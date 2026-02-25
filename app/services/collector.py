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
from app.models.db_models import InventoryItem, PortfolioSnapshot, PriceHistory, PriceSnapshot

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
    Backfill: fetch SteamDT avg prices (7/30/90 day) for all active items.
    Generates dense synthetic daily price_history rows by interpolating
    between the three averages to produce ~45 days of data (enough for
    RSI-14, Bollinger-20, and other indicators).
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

        # Fetch 3 avg periods per item
        backfill_state["total"] = len(hash_names) * 3

        today = datetime.now(timezone.utc)
        avg_data: dict[str, dict[int, float]] = {}  # name → {days: avg_price}

        for name in hash_names:
            avg_data[name] = {}
            for days in [7, 30, 90]:
                try:
                    async with AsyncSessionLocal() as db:
                        avg_vo = await steamdt_svc.fetch_avg_price(name, db, days=days)
                        if avg_vo.avg_price is not None and avg_vo.avg_price > 0:
                            avg_data[name][days] = avg_vo.avg_price
                except Exception as e:
                    logger.warning("backfill fetch %s %dd: %s", name, days, e)

                backfill_state["done"] += 1
                backfill_state["progress"] = f"{name} ({days}d)"
                await asyncio.sleep(1.1)  # rate limit 60/min

        # Now generate dense synthetic daily data by interpolation
        backfill_state["progress"] = "Generating daily points..."
        generated = 0

        async with AsyncSessionLocal() as db:
            for name, avgs in avg_data.items():
                if not avgs:
                    continue

                # We have up to 3 price points: 7d, 30d, 90d averages
                # Generate daily data from day -45 to day -1
                # Use closest average for each segment:
                #   day -45 to -15: use 90d avg (or 30d fallback)
                #   day -15 to -4:  use 30d avg (or 7d fallback)
                #   day -4 to -1:   use 7d avg
                avg_90 = avgs.get(90)
                avg_30 = avgs.get(30)
                avg_7 = avgs.get(7)

                # Pick reference prices for interpolation
                far_price = avg_90 or avg_30 or avg_7
                mid_price = avg_30 or avg_7 or avg_90
                near_price = avg_7 or avg_30 or avg_90
                if not far_price:
                    continue

                import random
                for days_ago in range(45, 0, -1):
                    d = (today - timedelta(days=days_ago)).strftime("%Y%m%d")

                    # Select base price by segment
                    if days_ago > 15:
                        base = far_price
                    elif days_ago > 4:
                        # Interpolate between far and near
                        t = (15 - days_ago) / 11.0  # 0..1
                        base = far_price * (1 - t) + mid_price * t
                    else:
                        base = near_price

                    # Add small daily noise (±1.5%) for realistic-looking chart
                    noise = 1.0 + random.uniform(-0.015, 0.015)
                    price = round(base * noise, 2)

                    values = {
                        "market_hash_name": name,
                        "platform": "ALL",
                        "open_price": price,
                        "close_price": price,
                        "high_price": round(price * 1.01, 2),
                        "low_price": round(price * 0.99, 2),
                        "record_date": d,
                    }
                    ins = sqlite_insert(PriceHistory).values(values)
                    ins = ins.on_conflict_do_update(
                        index_elements=["market_hash_name", "platform", "record_date"],
                        set_={
                            "close_price": ins.excluded.close_price,
                            "open_price": ins.excluded.open_price,
                            "high_price": ins.excluded.high_price,
                            "low_price": ins.excluded.low_price,
                        },
                    )
                    await db.execute(ins)
                    generated += 1

                # Commit every item
                await db.commit()

            backfill_state["progress"] = f"Done: {generated} data points"

        # Re-compute signals with new data
        backfill_state["progress"] = "Computing signals..."
        try:
            from app.services.quant_engine import compute_all_signals
            await compute_all_signals()
        except Exception as e:
            logger.warning("backfill signal compute: %s", e)

        backfill_state["status"] = "done"
        backfill_state["progress"] = f"Completed: {generated} daily points for {len(hash_names)} items"
        logger.info("backfill complete: %d items, %d data points", len(hash_names), generated)
    except Exception as e:
        backfill_state["status"] = "error"
        backfill_state["progress"] = str(e)
        logger.exception("backfill failed: %s", e)


# ══════════════════════════════════════════════════════════════
#  Task 4: Portfolio Snapshot (every 30 min, after price collect)
# ══════════════════════════════════════════════════════════════

