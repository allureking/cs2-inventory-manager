"""
悠悠有品 PC-Web API 集成服务

功能：
  fetch_buy_records()   → 拉取购买记录
  fetch_sell_records()  → 拉取出售记录
  import_buy_records()  → 匹配 inventory_item，写入 purchase_price / purchase_date
  import_sell_records() → 匹配 inventory_item，标记 status=sold

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
from sqlalchemy import select
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


# ── DB 写入逻辑 ────────────────────────────────────────────────────────────

def _parse_hash_name(record: dict) -> Optional[str]:
    """从 productDetail.commodityHashName 提取 market_hash_name"""
    detail = record.get("productDetail") or {}
    return detail.get("commodityHashName") or None


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

        # 找未录入购入价的同名 inventory_item
        result = await db.execute(
            select(InventoryItem)
            .where(
                InventoryItem.market_hash_name == hash_name,
                InventoryItem.purchase_price.is_(None),
                InventoryItem.status.in_(["in_steam", "rented_out", "in_storage"]),
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
