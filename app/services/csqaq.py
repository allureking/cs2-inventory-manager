"""
CSQAQ 数据 API 集成服务。

提供饰品市场租金价格、物品分类、Steam 成交量、全球存世量等数据。
API 文档：https://docs.csqaq.com/

核心端点：
  GET  /info/good?id=X          — 单品详情（租金/分类/成交量/存世量）
  POST /info/get_rank_list      — 排行榜（用于 ID 映射）

速率限制：1 req/sec
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

import httpx
from sqlalchemy import func, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.db_models import InventoryItem, Item, QuantSignal

logger = logging.getLogger(__name__)

# Module-level state for frontend polling
csqaq_sync_state: dict = {
    "status": "idle",
    "last_run": None,
    "mapped": 0,
    "synced": 0,
    "errors": 0,
}

_BASE_URL = "https://api.csqaq.com/api/v1"
_RATE_LIMIT_DELAY = 1.5  # seconds between requests (avoid 429)


def _headers() -> dict[str, str]:
    return {
        "ApiToken": settings.csqaq_api_key,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


# ══════════════════════════════════════════════════════════════
#  Low-level API calls
# ══════════════════════════════════════════════════════════════

async def _fetch_good(client: httpx.AsyncClient, good_id: int) -> Optional[dict]:
    """Fetch single item details via GET /info/good?id=X."""
    try:
        resp = await client.get(f"{_BASE_URL}/info/good", params={"id": good_id})
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") == 200 and data.get("data"):
            return data["data"].get("goods_info")
    except Exception as e:
        logger.warning("csqaq fetch good %d: %s", good_id, e)
    return None


async def _search_ranking(
    client: httpx.AsyncClient, search: str, page_size: int = 10
) -> list[dict]:
    """Search ranking by Chinese name."""
    try:
        resp = await client.post(
            f"{_BASE_URL}/info/get_rank_list",
            json={"page_index": 1, "page_size": page_size, "filter": {}, "search": search},
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") == 200:
            return data.get("data", {}).get("data", [])
    except Exception as e:
        logger.warning("csqaq search '%s': %s", search[:30], e)
    return []


# ══════════════════════════════════════════════════════════════
#  ID Mapping: Chinese name → CSQAQ good_id
# ══════════════════════════════════════════════════════════════

async def build_id_mapping() -> int:
    """
    Build CSQAQ good_id mapping for all inventory items.
    Searches ranking API by Chinese name, verifies via /info/good.
    Returns number of items mapped.
    """
    if not settings.csqaq_api_key:
        logger.info("csqaq: no API key, skipping mapping")
        return 0

    csqaq_sync_state["status"] = "mapping"
    mapped = 0
    errors = 0

    async with AsyncSessionLocal() as db:
        # Get all unique items with Chinese name
        result = await db.execute(
            select(
                InventoryItem.market_hash_name,
                InventoryItem.name,
            )
            .where(InventoryItem.status.in_(["in_steam", "rented_out"]))
            .group_by(InventoryItem.market_hash_name)
        )
        items = result.all()
        logger.info("csqaq mapping: %d items to map", len(items))

        async with httpx.AsyncClient(timeout=15, headers=_headers()) as client:
            for market_hash_name, cn_name in items:
                try:
                    # Skip non-tradeable items (medals, coins, etc.)
                    if any(kw in cn_name for kw in ["勋章", "纪念奖牌", "硬币", "通行证", "Storage Unit"]):
                        continue

                    # Extract a shorter search term (weapon + skin name without wear)
                    # e.g., "AK-47 | 传承 (崭新出厂)" → search "传承"
                    search_term = cn_name
                    if " | " in cn_name:
                        # Use the skin name part for more precise search
                        parts = cn_name.split(" | ", 1)
                        skin_part = parts[1]
                        # Remove wear condition for broader match
                        if " (" in skin_part:
                            skin_part = skin_part.split(" (")[0]
                        search_term = skin_part

                    results = await _search_ranking(client, search_term)
                    await asyncio.sleep(_RATE_LIMIT_DELAY)

                    # Find exact match by full Chinese name
                    match = None
                    for item in results:
                        if item.get("name") == cn_name:
                            match = item
                            break

                    if not match:
                        # Try broader search with full name
                        if search_term != cn_name:
                            results = await _search_ranking(client, cn_name)
                            await asyncio.sleep(_RATE_LIMIT_DELAY)
                            for item in results:
                                if item.get("name") == cn_name:
                                    match = item
                                    break

                    if match:
                        good_id = match["id"]
                        # Upsert into item table
                        stmt = sqlite_insert(Item).values(
                            market_hash_name=market_hash_name,
                            name=cn_name,
                            csqaq_good_id=good_id,
                        )
                        stmt = stmt.on_conflict_do_update(
                            index_elements=["market_hash_name"],
                            set_={"csqaq_good_id": good_id, "name": cn_name},
                        )
                        await db.execute(stmt)
                        await db.commit()  # Commit each mapping to avoid long locks
                        mapped += 1
                        csqaq_sync_state["mapped"] = mapped
                        if mapped % 20 == 0:
                            logger.info("csqaq mapping progress: %d/%d", mapped, len(items))
                    else:
                        logger.debug("csqaq: no match for '%s'", cn_name[:40])

                except Exception as e:
                    logger.warning("csqaq mapping error for %s: %s", cn_name[:30], e)
                    errors += 1
                    await asyncio.sleep(_RATE_LIMIT_DELAY)

        await db.commit()

    csqaq_sync_state.update(status="idle", mapped=mapped, errors=errors)
    logger.info("csqaq mapping complete: %d mapped, %d errors", mapped, errors)
    return mapped


# ══════════════════════════════════════════════════════════════
#  Daily sync: fetch rental + metadata for all mapped items
# ══════════════════════════════════════════════════════════════

async def sync_all_items() -> int:
    """
    Fetch full item data from CSQAQ for all mapped items.
    Updates quant_signal (rental, turnover, supply) and
    fills missing inventory_item metadata (item_type, icon_url).
    """
    if not settings.csqaq_api_key:
        return 0

    csqaq_sync_state["status"] = "syncing"
    synced = 0
    errors = 0
    signal_date = datetime.now(timezone.utc).strftime("%Y%m%d")

    async with AsyncSessionLocal() as db:
        # Get all items with csqaq_good_id
        result = await db.execute(
            select(Item.market_hash_name, Item.csqaq_good_id)
            .where(Item.csqaq_good_id.isnot(None))
        )
        items = result.all()

        if not items:
            logger.info("csqaq sync: no mapped items, running mapping first")
            csqaq_sync_state["status"] = "idle"
            return 0

        logger.info("csqaq sync: fetching data for %d items", len(items))

        # Collect items needing metadata fill
        missing_type_q = await db.execute(
            select(InventoryItem.market_hash_name)
            .where(
                InventoryItem.status.in_(["in_steam", "rented_out"]),
                InventoryItem.item_type.is_(None),
            )
            .distinct()
        )
        needs_type = {r[0] for r in missing_type_q.all()}

        missing_icon_q = await db.execute(
            select(InventoryItem.market_hash_name)
            .where(
                InventoryItem.status.in_(["in_steam", "rented_out"]),
                InventoryItem.icon_url.is_(None),
            )
            .distinct()
        )
        needs_icon = {r[0] for r in missing_icon_q.all()}

        async with httpx.AsyncClient(timeout=15, headers=_headers()) as client:
            for market_hash_name, good_id in items:
                try:
                    info = await _fetch_good(client, good_id)
                    await asyncio.sleep(_RATE_LIMIT_DELAY)

                    if not info:
                        errors += 1
                        continue

                    # ── Update quant_signal with rental/market data ──
                    lease_price = info.get("yyyp_lease_price") or 0
                    lease_annual = info.get("yyyp_lease_annual") or 0
                    turnover = info.get("turnover_number")
                    supply = info.get("statistic")

                    # Upsert into quant_signal (merge with existing signal data)
                    update_fields = {}
                    if lease_price > 0:
                        update_fields["daily_rent"] = float(lease_price)
                    if lease_annual > 0:
                        update_fields["rental_annual"] = float(lease_annual)
                    if turnover is not None:
                        update_fields["steam_turnover"] = int(turnover)
                    if supply is not None:
                        update_fields["global_supply"] = int(supply)

                    if update_fields:
                        # Try to update existing signal for today
                        upd = await db.execute(
                            update(QuantSignal)
                            .where(
                                QuantSignal.market_hash_name == market_hash_name,
                                QuantSignal.signal_date == signal_date,
                            )
                            .values(**update_fields)
                        )
                        if upd.rowcount == 0:
                            # No signal row for today yet; insert minimal row
                            vals = {
                                "market_hash_name": market_hash_name,
                                "signal_date": signal_date,
                                **update_fields,
                            }
                            stmt = sqlite_insert(QuantSignal).values(vals)
                            stmt = stmt.on_conflict_do_update(
                                index_elements=["market_hash_name", "signal_date"],
                                set_=update_fields,
                            )
                            await db.execute(stmt)

                    # ── Fill missing inventory_item metadata ──
                    if market_hash_name in needs_type:
                        type_name = info.get("type_localized_name")
                        rarity = info.get("rarity_localized_name")
                        if type_name:
                            combined = f"{rarity} {type_name}" if rarity else type_name
                            await db.execute(
                                update(InventoryItem)
                                .where(InventoryItem.market_hash_name == market_hash_name)
                                .values(item_type=combined)
                            )

                    if market_hash_name in needs_icon:
                        img = info.get("img")
                        if img:
                            await db.execute(
                                update(InventoryItem)
                                .where(
                                    InventoryItem.market_hash_name == market_hash_name,
                                    InventoryItem.icon_url.is_(None),
                                )
                                .values(icon_url=img)
                            )

                    synced += 1
                    csqaq_sync_state["synced"] = synced
                    if synced % 30 == 0:
                        logger.info("csqaq sync progress: %d/%d", synced, len(items))
                    await db.commit()  # Commit per-item to avoid long locks

                except Exception as e:
                    logger.warning("csqaq sync error for %s: %s", market_hash_name[:30], e)
                    errors += 1
                    csqaq_sync_state["errors"] = errors
                    await asyncio.sleep(_RATE_LIMIT_DELAY)

        await db.commit()

    csqaq_sync_state.update(
        status="idle",
        last_run=datetime.now(timezone.utc).isoformat(),
        synced=synced,
        errors=errors,
    )
    logger.info("csqaq sync complete: %d synced, %d errors", synced, errors)
    return synced


# ══════════════════════════════════════════════════════════════
#  Orchestrator: called by scheduler
# ══════════════════════════════════════════════════════════════

async def csqaq_daily_sync() -> None:
    """Daily sync job: ensure mapping exists, then sync data."""
    if not settings.csqaq_api_key:
        return

    async with AsyncSessionLocal() as db:
        # Check if mapping exists
        count = await db.execute(
            select(func.count()).select_from(Item).where(Item.csqaq_good_id.isnot(None))
        )
        mapped_count = count.scalar() or 0

    if mapped_count == 0:
        logger.info("csqaq: no ID mapping found, building first...")
        await build_id_mapping()

    await sync_all_items()
