"""
Background price data collector for quantitative analysis.

Scheduled tasks:
  collect_prices()   — every 30 min, rotates through items via SteamDT batch API
  aggregate_daily()  — 00:05 daily, collapse snapshots → price_history OHLC
  compute_signals()  — 00:10 daily, run quant formulas → quant_signal + alerts
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models.db_models import InventoryItem, PriceHistory, PriceSnapshot

logger = logging.getLogger(__name__)

# ── 运行状态（内存，供前端轮询） ──────────────────────────────────────────
collector_state: dict = {
    "status": "idle",        # idle | running | error
    "last_run": None,
    "last_error": None,
    "items_collected": 0,
    "batches_done": 0,
    "batches_total": 0,
}

backfill_state: dict = {
    "status": "idle",
    "progress": "",
    "done": 0,
    "total": 0,
}


# ══════════════════════════════════════════════════════════════
#  Task 1: Collect Prices (every 30 min)
# ══════════════════════════════════════════════════════════════

async def collect_prices() -> None:
    """
    Fetch batch prices for all unique active market_hash_names via SteamDT.
    Writes into price_snapshot. Called every 30 min by scheduler.
    """
    from app.services import steamdt as steamdt_svc
    from app.core.config import settings

    if not settings.steamdt_api_key:
        logger.debug("collect_prices: no SteamDT API key configured, skipping")
        return

    collector_state["status"] = "running"
    collector_state["last_error"] = None
    collector_state["items_collected"] = 0

    try:
        async with AsyncSessionLocal() as db:
            # Get unique active item names
            result = await db.execute(
                select(InventoryItem.market_hash_name)
                .where(InventoryItem.status.in_(["in_steam", "rented_out"]))
                .distinct()
            )
            hash_names = [row[0] for row in result.all()]

        if not hash_names:
            logger.info("collect_prices: no active items, skipping")
            collector_state["status"] = "idle"
            return

        chunks = [hash_names[i:i + 100] for i in range(0, len(hash_names), 100)]
        collector_state["batches_total"] = len(chunks)
        collector_state["batches_done"] = 0

        for chunk in chunks:
            try:
                async with AsyncSessionLocal() as db:
                    await steamdt_svc.fetch_batch_prices(chunk, db)
                collector_state["items_collected"] += len(chunk)
                collector_state["batches_done"] += 1
            except Exception as e:
                logger.warning("collect_prices batch error: %s", e)
            # Rate limit: 1 batch/min
            if chunk is not chunks[-1]:
                await asyncio.sleep(62)

        collector_state["status"] = "idle"
        collector_state["last_run"] = datetime.now(timezone.utc).isoformat()
        logger.info(
            "collect_prices: done, %d items in %d batches",
            collector_state["items_collected"],
            len(chunks),
        )
    except Exception as e:
        collector_state["status"] = "error"
        collector_state["last_error"] = str(e)
        logger.exception("collect_prices failed: %s", e)


# ══════════════════════════════════════════════════════════════
#  Task 2: Aggregate Daily OHLC (00:05 UTC)
# ══════════════════════════════════════════════════════════════

async def aggregate_daily(target_date: Optional[str] = None) -> int:
    """
    Collapse yesterday's price_snapshot rows into price_history OHLC rows.
    Returns number of rows upserted.
    """
    if target_date is None:
        yesterday = datetime.now(timezone.utc) - timedelta(days=1)
        target_date = yesterday.strftime("%Y%m%d")

    # snapshot_minute is "YYYYMMDDHHmm", so prefix match on date
    prefix = target_date  # e.g. "20260222"

    async with AsyncSessionLocal() as db:
        # Aggregate: for each (market_hash_name, platform), compute OHLC
        # Using raw SQL for efficiency — GROUP BY with MIN/MAX/first/last
        stmt = text("""
            SELECT
                market_hash_name,
                platform,
                -- Open: sell_price of earliest snapshot
                (SELECT ps2.sell_price FROM price_snapshot ps2
                 WHERE ps2.market_hash_name = ps.market_hash_name
                   AND ps2.platform = ps.platform
                   AND ps2.snapshot_minute LIKE :prefix || '%'
                   AND ps2.sell_price IS NOT NULL
                 ORDER BY ps2.snapshot_minute ASC LIMIT 1) AS open_price,
                -- Close: sell_price of latest snapshot
                (SELECT ps3.sell_price FROM price_snapshot ps3
                 WHERE ps3.market_hash_name = ps.market_hash_name
                   AND ps3.platform = ps.platform
                   AND ps3.snapshot_minute LIKE :prefix || '%'
                   AND ps3.sell_price IS NOT NULL
                 ORDER BY ps3.snapshot_minute DESC LIMIT 1) AS close_price,
                MAX(ps.sell_price) AS high_price,
                MIN(ps.sell_price) AS low_price,
                -- sell_count/bidding_count from latest snapshot
                (SELECT ps4.sell_count FROM price_snapshot ps4
                 WHERE ps4.market_hash_name = ps.market_hash_name
                   AND ps4.platform = ps.platform
                   AND ps4.snapshot_minute LIKE :prefix || '%'
                 ORDER BY ps4.snapshot_minute DESC LIMIT 1) AS sell_count,
                (SELECT ps5.bidding_count FROM price_snapshot ps5
                 WHERE ps5.market_hash_name = ps.market_hash_name
                   AND ps5.platform = ps.platform
                   AND ps5.snapshot_minute LIKE :prefix || '%'
                 ORDER BY ps5.snapshot_minute DESC LIMIT 1) AS bidding_count
            FROM price_snapshot ps
            WHERE ps.snapshot_minute LIKE :prefix || '%'
              AND ps.sell_price IS NOT NULL
            GROUP BY ps.market_hash_name, ps.platform
        """)

        rows = (await db.execute(stmt, {"prefix": prefix})).fetchall()
        if not rows:
            logger.info("aggregate_daily: no snapshots for %s", target_date)
            return 0

        count = 0
        for row in rows:
            values = {
                "market_hash_name": row[0],
                "platform": row[1],
                "open_price": row[2],
                "close_price": row[3],
                "high_price": row[4],
                "low_price": row[5],
                "sell_count": row[6],
                "bidding_count": row[7],
                "record_date": target_date,
            }
            ins = sqlite_insert(PriceHistory).values(values)
            ins = ins.on_conflict_do_update(
                index_elements=["market_hash_name", "platform", "record_date"],
                set_={
                    "open_price": ins.excluded.open_price,
                    "close_price": ins.excluded.close_price,
                    "high_price": ins.excluded.high_price,
                    "low_price": ins.excluded.low_price,
                    "sell_count": ins.excluded.sell_count,
                    "bidding_count": ins.excluded.bidding_count,
                },
            )
            await db.execute(ins)
            count += 1

        await db.commit()
        logger.info("aggregate_daily: upserted %d rows for %s", count, target_date)

        # Also generate a synthetic "ALL" row per item (cross-platform minimum sell)
        all_stmt = text("""
            SELECT market_hash_name,
                   MIN(open_price), MIN(close_price),
                   MAX(high_price), MIN(low_price),
                   SUM(sell_count), SUM(bidding_count)
            FROM price_history
            WHERE record_date = :date AND platform != 'ALL'
            GROUP BY market_hash_name
        """)
        all_rows = (await db.execute(all_stmt, {"date": target_date})).fetchall()
        for arow in all_rows:
            values = {
                "market_hash_name": arow[0],
                "platform": "ALL",
                "open_price": arow[1],
                "close_price": arow[2],
                "high_price": arow[3],
                "low_price": arow[4],
                "sell_count": arow[5],
                "bidding_count": arow[6],
                "record_date": target_date,
            }
            ins = sqlite_insert(PriceHistory).values(values)
            ins = ins.on_conflict_do_update(
                index_elements=["market_hash_name", "platform", "record_date"],
                set_={
                    "open_price": ins.excluded.open_price,
                    "close_price": ins.excluded.close_price,
                    "high_price": ins.excluded.high_price,
                    "low_price": ins.excluded.low_price,
                    "sell_count": ins.excluded.sell_count,
                    "bidding_count": ins.excluded.bidding_count,
                },
            )
            await db.execute(ins)

        await db.commit()
        return count


# ══════════════════════════════════════════════════════════════
#  Task 3: Compute Signals (00:10 UTC)
# ══════════════════════════════════════════════════════════════

async def compute_signals() -> None:
    """Delegates to quant_engine after daily aggregation."""
    from app.services.quant_engine import compute_all_signals
    await compute_all_signals()


# ══════════════════════════════════════════════════════════════
#  Backfill: bootstrap price_history from SteamDT avg
# ══════════════════════════════════════════════════════════════

async def backfill_avg_prices() -> None:
    """
    One-time backfill: fetch SteamDT avg prices (7/30/90 day) for all active items.
    Creates synthetic price_history rows using avg as close price.
    """
    from app.services import steamdt as steamdt_svc
    from app.core.config import settings

    if not settings.steamdt_api_key:
        backfill_state["status"] = "error"
        backfill_state["progress"] = "No SteamDT API key"
        return

    backfill_state["status"] = "running"
    backfill_state["done"] = 0

    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(InventoryItem.market_hash_name)
                .where(InventoryItem.status.in_(["in_steam", "rented_out"]))
                .distinct()
            )
            hash_names = [row[0] for row in result.all()]

        backfill_state["total"] = len(hash_names) * 3  # 3 periods each

        today = datetime.now(timezone.utc)
        periods = [
            (7,  (today - timedelta(days=4)).strftime("%Y%m%d")),
            (30, (today - timedelta(days=15)).strftime("%Y%m%d")),
            (90, (today - timedelta(days=45)).strftime("%Y%m%d")),
        ]

        for name in hash_names:
            for days, synthetic_date in periods:
                try:
                    async with AsyncSessionLocal() as db:
                        avg_vo = await steamdt_svc.fetch_avg_price(name, db, days=days)

                        # Write synthetic price_history row
                        if avg_vo.avg_price is not None:
                            values = {
                                "market_hash_name": name,
                                "platform": "ALL",
                                "open_price": avg_vo.avg_price,
                                "close_price": avg_vo.avg_price,
                                "high_price": avg_vo.avg_price,
                                "low_price": avg_vo.avg_price,
                                "record_date": synthetic_date,
                            }
                            ins = sqlite_insert(PriceHistory).values(values)
                            ins = ins.on_conflict_do_update(
                                index_elements=["market_hash_name", "platform", "record_date"],
                                set_={"close_price": ins.excluded.close_price},
                            )
                            await db.execute(ins)
                            await db.commit()

                    backfill_state["done"] += 1
                    backfill_state["progress"] = f"{name} ({days}d)"
                except Exception as e:
                    logger.warning("backfill error %s %dd: %s", name, days, e)
                    backfill_state["done"] += 1

                # Rate limit: 60/min for avg endpoint
                await asyncio.sleep(1.1)

        backfill_state["status"] = "done"
        backfill_state["progress"] = "Completed"
        logger.info("backfill complete: %d items", len(hash_names))
    except Exception as e:
        backfill_state["status"] = "error"
        backfill_state["progress"] = str(e)
        logger.exception("backfill failed: %s", e)


# ══════════════════════════════════════════════════════════════
#  Cleanup: purge old snapshots
# ══════════════════════════════════════════════════════════════

async def cleanup_old_snapshots(keep_days: int = 7) -> int:
    """Remove price_snapshot rows older than keep_days (already aggregated)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=keep_days)).strftime("%Y%m%d")
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            text("DELETE FROM price_snapshot WHERE snapshot_minute < :cutoff"),
            {"cutoff": cutoff + "0000"},
        )
        await db.commit()
        deleted = result.rowcount
        if deleted:
            logger.info("cleanup: purged %d old snapshots (before %s)", deleted, cutoff)
        return deleted
