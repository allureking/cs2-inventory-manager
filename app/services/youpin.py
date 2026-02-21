"""
悠悠有品 PC-Web API 集成服务

功能：
  fetch_stock_records()  → 拉取在库存（Steam 保护期）物品
  fetch_lease_records()  → 拉取租出中订单
  fetch_buy_records()    → 拉取购买记录
  fetch_sell_records()   → 拉取出售记录
  import_stock_records() → 导入在库存物品（status=in_steam，写入 purchase_price）
  import_lease_records() → 导入租出物品（status=rented_out）
  import_buy_records()   → 匹配 inventory_item，写入 purchase_price / purchase_date
  import_sell_records()  → 匹配 inventory_item，标记 status=sold

Token 刷新：每次登录 PC 网页版后从 DevTools 复制新 token 写入 .env
"""

from __future__ import annotations

import base64
import json
import logging
import random
import string
import uuid
from datetime import datetime
from typing import List, Optional

import httpx
from Crypto.Cipher import AES, PKCS1_v1_5
from Crypto.PublicKey import RSA
from Crypto.Util.Padding import pad, unpad
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.db_models import InventoryItem

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


# ── RSA+AES uk 生成 ────────────────────────────────────────────────────────

def _rand_str(n: int) -> str:
    return "".join(random.choices(string.ascii_letters + string.digits, k=n))


def _get_uk() -> str:
    """向 /api/deviceW2 获取真实 uk（RSA+AES 加密协议，与 Steamauto 完全一致）"""
    aes_key = _rand_str(16).encode()

    # AES-ECB 加密 payload
    cipher_aes = AES.new(aes_key, AES.MODE_ECB)
    payload = json.dumps({"iud": str(uuid.uuid4())})
    enc_data = base64.b64encode(
        cipher_aes.encrypt(pad(payload.encode(), AES.block_size))
    ).decode()

    # RSA 加密 AES key
    pub = RSA.import_key(_RSA_PUBLIC_KEY)
    enc_key = base64.b64encode(PKCS1_v1_5.new(pub).encrypt(aes_key)).decode()

    resp = httpx.post(
        f"{YOUPIN_API}/api/deviceW2",
        json={"encryptedData": enc_data, "encryptedAesKey": enc_key},
        timeout=10,
    )
    resp.raise_for_status()

    # AES-ECB 解密响应
    cipher_aes2 = AES.new(aes_key, AES.MODE_ECB)
    result = json.loads(
        unpad(cipher_aes2.decrypt(base64.b64decode(resp.content)), AES.block_size).decode()
    )
    return result["u"]


# ── HTTP 客户端 ────────────────────────────────────────────────────────────

def _headers() -> dict:
    token = settings.youpin_token
    device_id = settings.youpin_device_id or str(uuid.uuid4())
    try:
        uk = _get_uk()
    except Exception as e:
        logger.warning("获取 uk 失败，使用随机值: %s", e)
        uk = _rand_str(65)

    return {
        "authorization": f"Bearer {token}",
        "content-type": "application/json",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "app-version": "5.26.0",
        "apptype": "1",
        "appversion": "5.26.0",
        "platform": "pc",
        "deviceid": device_id,
        "secret-v": "h5_v1",
        "uk": uk,
        "accept": "application/json, text/plain, */*",
    }


# ── API 封装 ───────────────────────────────────────────────────────────────

async def fetch_lease_records(page: int = 1, page_size: int = 30) -> tuple:
    """
    拉取当前租出中的订单列表。
    返回 (records: list, total_count: int, stats_desc: str)
    注意：API 最大 page_size=30，超出返回空列表。
    """
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{YOUPIN_API}/api/youpin/bff/trade/v1/order/lease/out/list",
            headers=_headers(),
            json={"pageIndex": page, "pageSize": page_size, "gameId": 730},
        )
    resp.raise_for_status()
    body = resp.json()
    code = body.get("Code", body.get("code"))
    if code != 0:
        raise RuntimeError(f"悠悠 lease_records 接口错误: {body.get('Msg', body.get('msg'))}")
    data = body.get("Data", body.get("data")) or {}
    records = data.get("orderDataList", []) if isinstance(data, dict) else []
    total_count = data.get("totalCount", 0) if isinstance(data, dict) else 0
    stats_desc = data.get("statisticsDataDesc", "") if isinstance(data, dict) else ""
    return records, total_count, stats_desc


