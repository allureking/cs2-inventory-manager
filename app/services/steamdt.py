"""
SteamDT Open Platform API 客户端

接口速率限制：
  /price/single  — 60 次/分钟
  /price/batch   — 1 次/分钟，每次最多 100 个
  /price/avg     — 未标注（保守估计 60 次/分钟）
  /base          — 1 次/天
"""

import json
import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.db_models import Item, ItemAvgPrice, PriceSnapshot
from app.schemas.steamdt import (
    AveragePriceVO,
    BaseInfoVO,
    BatchPlatformPriceVO,
    PlatformPriceVO,
    SteamDTResponse,
)

logger = logging.getLogger(__name__)

BASE_URL = settings.steamdt_base_url


def _auth_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.steamdt_api_key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _snapshot_minute() -> str:
    """返回当前 UTC 时间精确到分钟的字符串，用于去重 key"""
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M")


def _today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def _check_response(resp: SteamDTResponse) -> None:
    """统一检查 API 响应，非成功时抛出异常"""
    if not resp.success:
        raise ValueError(f"SteamDT API error [{resp.error_code}]: {resp.error_msg}")


# ------------------------------------------------------------------ #
#  单品价格查询                                                         #
# ------------------------------------------------------------------ #

async def fetch_single_price(
    market_hash_name: str,
    db: AsyncSession,
) -> list[PlatformPriceVO]:
    """
    GET /open/cs2/v1/price/single
    查询单个饰品在所有平台的实时价格，并写入 price_snapshot。
    """
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(
            f"{BASE_URL}/open/cs2/v1/price/single",
            params={"marketHashName": market_hash_name},
            headers=_auth_headers(),
        )
        r.raise_for_status()

    resp = SteamDTResponse.model_validate(r.json())
    _check_response(resp)

    items: list[PlatformPriceVO] = [
        PlatformPriceVO.model_validate(p) for p in (resp.data or [])
    ]

    await _upsert_price_snapshots(market_hash_name, items, db)
    return items


# ------------------------------------------------------------------ #
#  批量价格查询                                                         #
# ------------------------------------------------------------------ #

async def fetch_batch_prices(
    market_hash_names: list[str],
    db: AsyncSession,
) -> list[BatchPlatformPriceVO]:
    """
    POST /open/cs2/v1/price/batch
    批量查询饰品实时价格（最多 100 个/次），并写入 price_snapshot。
    """
    if len(market_hash_names) > 100:
        raise ValueError("批量查询最多支持 100 个饰品")

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(
            f"{BASE_URL}/open/cs2/v1/price/batch",
            json={"marketHashNames": market_hash_names},
            headers=_auth_headers(),
        )
        r.raise_for_status()

    resp = SteamDTResponse.model_validate(r.json())
    _check_response(resp)

    results: list[BatchPlatformPriceVO] = [
        BatchPlatformPriceVO.model_validate(item) for item in (resp.data or [])
    ]

    for batch_item in results:
        await _upsert_price_snapshots(batch_item.market_hash_name, batch_item.data_list, db)

    return results


# ------------------------------------------------------------------ #
#  7 天均价查询                                                         #
# ------------------------------------------------------------------ #

async def fetch_avg_price(
    market_hash_name: str,
    db: AsyncSession,
    days: int = 7,
) -> AveragePriceVO:
    """
    GET /open/cs2/v1/price/avg
    查询近 N 天均价，并写入 item_avg_price。
    """
    params: dict[str, str | int] = {"marketHashName": market_hash_name}
    if days != 7:
        params["days"] = days

    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(
            f"{BASE_URL}/open/cs2/v1/price/avg",
            params=params,
            headers=_auth_headers(),
        )
        r.raise_for_status()

    resp = SteamDTResponse.model_validate(r.json())
    _check_response(resp)

    avg_vo = AveragePriceVO.model_validate(resp.data)
    await _upsert_avg_prices(avg_vo, days, db)
    return avg_vo


# ------------------------------------------------------------------ #
#  基础信息全量同步（1 次/天）                                           #
# ------------------------------------------------------------------ #

