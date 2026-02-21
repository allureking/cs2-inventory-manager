"""
Steam Community 库存服务

端点：GET https://steamcommunity.com/inventory/{steamid}/730/2
      ?l=english&count=500[&start_assetid={cursor}]

状态机（inventory_item.status）：
  in_steam    → 当前在 Steam 可见库存（可交易/可租）
  in_storage  → 推断存入储物柜（个人收藏，不计入持仓价值）
  rented_out  → 消失且储物柜无变化，推断出租中（仍属于我）
  sold        → Phase 3 出售记录确认

储物柜检测：
  Steam 储物柜 class_id 固定为 3604678661
  instance_id 随内容变化而变化 → 可检测存取事件
  存取推断（启发式）：
    同步中有物品消失 + 某个储物柜 instance_id 变化 → in_storage
    同步中有新物品出现 + 某个储物柜 instance_id 变化 → 从储物柜取出（in_steam）
    物品消失 + 储物柜无变化 → rented_out
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Tuple

import httpx
from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.db_models import InventoryItem, PriceSnapshot, StorageUnit
from app.schemas.steam import SteamAsset, SteamDescription, SteamInventoryResponse

logger = logging.getLogger(__name__)

STEAM_INVENTORY_URL = "https://steamcommunity.com/inventory/{steam_id}/730/2"
STORAGE_UNIT_CLASS_ID = "3604678661"

_BASE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def _build_cookies() -> Optional[Dict[str, str]]:
    if settings.steam_login_secure and settings.steam_session_id:
        return {
            "steamLoginSecure": settings.steam_login_secure,
            "sessionid": settings.steam_session_id,
        }
    return None


# ------------------------------------------------------------------ #
#  库存拉取（支持分页 + Cookie 认证）                                    #
# ------------------------------------------------------------------ #

async def fetch_inventory_pages(
    steam_id: str,
) -> Tuple[List[SteamAsset], Dict[str, SteamDescription], int]:
    """
    拉取完整顶层库存（不含储物柜内部物品），自动分页。
    返回 (assets, desc_map{classid_instanceid→desc}, total_count)
    """
    all_assets: List[SteamAsset] = []
    desc_map: Dict[str, SteamDescription] = {}
    total_count = 0
    cursor: Optional[str] = None
    cookies = _build_cookies()

    if cookies:
        logger.info("fetch_inventory_pages: Cookie 认证，可见全量顶层库存（含保护期）")
    else:
        logger.warning("fetch_inventory_pages: 无 Cookie，仅可见公开物品（不含7天保护期）")

    async with httpx.AsyncClient(timeout=30, headers=_BASE_HEADERS, cookies=cookies) as client:
        while True:
            params: dict = {"l": "english", "count": 500}
            if cursor:
                params["start_assetid"] = cursor

            r = await client.get(STEAM_INVENTORY_URL.format(steam_id=steam_id), params=params)

            if r.status_code == 403:
                raise PermissionError(
                    "库存为私密，或 Cookie 已失效。"
                    "请确认 Steam 隐私设置，或重新获取 .env 中的 Cookie。"
                )
            if r.status_code == 429:
                raise RuntimeError("Steam 请求频率过高，请稍后再试")
            r.raise_for_status()

            data = r.json()
            if not data.get("success"):
                raise RuntimeError(f"Steam 返回失败: {data}")

            inv = SteamInventoryResponse.model_validate(data)
            total_count = inv.total_inventory_count
            all_assets.extend(inv.assets)

            for desc in inv.descriptions:
                key = f"{desc.classid}_{desc.instanceid}"
                desc_map[key] = desc

            if not inv.more_items or not inv.last_assetid:
                break

            cursor = inv.last_assetid
            await asyncio.sleep(1.2)

    logger.info(
        "fetch_inventory_pages: %s  assets=%d  total=%d  authed=%s",
        steam_id, len(all_assets), total_count, cookies is not None,
    )
    return all_assets, desc_map, total_count


# ------------------------------------------------------------------ #
#  储物柜同步（检测 instance_id 变化）                                   #
# ------------------------------------------------------------------ #

async def _sync_storage_units(
    assets: List[SteamAsset],
    desc_map: Dict[str, SteamDescription],
    sid: str,
    now: datetime,
    db: AsyncSession,
) -> Set[str]:
    """
    更新 storage_unit 表，返回本次同步中 instance_id 发生变化的
    储物柜 asset_id 集合（表示该储物柜内容有变动）。
    """
    # 当前同步中的所有储物柜
    current_units: List[dict] = []
    for asset in assets:
        fp = f"{asset.classid}_{asset.instanceid}"
        desc = desc_map.get(fp)
        if asset.classid == STORAGE_UNIT_CLASS_ID and desc:
            current_units.append({
                "asset_id": asset.assetid,
                "class_id": asset.classid,
                "instance_id": asset.instanceid,
            })

    if not current_units:
        return set()

    # 读取 DB 中已知的储物柜（按 asset_id 匹配）
    known_result = await db.execute(
        select(StorageUnit).where(StorageUnit.steam_id == sid)
    )
    known_units: Dict[str, StorageUnit] = {u.asset_id: u for u in known_result.scalars().all()}

    changed_asset_ids: Set[str] = set()

    for unit in current_units:
        known = known_units.get(unit["asset_id"])
        if known:
            if known.instance_id != unit["instance_id"]:
                # instance_id 变化 → 储物柜内容有变动
                changed_asset_ids.add(unit["asset_id"])
                known.prev_instance_id = known.instance_id
                known.instance_id = unit["instance_id"]
                known.changed_in_last_sync = True
                known.last_synced_at = now
            else:
                known.changed_in_last_sync = False
                known.last_synced_at = now
        else:
            # 新发现的储物柜（首次同步）
            db.add(StorageUnit(
                steam_id=sid,
                asset_id=unit["asset_id"],
                class_id=unit["class_id"],
                instance_id=unit["instance_id"],
                changed_in_last_sync=False,
                first_seen_at=now,
                last_synced_at=now,
            ))

    # 清除已消失的储物柜（理论上储物柜不会消失，但做个清理）
    await db.flush()
    return changed_asset_ids


# ------------------------------------------------------------------ #
#  主同步逻辑                                                           #
# ------------------------------------------------------------------ #

async def sync_inventory(db: AsyncSession, steam_id: Optional[str] = None) -> dict:
    """
    从 Steam 拉取库存，智能同步到 inventory_item 表。

    状态推断逻辑：
    1. 物品仍在 Steam → status = in_steam
    2. in_steam 物品消失 + 同时某储物柜 instance_id 变化 → in_storage（存入了储物柜）
    3. in_steam 物品消失 + 储物柜无变化 → rented_out（租出/交易）
    4. 新出现物品 + 某储物柜变化 → 从储物柜取出，直接 in_steam，可录入购入价
    5. 新出现物品 + 储物柜无变化 → 新入手物品，in_steam
    6. in_storage 物品重新出现在顶层 → 从储物柜取出，恢复 in_steam
    """
    sid = steam_id or settings.steam_steam_id
    if not sid:
        raise ValueError("未配置 STEAM_STEAM_ID")

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    assets, desc_map, total_steam_count = await fetch_inventory_pages(sid)

    # ── 当次快照 ────────────────────────────────────────────────────
    # 储物柜单独处理，不进入 inventory_item 追踪
    current_items: Dict[str, Tuple[SteamAsset, SteamDescription]] = {}  # fp → (asset, desc)
    current_asset_ids: Set[str] = set()

    for asset in assets:
        fp = f"{asset.classid}_{asset.instanceid}"
        desc = desc_map.get(fp)
        if not desc:
            continue
        if asset.classid == STORAGE_UNIT_CLASS_ID:
            continue  # 储物柜容器本身不进 inventory_item
        current_items[fp] = (asset, desc)
        current_asset_ids.add(asset.assetid)

    # ── 储物柜变化检测 ───────────────────────────────────────────────
    changed_storage_units = await _sync_storage_units(assets, desc_map, sid, now, db)
    storage_changed = len(changed_storage_units) > 0

    # ── 读取 DB 现有记录 ─────────────────────────────────────────────
    db_result = await db.execute(
        select(InventoryItem).where(InventoryItem.steam_id == sid)
    )
    db_items: List[InventoryItem] = list(db_result.scalars().all())

    db_by_asset: Dict[str, InventoryItem] = {
        item.asset_id: item for item in db_items if item.asset_id
    }
    db_by_fp: Dict[str, InventoryItem] = {
        f"{item.class_id}_{item.instance_id}": item for item in db_items
    }

    # ── 处理当前在 Steam 中的物品 ────────────────────────────────────
    new_rows: List[dict] = []
    updated = 0
    from_storage_count = 0

    for fp, (asset, desc) in current_items.items():
        existing = db_by_asset.get(asset.assetid) or db_by_fp.get(fp)

        if existing:
            was_in_storage = existing.status == "in_storage"
            existing.asset_id = asset.assetid
            existing.status = "in_steam"
            existing.last_seen_in_steam_at = now
            existing.tradable = bool(desc.tradable)
            existing.marketable = bool(desc.marketable)
            existing.left_steam_at = None
            if was_in_storage:
                from_storage_count += 1
                logger.info("从储物柜取出: %s", desc.market_hash_name)
            updated += 1
        else:
            # 全新物品（可能是从储物柜取出的、或新购入的）
            note = "from_storage" if storage_changed else "new_purchase"
            new_rows.append({
                "steam_id": sid,
                "asset_id": asset.assetid,
                "class_id": asset.classid,
                "instance_id": asset.instanceid,
                "market_hash_name": desc.market_hash_name,
                "name": desc.name,
                "item_type": desc.type,
                "icon_url": desc.icon_url,
                "tradable": bool(desc.tradable),
                "marketable": bool(desc.marketable),
                "status": "in_steam",
                "last_seen_in_steam_at": now,
            })
            logger.info("新物品入库 [%s]: %s", note, desc.market_hash_name)

    inserted = 0
    if new_rows:
        stmt = sqlite_insert(InventoryItem).values(new_rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["steam_id", "class_id", "instance_id"],
            set_={
                "asset_id": stmt.excluded.asset_id,
                "status": "in_steam",
                "last_seen_in_steam_at": stmt.excluded.last_seen_in_steam_at,
                "tradable": stmt.excluded.tradable,
                "marketable": stmt.excluded.marketable,
                "left_steam_at": None,
            },
        )
        await db.execute(stmt)
        inserted = len(new_rows)

    # ── 处理从 Steam 消失的物品 ──────────────────────────────────────
    # 只对上次状态为 in_steam 的物品做推断（in_storage/rented_out/sold 不重复处理）
    newly_gone = [
        item for item in db_items
        if item.status == "in_steam"
        and item.asset_id not in current_asset_ids
        and f"{item.class_id}_{item.instance_id}" not in current_items
    ]

    into_storage_ids = []
    rented_out_ids = []

    for item in newly_gone:
        if storage_changed:
            # 启发式：储物柜有变动，推断存入了储物柜
            into_storage_ids.append(item.id)
            logger.info("推断存入储物柜: %s", item.market_hash_name)
        else:
            # 储物柜无变动，推断租出/交易走了
            rented_out_ids.append(item.id)
            logger.info("推断租出/离库: %s", item.market_hash_name)

    if into_storage_ids:
        await db.execute(
            update(InventoryItem)
            .where(InventoryItem.id.in_(into_storage_ids))
            .values(status="in_storage", left_steam_at=now)
        )

    if rented_out_ids:
        await db.execute(
            update(InventoryItem)
            .where(InventoryItem.id.in_(rented_out_ids))
            .values(status="rented_out", left_steam_at=now)
        )

    await db.commit()

    stats = {
        "steam_id": sid,
        "authenticated": bool(_build_cookies()),
        "total_steam_count": total_steam_count,
        "visible_items": len(current_items),
        "storage_units_found": len([a for a in assets if a.classid == STORAGE_UNIT_CLASS_ID]),
        "storage_units_changed": len(changed_storage_units),
        "updated": updated,
        "inserted": inserted,
        "newly_in_storage": len(into_storage_ids),
        "newly_rented_out": len(rented_out_ids),
        "returned_from_storage": from_storage_count,
    }
    logger.info("sync_inventory: %s", stats)
    return stats


# ------------------------------------------------------------------ #
#  库存列表 + 持仓汇总                                                   #
# ------------------------------------------------------------------ #

async def get_inventory_with_prices(
    db: AsyncSession,
    steam_id: Optional[str] = None,
    status_filter: Optional[List[str]] = None,
) -> List[dict]:
    """
    返回持仓列表，附 BUFF/悠悠/Steam 最新快照价格。
    默认返回全持仓（in_steam + rented_out），不含 in_storage（收藏品）。
    """
    sid = steam_id or settings.steam_steam_id
    if status_filter is None:
        status_filter = ["in_steam", "rented_out"]

    items = list((await db.execute(
        select(InventoryItem)
        .where(InventoryItem.steam_id == sid)
        .where(InventoryItem.status.in_(status_filter))
        .order_by(InventoryItem.market_hash_name)
    )).scalars().all())

    if not items:
        return []

    hash_names = list({item.market_hash_name for item in items})
    price_map = await _batch_latest_prices(hash_names, db)

    result = []
    for item in items:
        prices = price_map.get(item.market_hash_name, {})
        buff_price = prices.get("BUFF")
        youpin_price = prices.get("YOUPIN")
        steam_price = prices.get("STEAM")

        profit_loss = profit_pct = None
        if item.purchase_price and buff_price:
            profit_loss = round(buff_price - item.purchase_price, 2)
            profit_pct = round(profit_loss / item.purchase_price * 100, 2)

        result.append({
            "asset_id": item.asset_id,
            "class_id": item.class_id,
            "instance_id": item.instance_id,
            "market_hash_name": item.market_hash_name,
            "name": item.name,
            "item_type": item.item_type,
            "icon_url": item.icon_url,
            "tradable": item.tradable,
            "marketable": item.marketable,
            "status": item.status,
            "purchase_price": item.purchase_price,
            "purchase_date": item.purchase_date,
            "purchase_platform": item.purchase_platform,
            "first_seen_at": item.first_seen_at.isoformat() if item.first_seen_at else None,
            "last_seen_in_steam_at": item.last_seen_in_steam_at.isoformat() if item.last_seen_in_steam_at else None,
            "left_steam_at": item.left_steam_at.isoformat() if item.left_steam_at else None,
            "buff_sell_price": buff_price,
            "youpin_sell_price": youpin_price,
            "steam_sell_price": steam_price,
            "snapshot_minute": prices.get("_minute"),
            "profit_loss": profit_loss,
            "profit_pct": profit_pct,
        })

    return result


async def get_portfolio_summary(db: AsyncSession, steam_id: Optional[str] = None) -> dict:
    """
    总持仓价值汇总。
    in_storage 物品（个人收藏）不计入持仓价值，但单独列出数量。
    """
    sid = steam_id or settings.steam_steam_id

    all_active = await get_inventory_with_prices(db, sid, ["in_steam", "rented_out"])
    storage_count_result = await db.execute(
        select(InventoryItem)
        .where(InventoryItem.steam_id == sid, InventoryItem.status == "in_storage")
    )
    storage_count = len(list(storage_count_result.scalars().all()))

    def _group(status_list: List[str]) -> dict:
        subset = [i for i in all_active if i["status"] in status_list]
        buff_vals = [i["buff_sell_price"] for i in subset if i["buff_sell_price"]]
        costs = [i["purchase_price"] for i in subset if i["purchase_price"]]
        return {
            "count": len(subset),
            "priced_count": len(buff_vals),
            "costed_count": len(costs),
            "buff_value": round(sum(buff_vals), 2),
            "total_cost": round(sum(costs), 2),
        }

    in_steam = _group(["in_steam"])
    rented_out = _group(["rented_out"])
    total_buff = in_steam["buff_value"] + rented_out["buff_value"]
    total_cost = in_steam["total_cost"] + rented_out["total_cost"]
    profit = round(total_buff - total_cost, 2) if total_cost else None

    return {
        "portfolio": {
            "count": in_steam["count"] + rented_out["count"],
            "buff_value": round(total_buff, 2),
            "total_cost": round(total_cost, 2),
            "profit_loss": profit,
            "profit_pct": round(profit / total_cost * 100, 2) if profit and total_cost else None,
        },
        "in_steam": in_steam,
        "rented_out": rented_out,
        "in_storage_count": storage_count,   # 收藏品，不计入持仓
        "authenticated": bool(_build_cookies()),
    }


# ------------------------------------------------------------------ #
#  内部工具                                                             #
# ------------------------------------------------------------------ #

async def _batch_latest_prices(
    hash_names: List[str],
    db: AsyncSession,
) -> Dict[str, Dict[str, object]]:
    if not hash_names:
        return {}

    from sqlalchemy import func as sqlfunc

    subq = (
        select(
            PriceSnapshot.market_hash_name,
            sqlfunc.max(PriceSnapshot.snapshot_minute).label("latest_minute"),
        )
        .where(PriceSnapshot.market_hash_name.in_(hash_names))
        .group_by(PriceSnapshot.market_hash_name)
        .subquery()
    )

    rows = list((await db.execute(
        select(PriceSnapshot)
        .join(
            subq,
            (PriceSnapshot.market_hash_name == subq.c.market_hash_name)
            & (PriceSnapshot.snapshot_minute == subq.c.latest_minute),
        )
        .where(PriceSnapshot.platform.in_(["BUFF", "YOUPIN", "STEAM"]))
    )).scalars().all())

    result: Dict[str, Dict[str, object]] = {}
    for row in rows:
        if row.market_hash_name not in result:
            result[row.market_hash_name] = {"_minute": row.snapshot_minute}
        if row.sell_price:
            result[row.market_hash_name][row.platform] = row.sell_price

    return result