async def fetch_buy_records(page: int = 1, page_size: int = 30) -> list:
    """拉取购买记录。注意：API 最大 page_size=30，超出返回空列表。"""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{YOUPIN_API}/api/youpin/bff/trade/sale/v1/buy/list",
            headers=_headers(),
            json={"pageIndex": page, "pageSize": page_size, "gameId": 730},
        )
    resp.raise_for_status()
    body = resp.json()
    code = body.get("Code", body.get("code"))
    if code != 0:
        raise RuntimeError(f"悠悠 buy_records 接口错误: {body.get('Msg', body.get('msg'))}")
    data = body.get("Data", body.get("data")) or {}
    if isinstance(data, list):
        return data
    for key in ("list", "List", "orderList", "OrderList", "data"):
        if isinstance(data.get(key), list):
            return data[key]
    return []


async def fetch_sell_records(page: int = 1, page_size: int = 30) -> list:
    """拉取出售记录。注意：API 最大 page_size=30，超出返回空列表。"""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{YOUPIN_API}/api/youpin/bff/trade/sale/v1/sell/list",
            headers=_headers(),
            json={"pageIndex": page, "pageSize": page_size, "gameId": 730},
        )
    resp.raise_for_status()
    body = resp.json()
    code = body.get("Code", body.get("code"))
    if code != 0:
        raise RuntimeError(f"悠悠 sell_records 接口错误: {body.get('Msg', body.get('msg'))}")
    data = body.get("Data", body.get("data")) or {}
    if isinstance(data, list):
        return data
    for key in ("list", "List", "orderList", "OrderList", "data"):
        if isinstance(data.get(key), list):
            return data[key]
    return []


async def fetch_stock_records(page: int = 1, page_size: int = 100) -> tuple:
    """
    拉取在库存（Steam 保护期）物品列表。
    返回 (records: list, total_count: int, valuation: str)

    端点：POST /api/youpin/pc/inventory/list
    """
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{YOUPIN_API}/api/youpin/pc/inventory/list",
            headers=_headers(),
            json={"pageIndex": page, "pageSize": page_size},
        )
    resp.raise_for_status()
    body = resp.json()
    code = body.get("Code", body.get("code"))
    if code != 0:
        raise RuntimeError(f"悠悠库存接口错误: {body.get('Msg', body.get('msg'))}")
    data = body.get("Data", body.get("data")) or {}
    records = data.get("itemsInfos", []) if isinstance(data, dict) else []
    total_count = data.get("totalCount", 0) if isinstance(data, dict) else 0
    valuation = data.get("valuation", "") if isinstance(data, dict) else ""
    return records or [], total_count, valuation


# ── DB 写入逻辑 ────────────────────────────────────────────────────────────

def _parse_hash_name(record: dict) -> Optional[str]:
    """从 productDetail.commodityHashName 提取 market_hash_name"""
    detail = record.get("productDetail") or {}
    return detail.get("commodityHashName") or None


def _parse_abrade(record: dict) -> Optional[float]:
    """
    从 productDetail.abrade / productDetail.commodityAbrade 提取磨损值。
    无磨损物品（印花/武器箱/钥匙等）返回 None。
    """
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
    """totalAmount 单位为分（1/100 元），转换为元"""
    v = record.get("totalAmount")
    if v is not None:
        try:
            return float(v) / 100
        except (TypeError, ValueError):
            pass
    return None


def _parse_date(record: dict) -> Optional[str]:
    """createOrderTime 为 Unix 毫秒时间戳，转换为 YYYY-MM-DD"""
    for key in ("createOrderTime", "finishOrderTime", "payTime"):
        ms = record.get(key)
        if ms:
            try:
                return datetime.utcfromtimestamp(int(ms) / 1000).strftime("%Y-%m-%d")
            except (TypeError, ValueError, OSError):
                pass
    return None