async def sync_base_info(db: AsyncSession) -> int:
    """
    GET /open/cs2/v1/base
    全量拉取所有 CS2 饰品基础信息，upsert 到 item 表。
    返回写入条数。
    """
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(
            f"{BASE_URL}/open/cs2/v1/base",
            headers=_auth_headers(),
        )
        r.raise_for_status()

    resp = SteamDTResponse.model_validate(r.json())
    _check_response(resp)

    base_list: list[BaseInfoVO] = [
        BaseInfoVO.model_validate(item) for item in (resp.data or [])
    ]

    count = 0
    for chunk in _chunked(base_list, 500):
        rows = [
            {
                "market_hash_name": b.market_hash_name,
                "name": b.name,
                "platform_ids_json": json.dumps(
                    {p.name: p.item_id for p in b.platform_list},
                    ensure_ascii=False,
                ),
            }
            for b in chunk
        ]
        stmt = sqlite_insert(Item).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["market_hash_name"],
            set_={
                "name": stmt.excluded.name,
                "platform_ids_json": stmt.excluded.platform_ids_json,
            },
        )
        await db.execute(stmt)
        count += len(rows)

    await db.commit()
    logger.info("sync_base_info: upserted %d items", count)
    return count


# ------------------------------------------------------------------ #
#  数据库工具函数                                                        #
# ------------------------------------------------------------------ #

async def _upsert_price_snapshots(
    market_hash_name: str,
    platforms: list[PlatformPriceVO],
    db: AsyncSession,
) -> None:
    """将平台价格列表写入 price_snapshot（按分钟去重）"""
    minute = _snapshot_minute()
    rows = [
        {
            "market_hash_name": market_hash_name,
            "platform": p.platform,
            "platform_item_id": p.platform_item_id,
            "sell_price": p.sell_price,
            "sell_count": p.sell_count,
            "bidding_price": p.bidding_price,
            "bidding_count": p.bidding_count,
            "api_update_time": p.update_time,
            "snapshot_minute": minute,
        }
        for p in platforms
    ]
    if not rows:
        return

    stmt = sqlite_insert(PriceSnapshot).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["market_hash_name", "platform", "snapshot_minute"],
        set_={
            "sell_price": stmt.excluded.sell_price,
            "sell_count": stmt.excluded.sell_count,
            "bidding_price": stmt.excluded.bidding_price,
            "bidding_count": stmt.excluded.bidding_count,
            "api_update_time": stmt.excluded.api_update_time,
        },
    )
    await db.execute(stmt)
    await db.commit()


async def _upsert_avg_prices(
    avg_vo: AveragePriceVO,
    days: int,
    db: AsyncSession,
) -> None:
    """将均价数据写入 item_avg_price（按日期去重）"""
    today = _today_str()
    rows = []

    # 跨平台综合均价
    if avg_vo.avg_price is not None:
        rows.append({
            "market_hash_name": avg_vo.market_hash_name,
            "platform": "ALL",
            "days": days,
            "avg_price": avg_vo.avg_price,
            "record_date": today,
        })

    # 各平台均价
    for p in avg_vo.data_list:
        rows.append({
            "market_hash_name": avg_vo.market_hash_name,
            "platform": p.platform,
            "days": days,
            "avg_price": p.avg_price,
            "record_date": today,
        })

    if not rows:
        return

    stmt = sqlite_insert(ItemAvgPrice).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["market_hash_name", "platform", "days", "record_date"],
        set_={"avg_price": stmt.excluded.avg_price},
    )
    await db.execute(stmt)
    await db.commit()


async def get_latest_snapshots(
    market_hash_name: str,
    db: AsyncSession,
) -> list[PriceSnapshot]:
    """从 DB 获取某饰品最新一分钟的价格快照（不调 API）"""
    subq = (
        select(PriceSnapshot.snapshot_minute)
        .where(PriceSnapshot.market_hash_name == market_hash_name)
        .order_by(PriceSnapshot.snapshot_minute.desc())
        .limit(1)
        .scalar_subquery()
    )
    result = await db.execute(
        select(PriceSnapshot).where(
            PriceSnapshot.market_hash_name == market_hash_name,
            PriceSnapshot.snapshot_minute == subq,
        )
    )
    return list(result.scalars().all())


def _chunked(lst: list, size: int):
    for i in range(0, len(lst), size):
        yield lst[i : i + size]
