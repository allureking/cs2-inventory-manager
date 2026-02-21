"""
悠悠有品 API 集成服务

功能模块：
  ── 数据导入 ──
  import_stock_records()     → 悠悠在库存（保护期物品）→ inventory_item(in_steam)
  import_lease_records()     → 当前租出订单          → inventory_item(rented_out)
  import_buy_records()       → 购买记录匹配购入价
  import_sell_records()      → 出售记录标记 sold

  ── 模板ID同步 ──
  sync_template_ids()        → 从悠悠完整库存同步 youpin_template_id

  ── 市场价格 ──
  fetch_market_sell_price()  → 查单个饰品悠悠卖出市价
  fetch_market_lease_price() → 查单个饰品悠悠租赁市价
  bulk_refresh_market_prices() → 批量刷新全量活跃持仓市价（写入 price_snapshot）

  ── Token 管理 ──
  check_token_status()       → 验证 Token 是否有效（返回 bool + 用户信息）

认证说明：
  - 普通接口：uk 使用 65 位随机字符串（快速，无需加密请求）
  - PC 市场查询接口：uk 使用 RSA+AES 加密真实值（缓存 30 秒）
  - Token 过期：响应 code=84101，所有接口统一抛 TokenExpiredError
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import random
import string
import time
import uuid
from datetime import datetime, timezone
from typing import List, Optional

import httpx
from Crypto.Cipher import AES, PKCS1_v1_5
from Crypto.PublicKey import RSA
from Crypto.Util.Padding import pad, unpad
from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.db_models import InventoryItem, PriceSnapshot

logger = logging.getLogger(__name__)

YOUPIN_API = "https://api.youpin898.com"

_RSA_PUBLIC_KEY = (
    "-----BEGIN PUBLIC KEY-----\n"
    "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAv9BDdhCDahZNFuJeesx3\n"
    "gzoQfD7pE0AeWiNBZlc21ph6kU9zd58X/1warV3C1VIX0vMAmhOcj5u86i+L2Lb2\n"
    "V68dX2Nb70MIDeW6Ibe8d0nF8D30tPsM7kaAyvxkY6ECM6RHGNhV4RrzkHmf5DeR\n"
    "9bybQGE0A9jcjuxszD1wsW/n19eeom7MroHqlRorp5LLNR8bSbmhTw6M/RQ/Fm3l\n"
    "KjKcvs1QNVyBNimrbD+ZVPE/KHSZLQ1jdF6tppvFnGxgJU9NFmxGFU0hx6cZiQHk\n"
    "hOQfGDFkElxgtj8gFJ1narTwYbvfe5nGSiznv/EUJSjTHxzX1TEkex0+5j4vSANt\n"
    "1QIDAQAB\n"
    "-----END PUBLIC KEY-----"
)


# ── 自定义异常 ─────────────────────────────────────────────────────────────

class TokenExpiredError(Exception):
    """悠悠有品 Token 已过期（code=84101），需要重新登录获取 Token"""


# ── RSA+AES uk 生成（带 30 秒缓存） ────────────────────────────────────────

_uk_cache: dict = {"value": None, "expires_at": 0.0}


def _rand_str(n: int) -> str:
    return "".join(random.choices(string.ascii_letters + string.digits, k=n))


def _get_real_uk() -> str:
    """
    向 /api/deviceW2 获取真实 uk（RSA+AES 加密协议）。
    结果缓存 30 秒，避免频繁加密请求。
    仅在需要 PC 端市场查询时使用，普通接口用随机字符串即可。
    """
    now = time.time()
    if _uk_cache["value"] and now < _uk_cache["expires_at"]:
        return _uk_cache["value"]

    aes_key = _rand_str(16).encode()

    cipher_aes = AES.new(aes_key, AES.MODE_ECB)
    payload = json.dumps({"iud": str(uuid.uuid4())})
    enc_data = base64.b64encode(
        cipher_aes.encrypt(pad(payload.encode(), AES.block_size))
    ).decode()

    pub = RSA.import_key(_RSA_PUBLIC_KEY)
    enc_key = base64.b64encode(PKCS1_v1_5.new(pub).encrypt(aes_key)).decode()

    resp = httpx.post(
        f"{YOUPIN_API}/api/deviceW2",
        json={"encryptedData": enc_data, "encryptedAesKey": enc_key},
        timeout=10,
    )
    resp.raise_for_status()

    cipher_aes2 = AES.new(aes_key, AES.MODE_ECB)
    result = json.loads(
        unpad(cipher_aes2.decrypt(base64.b64decode(resp.content)), AES.block_size).decode()
    )
    uk = result["u"]
    _uk_cache["value"] = uk
    _uk_cache["expires_at"] = now + 28.0
    return uk


# ── HTTP Headers ────────────────────────────────────────────────────────────

def _headers(pc_market: bool = False) -> dict:
    """
    构建悠悠 API 请求头。

    pc_market=True  → 使用 RSA+AES 真实 uk + platform=pc
                      仅用于市场价格查询接口（queryOnSaleCommodityList）
    pc_market=False → uk 使用随机字符串（快速，适用于绝大多数接口）
    """
    token = settings.youpin_token
    device_id = settings.youpin_device_id or str(uuid.uuid4())

    if pc_market:
        try:
            uk = _get_real_uk()
        except Exception as e:
            logger.warning("获取真实 uk 失败，使用随机值: %s", e)
            uk = _rand_str(65)
        platform = "pc"
    else:
        uk = _rand_str(65)
        platform = "android"

    return {
        "authorization": f"Bearer {token}",
        "content-type": "application/json",
        "user-agent": "okhttp/3.14.9",
        "app-version": "5.28.3",
        "apptype": "4",
        "appversion": "5.28.3",
        "platform": platform,
        "deviceid": device_id,
        "devicetype": "1",
        "uk": uk,
        "gameid": "730",
        "accept": "application/json, text/plain, */*",
    }


# ── 响应统一校验 ────────────────────────────────────────────────────────────

def _check(body: dict, source: str = "API") -> None:
    """
    统一校验悠悠 API 响应 code 字段。
    - code=84101 → TokenExpiredError（需要重新登录）
    - code≠0     → RuntimeError
    """
    code = body.get("Code", body.get("code"))
    if code == 84101:
        raise TokenExpiredError("悠悠有品 Token 已过期（code=84101），请重新获取 Token")
    if code not in (0, None):
        msg = body.get("Msg", body.get("msg", "未知错误"))
        raise RuntimeError(f"{source} 错误 [{code}]: {msg}")


def _data(body: dict) -> dict | list:
    return body.get("Data", body.get("data")) or {}


# ── Token 状态检测 ──────────────────────────────────────────────────────────

async def check_token_status() -> dict:
    """
    验证当前 Token 是否有效，返回:
      {"valid": bool, "nickname": str | None, "error": str | None}
    """
    if not settings.youpin_token:
        return {"valid": False, "nickname": None, "error": "Token 未配置（.env 中 YOUPIN_TOKEN 为空）"}

    try:
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.get(
                f"{YOUPIN_API}/api/user/Account/getUserInfo",
                headers=_headers(),
            )
        resp.raise_for_status()
        body = resp.json()
        _check(body, "getUserInfo")
        data = _data(body)
        nickname = None
        if isinstance(data, dict):
            nickname = data.get("NickName") or data.get("nickName")
        return {"valid": True, "nickname": nickname, "error": None}
    except TokenExpiredError as e:
        return {"valid": False, "nickname": None, "error": str(e)}
    except Exception as e:
        return {"valid": False, "nickname": None, "error": f"检测失败: {e}"}


# ── 原始数据拉取 ────────────────────────────────────────────────────────────

async def fetch_lease_records(page: int = 1, page_size: int = 30) -> tuple:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{YOUPIN_API}/api/youpin/bff/trade/v1/order/lease/out/list",
            headers=_headers(),
            json={"pageIndex": page, "pageSize": page_size, "gameId": 730},
        )
    resp.raise_for_status()
    body = resp.json()
    _check(body, "lease_records")
    data = _data(body)
    records = data.get("orderDataList", []) if isinstance(data, dict) else []
    total_count = data.get("totalCount", 0) if isinstance(data, dict) else 0
    stats_desc = data.get("statisticsDataDesc", "") if isinstance(data, dict) else ""
    return records, total_count, stats_desc


async def fetch_buy_records(page: int = 1, page_size: int = 30) -> list:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{YOUPIN_API}/api/youpin/bff/trade/sale/v1/buy/list",
            headers=_headers(),
            json={"pageIndex": page, "pageSize": page_size, "gameId": 730},
        )
    resp.raise_for_status()
    body = resp.json()
    _check(body, "buy_records")
    data = _data(body)
    if isinstance(data, list):
        return data
    for key in ("list", "List", "orderList", "OrderList", "data"):
        if isinstance(data.get(key), list):
            return data[key]
    return []


async def fetch_sell_records(page: int = 1, page_size: int = 30) -> list:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{YOUPIN_API}/api/youpin/bff/trade/sale/v1/sell/list",
            headers=_headers(),
            json={"pageIndex": page, "pageSize": page_size, "gameId": 730},
        )
    resp.raise_for_status()
    body = resp.json()
    _check(body, "sell_records")
    data = _data(body)
    if isinstance(data, list):
        return data
    for key in ("list", "List", "orderList", "OrderList", "data"):
        if isinstance(data.get(key), list):
            return data[key]
    return []


async def fetch_stock_records(page: int = 1, page_size: int = 100) -> tuple:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{YOUPIN_API}/api/youpin/pc/inventory/list",
            headers=_headers(),
            json={"pageIndex": page, "pageSize": page_size},
        )
    resp.raise_for_status()
    body = resp.json()
    _check(body, "stock_records")
    data = _data(body)
    records = data.get("itemsInfos", []) if isinstance(data, dict) else []
    total_count = data.get("totalCount", 0) if isinstance(data, dict) else 0
    valuation = data.get("valuation", "") if isinstance(data, dict) else ""
    return records or [], total_count, valuation


async def fetch_full_inventory(page: int = 1, page_size: int = 500) -> tuple:
    """
    拉取悠悠完整库存（GetUserInventoryDataListV3），包含 templateId（ItemId）。
    用于同步 youpin_template_id 到 inventory_item。
    """
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            f"{YOUPIN_API}/api/commodity/Inventory/GetUserInventoryDataListV3",
            headers=_headers(),
            json={
                "pageIndex": page,
                "pageSize": page_size,
                "gameId": "730",
                "appType": 4,
            },
        )
    resp.raise_for_status()
    body = resp.json()
    _check(body, "full_inventory")
    data = _data(body)
    if isinstance(data, dict):
        items = data.get("Items", data.get("items", data.get("data", [])))
        total = data.get("TotalCount", data.get("totalCount", 0))
        return items or [], total
    if isinstance(data, list):
        return data, len(data)
    return [], 0


# ── 市场价格查询 ────────────────────────────────────────────────────────────

async def fetch_market_sell_price(
    template_id: int,
    abrade: Optional[float] = None,
    page_size: int = 10,
) -> list[dict]:
    """
    查询悠悠市场出售价格列表（PC端接口，需要真实 uk）。
    返回最多 page_size 条挂单，按价格升序。
    """
    payload: dict = {
        "listSortType": "2",  # 价格升序
        "pageIndex": 1,
        "pageSize": page_size,
        "templateId": template_id,
        "gameId": "730",
    }
    if abrade is not None:
        payload["abrade"] = abrade

    async with httpx.AsyncClient(timeout=12) as client:
        resp = await client.post(
            f"{YOUPIN_API}/api/homepage/pc/goods/market/queryOnSaleCommodityList",
            headers=_headers(pc_market=True),
            json=payload,
        )
    resp.raise_for_status()
    body = resp.json()
    _check(body, "market_sell_price")
    data = _data(body)
    if isinstance(data, dict):
        return data.get("commodityList", data.get("list", []))
    if isinstance(data, list):
        return data
    return []


async def fetch_market_lease_price(
    template_id: int,
    page_size: int = 20,
) -> list[dict]:
    """
    查询悠悠市场出租价格列表。
    返回最多 page_size 条挂租，按租金升序。
    """
    async with httpx.AsyncClient(timeout=12) as client:
        resp = await client.post(
            f"{YOUPIN_API}/api/homepage/v3/detail/commodity/list/lease",
            headers=_headers(),
            json={
                "templateId": template_id,
                "pageSize": page_size,
                "status": "20",
                "hasLease": "true",
                "gameId": "730",
            },
        )
    resp.raise_for_status()
    body = resp.json()
    _check(body, "market_lease_price")
    data = _data(body)
    if isinstance(data, dict):
        return data.get("commodityList", data.get("list", []))
    if isinstance(data, list):
        return data
    return []


# ── 批量刷新市场价格 ────────────────────────────────────────────────────────

_ACTIVE = ["in_steam", "rented_out", "in_storage"]

# 后台刷新状态（供 dashboard 轮询）
market_refresh_state: dict = {
    "status": "idle",       # idle | running | done | error
    "progress": 0,
    "total": 0,
    "done": 0,
    "started_at": None,
    "finished_at": None,
    "error": None,
    "price_updated_at": None,
}


def _snapshot_minute() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M")


async def _upsert_youpin_price(
    market_hash_name: str,
    sell_price: Optional[float],
    db: AsyncSession,
) -> None:
    """将悠悠市价写入 price_snapshot（platform="YOUPIN"）"""
    if sell_price is None or sell_price <= 0:
        return
    minute = _snapshot_minute()
    stmt = sqlite_insert(PriceSnapshot).values([{
        "market_hash_name": market_hash_name,
        "platform": "YOUPIN",
        "sell_price": sell_price,
        "snapshot_minute": minute,
    }])
    stmt = stmt.on_conflict_do_update(
        index_elements=["market_hash_name", "platform", "snapshot_minute"],
        set_={"sell_price": stmt.excluded.sell_price},
    )
    await db.execute(stmt)


async def bulk_refresh_market_prices(db: AsyncSession) -> None:
    """
    全量刷新活跃持仓的悠悠市价：
    1. 查询有 youpin_template_id 的活跃物品（按 templateId 去重）
    2. 逐个请求悠悠市场价格（每请求间 sleep 0.5s 避免被限速）
    3. 写入 price_snapshot（platform=YOUPIN）

    无 templateId 的物品跳过（需先 sync_template_ids）。
    """
    global market_refresh_state
    market_refresh_state.update(
        status="running", progress=0, done=0, error=None,
        started_at=datetime.now(timezone.utc).isoformat(),
    )

    try:
        from app.core.database import AsyncSessionLocal

        # 查所有有 templateId 的活跃物品（按 templateId + market_hash_name 去重）
        async with AsyncSessionLocal() as sess:
            rows = (await sess.execute(
                select(
                    InventoryItem.youpin_template_id,
                    InventoryItem.market_hash_name,
                    func.min(InventoryItem.abrade).label("abrade"),
                )
                .where(
                    InventoryItem.status.in_(_ACTIVE),
                    InventoryItem.youpin_template_id.isnot(None),
                )
                .group_by(InventoryItem.youpin_template_id, InventoryItem.market_hash_name)
            )).all()

        items = [(r[0], r[1], r[2]) for r in rows]
        total = len(items)
        market_refresh_state["total"] = total

        if total == 0:
            market_refresh_state.update(
                status="done", progress=100,
                finished_at=datetime.now(timezone.utc).isoformat(),
                price_updated_at=_snapshot_minute(),
            )
            return

        for idx, (template_id, hash_name, abrade) in enumerate(items):
            try:
                price_list = await fetch_market_sell_price(template_id, abrade)
                # 取最低非零卖价
                prices = [
                    float(p.get("price", p.get("Price", 0)) or 0)
                    for p in price_list
                    if p.get("price") or p.get("Price")
                ]
                sell_price = min((p for p in prices if p > 0), default=None)

                async with AsyncSessionLocal() as sess:
                    await _upsert_youpin_price(hash_name, sell_price, sess)
                    await sess.commit()

            except TokenExpiredError:
                raise
            except Exception as e:
                logger.warning("获取市价失败 [%s]: %s", hash_name, e)

            market_refresh_state["done"] = idx + 1
            market_refresh_state["progress"] = int((idx + 1) / total * 100)
            await asyncio.sleep(0.5)

        now_str = _snapshot_minute()
        market_refresh_state.update(
            status="done", progress=100,
            finished_at=datetime.now(timezone.utc).isoformat(),
            price_updated_at=now_str,
        )

    except TokenExpiredError as e:
        market_refresh_state.update(
            status="token_expired", error=str(e),
            finished_at=datetime.now(timezone.utc).isoformat(),
        )
    except Exception as e:
        market_refresh_state.update(
            status="error", error=str(e),
            finished_at=datetime.now(timezone.utc).isoformat(),
        )


# ── 模板 ID 同步 ────────────────────────────────────────────────────────────

async def sync_template_ids(db: AsyncSession) -> dict:
    """
    从悠悠完整库存（GetUserInventoryDataListV3）同步 youpin_template_id。
    对 market_hash_name 相同的记录批量更新 templateId。
    返回 {"synced": int, "total_fetched": int}
    """
    all_items: list[dict] = []
    page = 1

    first, total = await fetch_full_inventory(page=1, page_size=500)
    all_items.extend(first)

    total_pages = (total + 499) // 500 if total > 500 else 1
    for p in range(2, total_pages + 1):
        batch, _ = await fetch_full_inventory(page=p, page_size=500)
        if not batch:
            break
        all_items.extend(batch)

    # 构建 market_hash_name → templateId 映射
    name_to_tid: dict[str, int] = {}
    for item in all_items:
        # 字段名可能是 ItemId / templateId / TemplateId / itemId
        tid = (item.get("ItemId") or item.get("templateId") or
               item.get("TemplateId") or item.get("itemId"))
        name = (item.get("commodityHashName") or item.get("CommodityHashName") or
                item.get("marketHashName") or item.get("MarketHashName"))
        if tid and name:
            name_to_tid[str(name)] = int(tid)

    if not name_to_tid:
        return {"synced": 0, "total_fetched": len(all_items),
                "note": "API 响应中未找到 templateId 字段，请检查响应结构"}

    # 批量更新 inventory_item
    synced = 0
    for hash_name, tid in name_to_tid.items():
        result = await db.execute(
            select(InventoryItem)
            .where(
                InventoryItem.market_hash_name == hash_name,
                InventoryItem.youpin_template_id.is_(None),
            )
        )
        items_to_update = result.scalars().all()
        for it in items_to_update:
            it.youpin_template_id = tid
            synced += 1

    await db.commit()
    return {"synced": synced, "total_fetched": len(all_items),
            "unique_names_mapped": len(name_to_tid)}


# ── 数据解析工具 ────────────────────────────────────────────────────────────

def _parse_hash_name(record: dict) -> Optional[str]:
    detail = record.get("productDetail") or {}
    return detail.get("commodityHashName") or None


def _parse_abrade(record: dict) -> Optional[float]:
    detail = record.get("productDetail") or {}
    raw = detail.get("abrade") or detail.get("commodityAbrade")
    if raw:
        try:
            v = float(raw)
            return v if v > 0 else None
        except (TypeError, ValueError):
            pass
    return None


def _parse_price(record: dict) -> Optional[float]:
    v = record.get("totalAmount")
    if v is not None:
        try:
            return float(v) / 100
        except (TypeError, ValueError):
            pass
    return None


def _parse_qty(record: dict) -> int:
    for key in ("commodityNum", "count", "quantity", "goodsNum"):
        v = record.get(key)
        if v is not None:
            try:
                n = int(v)
                if n > 0:
                    return n
            except (TypeError, ValueError):
                pass
    return 1


def _parse_date(record: dict) -> Optional[str]:
    for key in ("createOrderTime", "finishOrderTime", "payTime"):
        ms = record.get(key)
        if ms:
            try:
                return datetime.utcfromtimestamp(int(ms) / 1000).strftime("%Y-%m-%d")
            except (TypeError, ValueError, OSError):
                pass
    return None


def _extract_template_id(info: dict) -> Optional[int]:
    """从各种可能字段中提取 templateId"""
    for key in ("templateId", "TemplateId", "ItemId", "itemId", "commodityTemplateId"):
        v = info.get(key)
        if v:
            try:
                return int(v)
            except (TypeError, ValueError):
                pass
    return None


# ── DB 写入：导入函数 ────────────────────────────────────────────────────────

async def import_stock_records(db: AsyncSession) -> dict:
    """全量拉取悠悠在库存物品，写入 inventory_item（status=in_steam）"""
    from app.core.config import settings as cfg

    all_records: list[dict] = []
    PAGE_SIZE = 100
    valuation = ""

    batch, total_count, valuation = await fetch_stock_records(page=1, page_size=PAGE_SIZE)
    all_records.extend(batch)

    for page in range(2, 50):
        try:
            batch, _, _ = await fetch_stock_records(page=page, page_size=PAGE_SIZE)
        except Exception as e:
            logger.error("拉取在库存第 %d 页失败: %s", page, e)
            break
        if not batch:
            break
        all_records.extend(batch)

    logger.info("共拉取在库存物品 %d 条", len(all_records))
    steam_id = cfg.steam_steam_id or "unknown"
    upserted, skipped = [], []

    for rec in all_records:
        asset_id = str(rec.get("steamAssetId") or "").strip()
        hash_name = (rec.get("marketHashName") or "").strip()
        name_cn = (rec.get("name") or hash_name).strip()
        is_merge = int(rec.get("isMerge") or 0)
        merge_count = int(rec.get("assetMergeCount") or 1) or 1

        abrade: Optional[float] = None
        raw_abrade = rec.get("abrade")
        if raw_abrade:
            try:
                v = float(raw_abrade)
                abrade = v if v > 0 else None
            except (TypeError, ValueError):
                pass

        template_id = _extract_template_id(rec)

        if not asset_id or not hash_name:
            skipped.append({"asset_id": asset_id, "hash_name": hash_name})
            continue

        result = await db.execute(
            select(InventoryItem).where(
                InventoryItem.steam_id == steam_id,
                InventoryItem.class_id == "STEAM_PROTECTED",
                InventoryItem.instance_id == asset_id,
            )
        )
        item = result.scalar_one_or_none()

        if item:
            item.status = "in_steam"
            item.asset_id = asset_id
            item.market_hash_name = hash_name
            item.name = name_cn
            item.abrade = abrade
            if template_id and not item.youpin_template_id:
                item.youpin_template_id = template_id
        else:
            item = InventoryItem(
                steam_id=steam_id,
                asset_id=asset_id,
                class_id="STEAM_PROTECTED",
                instance_id=asset_id,
                market_hash_name=hash_name,
                name=name_cn,
                tradable=False,
                marketable=True,
                status="in_steam",
                abrade=abrade,
                youpin_template_id=template_id,
            )
            db.add(item)

        upserted.append({
            "asset_id": asset_id,
            "market_hash_name": hash_name,
            "abrade": abrade,
            "is_merge": is_merge,
            "merge_count": merge_count,
        })

    await db.commit()
    return {
        "valuation": valuation,
        "total_fetched": len(all_records),
        "upserted": len(upserted),
        "skipped": len(skipped),
    }


async def import_lease_records(db: AsyncSession) -> dict:
    """全量拉取当前租出中订单，upsert 到 inventory_item（status=rented_out）"""
    from app.core.config import settings as cfg

    all_records: list[dict] = []
    PAGE_SIZE = 30
    stats_desc = ""

    batch, total_count, stats_desc = await fetch_lease_records(page=1, page_size=PAGE_SIZE)
    all_records.extend(batch)

    total_pages = (total_count + PAGE_SIZE - 1) // PAGE_SIZE
    for page in range(2, total_pages + 1):
        try:
            batch, _, _ = await fetch_lease_records(page=page, page_size=PAGE_SIZE)
        except Exception as e:
            logger.error("拉取租出记录第 %d 页失败: %s", page, e)
            break
        if not batch:
            break
        all_records.extend(batch)

    logger.info("共拉取悠悠租出记录 %d 条", len(all_records))
    steam_id = cfg.steam_steam_id or "unknown"
    upserted, skipped = [], []

    for rec in all_records:
        info = rec.get("commodityInfo") or {}
        commodity_id = info.get("commodityId")
        hash_name = info.get("commodityHashName")
        order_id = rec.get("orderId") or rec.get("orderNo")
        name_cn = info.get("name", hash_name or "")
        template_id = _extract_template_id(info)

        abrade: Optional[float] = None
        raw_abrade = info.get("abrade")
        if raw_abrade:
            try:
                v = float(raw_abrade)
                abrade = v if v > 0 else None
            except (TypeError, ValueError):
                pass

        if not commodity_id or not hash_name:
            skipped.append(order_id)
            continue

        result = await db.execute(
            select(InventoryItem).where(InventoryItem.youpin_commodity_id == commodity_id)
        )
        item = result.scalar_one_or_none()

        if item:
            item.youpin_order_id = str(order_id) if order_id else item.youpin_order_id
            item.status = "rented_out"
            item.market_hash_name = hash_name
            item.abrade = abrade
            if template_id and not item.youpin_template_id:
                item.youpin_template_id = template_id
        else:
            item = InventoryItem(
                steam_id=steam_id,
                asset_id=str(order_id),
                class_id="YOUPIN",
                instance_id=str(commodity_id),
                market_hash_name=hash_name,
                name=name_cn,
                tradable=True,
                marketable=True,
                status="rented_out",
                youpin_order_id=str(order_id) if order_id else None,
                youpin_commodity_id=commodity_id,
                abrade=abrade,
                youpin_template_id=template_id,
            )
            db.add(item)

        upserted.append({"commodity_id": commodity_id, "market_hash_name": hash_name,
                         "order_id": order_id})

    await db.commit()
    return {
        "stats": stats_desc,
        "total_fetched": len(all_records),
        "upserted": len(upserted),
        "skipped": len(skipped),
    }


async def import_buy_records(db: AsyncSession) -> dict:
    """全量拉取购买记录，匹配 inventory_item，写入 purchase_price"""
    all_records: list[dict] = []
    PAGE_SIZE = 30
    MAX_PAGES = 200

    page = 1
    while page <= MAX_PAGES:
        try:
            batch = await fetch_buy_records(page=page, page_size=PAGE_SIZE)
        except Exception as e:
            logger.error("拉取买入记录第 %d 页失败: %s", page, e)
            break
        if not batch:
            break
        all_records.extend(batch)
        if len(batch) < PAGE_SIZE:
            break
        page += 1

    logger.info("共拉取悠悠购买记录 %d 条", len(all_records))
    updated, skipped, not_found = [], [], []

    for rec in all_records:
        hash_name = _parse_hash_name(rec)
        if not hash_name:
            continue
        total_price = _parse_price(rec)
        qty = _parse_qty(rec)
        per_item_price = total_price / qty if total_price is not None else None
        date_str = _parse_date(rec)
        buy_abrade = _parse_abrade(rec)
        detail = rec.get("productDetail") or {}
        buy_commodity_id = detail.get("commodityId")
        buy_asset_id = str(detail.get("assertId") or "").strip()

        for _ in range(qty):
            item = None

            if buy_commodity_id:
                result = await db.execute(
                    select(InventoryItem)
                    .where(
                        InventoryItem.youpin_commodity_id == buy_commodity_id,
                        InventoryItem.purchase_price.is_(None),
                        InventoryItem.status.in_(["in_steam", "rented_out", "in_storage"]),
                    ).limit(1)
                )
                item = result.scalar_one_or_none()

            if not item and buy_asset_id:
                result = await db.execute(
                    select(InventoryItem)
                    .where(
                        InventoryItem.asset_id == buy_asset_id,
                        InventoryItem.class_id == "STEAM_PROTECTED",
                        InventoryItem.purchase_price.is_(None),
                        InventoryItem.status.in_(["in_steam", "rented_out", "in_storage"]),
                    ).limit(1)
                )
                item = result.scalar_one_or_none()

            if not item and buy_abrade is not None:
                result = await db.execute(
                    select(InventoryItem)
                    .where(
                        InventoryItem.market_hash_name == hash_name,
                        InventoryItem.purchase_price.is_(None),
                        InventoryItem.status.in_(["in_steam", "rented_out", "in_storage"]),
                        InventoryItem.abrade.isnot(None),
                        func.abs(InventoryItem.abrade - buy_abrade) < 1e-8,
                    ).limit(1)
                )
                item = result.scalar_one_or_none()

            if not item:
                result = await db.execute(
                    select(InventoryItem)
                    .where(
                        InventoryItem.market_hash_name == hash_name,
                        InventoryItem.purchase_price.is_(None),
                        InventoryItem.status.in_(["in_steam", "rented_out", "in_storage"]),
                        InventoryItem.abrade.is_(None),
                    ).limit(1)
                )
                item = result.scalar_one_or_none()

            if not item:
                not_found.append(hash_name)
                break

            if per_item_price is not None:
                item.purchase_price = per_item_price
            if date_str:
                item.purchase_date = date_str
            item.purchase_platform = "YOUPIN"
            updated.append({"asset_id": item.asset_id, "market_hash_name": hash_name,
                             "purchase_price": per_item_price})

    await db.commit()
    return {
        "total_records": len(all_records),
        "updated": len(updated),
        "not_found_in_db": len(not_found),
        "items": updated,
        "not_found_names": list(set(not_found))[:20],
    }


async def import_sell_records(db: AsyncSession) -> dict:
    """全量拉取出售记录，标记 inventory_item.status=sold"""
    all_records: list[dict] = []
    PAGE_SIZE = 30
    MAX_PAGES = 200

    page = 1
    while page <= MAX_PAGES:
        try:
            batch = await fetch_sell_records(page=page, page_size=PAGE_SIZE)
        except Exception as e:
            logger.error("拉取卖出记录第 %d 页失败: %s", page, e)
            break
        if not batch:
            break
        all_records.extend(batch)
        if len(batch) < PAGE_SIZE:
            break
        page += 1

    logger.info("共拉取悠悠出售记录 %d 条", len(all_records))
    updated, not_found = [], []

    for rec in all_records:
        hash_name = _parse_hash_name(rec)
        if not hash_name:
            continue

        result = await db.execute(
            select(InventoryItem)
            .where(
                InventoryItem.market_hash_name == hash_name,
                InventoryItem.status.in_(["in_steam", "rented_out"]),
                InventoryItem.class_id.notin_(["YOUPIN", "STEAM_PROTECTED"]),
            ).limit(1)
        )
        item = result.scalar_one_or_none()

        if not item:
            not_found.append(hash_name)
            continue

        old_status = item.status
        item.status = "sold"
        item.left_steam_at = item.left_steam_at or datetime.utcnow()
        updated.append({"asset_id": item.asset_id, "market_hash_name": hash_name,
                        "old_status": old_status})

    await db.commit()
    return {
        "total_records": len(all_records),
        "updated": len(updated),
        "not_found_in_db": len(not_found),
        "items": updated,
    }