async def import_stock_records(db: AsyncSession) -> dict:
    """
    全量拉取在库存物品（Steam 保护期），写入 inventory_item（status=in_steam）。

    数据来源：POST /api/youpin/pc/inventory/list
    唯一键：class_id="STEAM_PROTECTED", instance_id=steamAssetId

    注意：不使用 assetBuyPrice 作为 purchase_price。
    assetBuyPrice 是悠悠平台对同类型饰品计算的估算价（同一 market_hash_name
    下所有物品共享同一价格，忽略 phase/pattern 差异），不准确。
    purchase_price 由后续 import_buy_records 根据真实买入记录（buy/list）
    按 market_hash_name（饰品类型+磨损）逐条匹配写入。

    isMerge=1 说明该行代表多件同款，assetMergeCount 为实际件数。
    """
    from app.core.config import settings

    all_records: List[dict] = []
    page = 1
    PAGE_SIZE = 100
    valuation = ""

    try:
        batch, total_count, valuation = await fetch_stock_records(page=1, page_size=PAGE_SIZE)
    except Exception as e:
        raise RuntimeError(f"拉取在库存记录失败: {e}")

    all_records.extend(batch)
    logger.info("在库存物品 totalCount=%d，开始分页拉取…", total_count)

    # 继续拉取剩余页（以 batch 为空作为终止条件，因 totalCount 统计的是实际件数而非分页行数）
    for page in range(2, 50):  # 上限 50 页（100 件/页 = 5000 件，远超实际）
        try:
            batch, _, _ = await fetch_stock_records(page=page, page_size=PAGE_SIZE)
        except Exception as e:
            logger.error("拉取在库存记录第 %d 页失败: %s", page, e)
            break
        if not batch:
            break
        all_records.extend(batch)

    logger.info("共拉取在库存物品 %d 条记录", len(all_records))

    steam_id = settings.steam_steam_id or "unknown"
    upserted, skipped = [], []

    for rec in all_records:
        asset_id = str(rec.get("steamAssetId") or "").strip()
        hash_name = (rec.get("marketHashName") or "").strip()
        name_cn = (rec.get("name") or hash_name).strip()
        is_merge = int(rec.get("isMerge") or 0)
        merge_count = int(rec.get("assetMergeCount") or 1) or 1

        # 磨损值（直接从顶层 abrade 字段读取，inventory/list 不走 productDetail）
        abrade: Optional[float] = None
        raw_abrade = rec.get("abrade")
        if raw_abrade:
            try:
                v = float(raw_abrade)
                abrade = v if v > 0 else None
            except (TypeError, ValueError):
                pass

        if not asset_id or not hash_name:
            skipped.append({"asset_id": asset_id, "hash_name": hash_name})
            continue

        # upsert：以 (steam_id, "STEAM_PROTECTED", asset_id) 为唯一指纹
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
            # 不覆盖 purchase_price：由 import_buy_records 根据真实买入记录写入
        else:
            item = InventoryItem(
                steam_id=steam_id,
                asset_id=asset_id,
                class_id="STEAM_PROTECTED",
                instance_id=asset_id,
                market_hash_name=hash_name,
                name=name_cn,
                tradable=False,   # 保护期内不可交易
                marketable=True,
                status="in_steam",
                abrade=abrade,
                # purchase_price 留空，由 import_buy_records 填入
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


async def import_buy_records(db: AsyncSession) -> dict:
    """
    全量拉取购买记录，按 market_hash_name 匹配 inventory_item，
    自动写入 purchase_price / purchase_date / purchase_platform。

    仅更新 purchase_price 为空的记录，已录入的不覆盖。
    """
    all_records: List[dict] = []
    page = 1
    PAGE_SIZE = 30
    MAX_PAGES = 200  # 最多拉 6000 条（API total=null，无法提前终止）
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
        price = _parse_price(rec)
        date_str = _parse_date(rec)
        buy_abrade = _parse_abrade(rec)
        detail = rec.get("productDetail") or {}
        buy_commodity_id = detail.get("commodityId")
        buy_asset_id = str(detail.get("assertId") or "").strip()

        item = None

        # ── 第一优先：commodityId 精确匹配（租出物品，唯一对应 youpin_commodity_id）──
        if buy_commodity_id:
            result = await db.execute(
                select(InventoryItem)
                .where(
                    InventoryItem.youpin_commodity_id == buy_commodity_id,
                    InventoryItem.purchase_price.is_(None),
                    InventoryItem.status.in_(["in_steam", "rented_out", "in_storage"]),
                )
                .limit(1)
            )
            item = result.scalar_one_or_none()

        # ── 第二优先：steamAssetId 精确匹配（在库存物品，买入时的 asset_id 不变）──
        if not item and buy_asset_id:
            result = await db.execute(
                select(InventoryItem)
                .where(
                    InventoryItem.asset_id == buy_asset_id,
                    InventoryItem.class_id == "STEAM_PROTECTED",
                    InventoryItem.purchase_price.is_(None),
                    InventoryItem.status.in_(["in_steam", "rented_out", "in_storage"]),
                )
                .limit(1)
            )
            item = result.scalar_one_or_none()

        # ── 第三优先：market_hash_name + 磨损值精确匹配（1e-8 容差，唯一识别物品）──
        if not item and buy_abrade is not None:
            result = await db.execute(
                select(InventoryItem)
                .where(
                    InventoryItem.market_hash_name == hash_name,
                    InventoryItem.purchase_price.is_(None),
                    InventoryItem.status.in_(["in_steam", "rented_out", "in_storage"]),
                    InventoryItem.abrade.isnot(None),
                    func.abs(InventoryItem.abrade - buy_abrade) < 1e-8,
                )
                .limit(1)
            )
            item = result.scalar_one_or_none()

        # ── 第四优先（降级）：market_hash_name 匹配（印花/武器箱等无磨损物品）──
        if not item:
            result = await db.execute(
                select(InventoryItem)
                .where(
                    InventoryItem.market_hash_name == hash_name,
                    InventoryItem.purchase_price.is_(None),
                    InventoryItem.status.in_(["in_steam", "rented_out", "in_storage"]),
                    InventoryItem.abrade.is_(None),
                )
                .limit(1)
            )
            item = result.scalar_one_or_none()

        if not item:
            not_found.append(hash_name)
            continue

        if price is not None:
            item.purchase_price = price
        if date_str:
            item.purchase_date = date_str
        item.purchase_platform = "YOUPIN"
        updated.append({"asset_id": item.asset_id, "market_hash_name": hash_name, "purchase_price": price})

    await db.commit()

    return {
        "total_records": len(all_records),
        "updated": len(updated),
        "not_found_in_db": len(not_found),
        "items": updated,
        "not_found_names": list(set(not_found))[:20],
    }


async def import_sell_records(db: AsyncSession) -> dict:
    """
    全量拉取出售记录，将匹配到的 inventory_item 标记为 status=sold。
    """
    all_records: List[dict] = []
    page = 1
    PAGE_SIZE = 30
    MAX_PAGES = 200
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

        # 找 rented_out 或 in_steam 中同名的 item
        result = await db.execute(
            select(InventoryItem)
            .where(
                InventoryItem.market_hash_name == hash_name,
                InventoryItem.status.in_(["in_steam", "rented_out"]),
            )
            .limit(1)
        )
        item = result.scalar_one_or_none()

        if not item:
            not_found.append(hash_name)
            continue

        old_status = item.status
        item.status = "sold"
        item.left_steam_at = item.left_steam_at or datetime.utcnow()
        updated.append({
            "asset_id": item.asset_id,
            "market_hash_name": hash_name,
            "old_status": old_status,
        })

    await db.commit()

    return {
        "total_records": len(all_records),
        "updated": len(updated),
        "not_found_in_db": len(not_found),
        "items": updated,
    }


async def import_lease_records(db: AsyncSession) -> dict:
    """
    全量拉取当前租出中订单，按 youpin_commodity_id 做 upsert，写入 inventory_item。

    数据来源：POST /api/youpin/bff/trade/v1/order/lease/out/list
    唯一键：youpin_commodity_id（每件物品对应一个 commodity，即使多次出租也只有一条记录）
    状态标记：rented_out
    身份标识：class_id="YOUPIN"，instance_id=str(commodity_id)（兼容现有唯一约束）
    """
    from app.core.config import settings

    all_records: List[dict] = []
    page = 1
    PAGE_SIZE = 30
    stats_desc = ""

    # 第一页同时获取汇总统计
    try:
        batch, total_count, stats_desc = await fetch_lease_records(page=1, page_size=PAGE_SIZE)
    except Exception as e:
        raise RuntimeError(f"拉取租出记录失败: {e}")

    all_records.extend(batch)
    logger.info("租出记录总计 %d 条，开始分页拉取…", total_count)

    # 继续拉取剩余页（total_count 是准确的）
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

    steam_id = settings.steam_steam_id or "unknown"
    upserted, skipped = [], []

    for rec in all_records:
        info = rec.get("commodityInfo") or {}
        commodity_id = info.get("commodityId")
        hash_name = info.get("commodityHashName")
        order_id = rec.get("orderId") or rec.get("orderNo")
        name_cn = info.get("name", hash_name or "")

        # 磨损值
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

        # 按 youpin_commodity_id 查询已有记录
        result = await db.execute(
            select(InventoryItem).where(InventoryItem.youpin_commodity_id == commodity_id)
        )
        item = result.scalar_one_or_none()

        if item:
            # 更新当前租出订单号、状态和磨损值
            item.youpin_order_id = str(order_id) if order_id else item.youpin_order_id
            item.status = "rented_out"
            item.market_hash_name = hash_name
            item.abrade = abrade
        else:
            # 新建（以 YOUPIN 为合成 class_id，commodity_id 为 instance_id）
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
            )
            db.add(item)

        upserted.append({
            "commodity_id": commodity_id,
            "market_hash_name": hash_name,
            "order_id": order_id,
        })

    await db.commit()

    return {
        "stats": stats_desc,
        "total_fetched": len(all_records),
        "upserted": len(upserted),
        "skipped": len(skipped),
    }