async def snapshot_portfolio() -> None:
    """
    Record a timestamped snapshot of the entire portfolio's value, cost, and PnL.
    Called every 30 min (5 min after collect_prices to ensure fresh data).
    Enables portfolio value trend charts over time.
    """
    from sqlalchemy import and_, or_

    now = datetime.now(timezone.utc)
    snap_minute = now.strftime("%Y%m%d%H%M")

    try:
        async with AsyncSessionLocal() as db:
            _ACTIVE = ["in_steam", "rented_out", "in_storage"]

            # ── Count by status ──
            status_rows = (
                await db.execute(
                    select(InventoryItem.status, func.count(InventoryItem.id))
                    .group_by(InventoryItem.status)
                )
            ).all()
            status_counts = dict(status_rows)
            total_active = sum(status_counts.get(s, 0) for s in _ACTIVE)

            # ── Total cost (COALESCE manual, auto) ──
            total_cost = (
                await db.execute(
                    select(
                        func.sum(
                            func.coalesce(
                                InventoryItem.purchase_price_manual,
                                InventoryItem.purchase_price,
                            )
                        )
                    ).where(InventoryItem.status.in_(_ACTIVE))
                )
            ).scalar() or 0

            # ── Cost-priced count ──
            cost_priced = (
                await db.execute(
                    select(func.count(InventoryItem.id)).where(
                        InventoryItem.status.in_(_ACTIVE),
                        or_(
                            InventoryItem.purchase_price.isnot(None),
                            InventoryItem.purchase_price_manual.isnot(None),
                        ),
                    )
                )
            ).scalar() or 0

            # ── Market value (latest price_snapshot per item × count) ──
            name_count_rows = (
                await db.execute(
                    select(
                        InventoryItem.market_hash_name,
                        func.count(InventoryItem.id).label("cnt"),
                    )
                    .where(InventoryItem.status.in_(_ACTIVE))
                    .group_by(InventoryItem.market_hash_name)
                )
            ).all()

            all_names = [r[0] for r in name_count_rows]
            name_to_count = {r[0]: r[1] for r in name_count_rows}

            # Get latest prices
            if all_names:
                latest_subq = (
                    select(
                        PriceSnapshot.market_hash_name,
                        func.max(PriceSnapshot.snapshot_minute).label("latest_minute"),
                    )
                    .where(PriceSnapshot.market_hash_name.in_(all_names))
                    .group_by(PriceSnapshot.market_hash_name)
                    .subquery()
                )
                price_rows = (
                    await db.execute(
                        select(
                            PriceSnapshot.market_hash_name,
                            func.min(PriceSnapshot.sell_price).label("cp"),
                        )
                        .join(
                            latest_subq,
                            and_(
                                PriceSnapshot.market_hash_name == latest_subq.c.market_hash_name,
                                PriceSnapshot.snapshot_minute == latest_subq.c.latest_minute,
                            ),
                        )
                        .where(PriceSnapshot.sell_price.isnot(None), PriceSnapshot.sell_price > 0)
                        .group_by(PriceSnapshot.market_hash_name)
                    )
                ).all()
                price_map = {r[0]: r[1] for r in price_rows}
            else:
                price_map = {}

            market_value = 0.0
            market_priced = 0
            for name, cnt in name_to_count.items():
                mp = price_map.get(name)
                if mp is not None:
                    market_value += mp * cnt
                    market_priced += cnt

            # ── PnL: items with both cost and market price ──
            item_cost_rows = (
                await db.execute(
                    select(
                        InventoryItem.market_hash_name,
                        func.coalesce(
                            InventoryItem.purchase_price_manual,
                            InventoryItem.purchase_price,
                        ).label("cost"),
                    )
                    .where(
                        InventoryItem.status.in_(_ACTIVE),
                        or_(
                            InventoryItem.purchase_price.isnot(None),
                            InventoryItem.purchase_price_manual.isnot(None),
                        ),
                    )
                )
            ).all()

            pnl_market_sum = 0.0
            pnl_cost_sum = 0.0
            for row in item_cost_rows:
                mp = price_map.get(row[0])
                if mp is not None and row[1] is not None:
                    pnl_market_sum += mp
                    pnl_cost_sum += float(row[1])

            if pnl_cost_sum > 0:
                pnl = round(pnl_market_sum - pnl_cost_sum, 2)
                pnl_pct = round((pnl_market_sum - pnl_cost_sum) / pnl_cost_sum * 100, 2)
            else:
                pnl = None
                pnl_pct = None

            # ── Write snapshot ──
            from sqlalchemy.dialects.sqlite import insert as sqlite_insert
            values = {
                "snapshot_minute": snap_minute,
                "total_active": total_active,
                "in_steam_count": status_counts.get("in_steam", 0),
                "rented_out_count": status_counts.get("rented_out", 0),
                "in_storage_count": status_counts.get("in_storage", 0),
                "total_cost": round(total_cost, 2) if total_cost else 0,
                "market_value": round(market_value, 2) if market_value else 0,
                "pnl": pnl,
                "pnl_pct": pnl_pct,
                "market_priced_count": market_priced,
                "cost_priced_count": cost_priced,
            }
            ins = sqlite_insert(PortfolioSnapshot).values(values)
            ins = ins.on_conflict_do_update(
                index_elements=["snapshot_minute"],
                set_={k: ins.excluded[k] for k in values if k != "snapshot_minute"},
            )
            await db.execute(ins)
            await db.commit()

            logger.info(
                "snapshot_portfolio: active=%d, value=%.2f, cost=%.2f, pnl=%s",
                total_active, market_value, total_cost, pnl,
            )
    except Exception as e:
        logger.exception("snapshot_portfolio failed: %s", e)


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
