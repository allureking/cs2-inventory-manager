"""
监控与组合历史 API

GET  /api/monitoring/status           — 系统健康状态（调度器、数据库、采集器）
GET  /api/monitoring/portfolio-history — 组合价值时序数据（用于趋势图）
GET  /api/monitoring/data-freshness   — 数据新鲜度检查
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.db_models import (
    InventoryItem,
    PortfolioSnapshot,
    PriceHistory,
    PriceSnapshot,
    QuantSignal,
)
from app.services.collector import collector_state

router = APIRouter()

_START_TIME = datetime.now(timezone.utc)


# ── System Status ────────────────────────────────────────────────────────

@router.get("/status")
async def system_status(db: AsyncSession = Depends(get_db)):
    """全面系统健康检查：调度器状态、数据库统计、采集器状态、数据新鲜度"""

    now = datetime.now(timezone.utc)
    uptime_seconds = int((now - _START_TIME).total_seconds())

    # DB table row counts
    counts = {}
    for tbl in ["inventory_item", "price_snapshot", "price_history", "quant_signal", "portfolio_snapshot"]:
        r = await db.execute(text(f"SELECT COUNT(*) FROM {tbl}"))
        counts[tbl] = r.scalar() or 0

    # Latest price snapshot time
    latest_snap = (
        await db.execute(select(func.max(PriceSnapshot.snapshot_minute)))
    ).scalar()

    # Latest signal date
    latest_signal = (
        await db.execute(select(func.max(QuantSignal.signal_date)))
    ).scalar()

    # Latest portfolio snapshot
    latest_portfolio = (
        await db.execute(select(func.max(PortfolioSnapshot.snapshot_minute)))
    ).scalar()

    # DB file size
    db_path = os.environ.get("DATABASE_PATH", "/var/www/cs2-inventory-manager/cs2_inventory.db")
    db_size_mb = round(os.path.getsize(db_path) / 1024 / 1024, 2) if os.path.exists(db_path) else None

    # Data freshness check
    data_fresh = True
    if latest_snap:
        try:
            snap_dt = datetime.strptime(latest_snap, "%Y%m%d%H%M").replace(tzinfo=timezone.utc)
            minutes_ago = (now - snap_dt).total_seconds() / 60
            data_fresh = minutes_ago < 60  # stale if > 1 hour
        except ValueError:
            data_fresh = False

    return {
        "status": "healthy" if data_fresh else "degraded",
        "uptime_seconds": uptime_seconds,
        "uptime_human": _format_uptime(uptime_seconds),
        "timestamp": now.isoformat(),
        "collector": collector_state,
        "database": {
            "size_mb": db_size_mb,
            "row_counts": counts,
        },
        "data_freshness": {
            "latest_price_snapshot": latest_snap,
            "latest_signal_date": latest_signal,
            "latest_portfolio_snapshot": latest_portfolio,
            "is_fresh": data_fresh,
        },
        "scheduler_jobs": [
            {"id": "price_collect", "interval": "30 min"},
            {"id": "portfolio_snapshot", "interval": "30 min (offset +5)"},
            {"id": "daily_aggregate", "cron": "00:05 UTC"},
            {"id": "daily_signals", "cron": "00:10 UTC"},
            {"id": "cleanup_snapshots", "cron": "01:00 UTC"},
        ],
    }


def _format_uptime(seconds: int) -> str:
    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    mins = (seconds % 3600) // 60
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    parts.append(f"{mins}m")
    return " ".join(parts)


# ── Portfolio History (Time-series for charts) ───────────────────────────

@router.get("/portfolio-history")
async def portfolio_history(
    range: str = Query("7d", regex="^(24h|7d|30d|90d|all)$"),
    db: AsyncSession = Depends(get_db),
):
    """
    返回指定时间范围内的组合价值时序数据，用于 Chart.js 趋势图。

    range: 24h | 7d | 30d | 90d | all
    """
    now = datetime.now(timezone.utc)

    if range == "all":
        cutoff = "000000000000"
    else:
        delta_map = {"24h": 1, "7d": 7, "30d": 30, "90d": 90}
        days = delta_map.get(range, 7)
        cutoff = (now - timedelta(days=days)).strftime("%Y%m%d%H%M")

    rows = (
        await db.execute(
            select(PortfolioSnapshot)
            .where(PortfolioSnapshot.snapshot_minute >= cutoff)
            .order_by(PortfolioSnapshot.snapshot_minute.asc())
        )
    ).scalars().all()

    # Downsample for long ranges to keep response size manageable
    max_points = 200
    if len(rows) > max_points:
        step = len(rows) // max_points
        rows = rows[::step] + ([rows[-1]] if rows[-1] not in rows[::step] else [])

    data = []
    for r in rows:
        try:
            ts = datetime.strptime(r.snapshot_minute, "%Y%m%d%H%M").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        data.append({
            "timestamp": ts.isoformat(),
            "snapshot_minute": r.snapshot_minute,
            "total_active": r.total_active,
            "in_steam_count": r.in_steam_count,
            "rented_out_count": r.rented_out_count,
            "in_storage_count": r.in_storage_count,
            "total_cost": r.total_cost,
            "market_value": r.market_value,
            "pnl": r.pnl,
            "pnl_pct": r.pnl_pct,
            "market_priced_count": r.market_priced_count,
            "cost_priced_count": r.cost_priced_count,
        })

    return {
        "range": range,
        "count": len(data),
        "data": data,
    }


# ── Data Freshness ───────────────────────────────────────────────────────

@router.get("/data-freshness")
async def data_freshness(db: AsyncSession = Depends(get_db)):
    """详细数据新鲜度报告：各数据源最后更新时间"""

    now = datetime.now(timezone.utc)

    # Latest price snapshot
    latest_snap = (
        await db.execute(select(func.max(PriceSnapshot.snapshot_minute)))
    ).scalar()

    # Latest price history date
    latest_history = (
        await db.execute(select(func.max(PriceHistory.record_date)))
    ).scalar()

    # Latest signal
    latest_signal = (
        await db.execute(select(func.max(QuantSignal.signal_date)))
    ).scalar()

    # Latest portfolio snapshot
    latest_portfolio = (
        await db.execute(select(func.max(PortfolioSnapshot.snapshot_minute)))
    ).scalar()

    # Active items last sync
    latest_sync = (
        await db.execute(select(func.max(InventoryItem.last_synced_at)))
    ).scalar()

    def _minutes_ago(minute_str: Optional[str], fmt: str = "%Y%m%d%H%M") -> Optional[int]:
        if not minute_str:
            return None
        try:
            dt = datetime.strptime(minute_str, fmt).replace(tzinfo=timezone.utc)
            return int((now - dt).total_seconds() / 60)
        except ValueError:
            return None

    return {
        "timestamp": now.isoformat(),
        "sources": {
            "price_snapshot": {
                "latest": latest_snap,
                "minutes_ago": _minutes_ago(latest_snap),
            },
            "price_history": {
                "latest": latest_history,
                "minutes_ago": _minutes_ago(latest_history, "%Y%m%d") if latest_history else None,
            },
            "quant_signal": {
                "latest": latest_signal,
                "minutes_ago": _minutes_ago(latest_signal, "%Y%m%d") if latest_signal else None,
            },
            "portfolio_snapshot": {
                "latest": latest_portfolio,
                "minutes_ago": _minutes_ago(latest_portfolio),
            },
            "inventory_sync": {
                "latest": latest_sync.isoformat() if latest_sync else None,
            },
        },
    }
