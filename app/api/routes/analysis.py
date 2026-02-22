"""
量化分析 API

GET  /api/analysis/overview           — 总览（评分分布、Top10、分类趋势）
GET  /api/analysis/signals            — 单品信号详情
GET  /api/analysis/alerts             — 预警列表
PATCH /api/analysis/alerts/{id}/read  — 标记已读
POST /api/analysis/alerts/read-all    — 全部已读
GET  /api/analysis/rankings           — 信号排名
GET  /api/analysis/price-history      — 图表数据（OHLC + MA + BB）
GET  /api/analysis/spreads            — 套利雷达
GET  /api/analysis/categories         — 分类趋势
POST /api/analysis/backfill           — 触发历史回填
POST /api/analysis/compute-now        — 手动触发信号计算
GET  /api/analysis/collector/status   — 采集器状态
"""

from __future__ import annotations

import asyncio
import math
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal, get_db
from app.models.db_models import (
    InventoryItem,
    PriceHistory,
    PriceSnapshot,
    QuantAlert,
    QuantSignal,
)
from app.services.collector import backfill_state, collector_state

router = APIRouter()


# ── Overview ──────────────────────────────────────────────────────────────

@router.get("/overview")
async def analysis_overview(db: AsyncSession = Depends(get_db)):
    """量化分析总览：评分分布、Top10 卖出信号、分类趋势、未读预警数"""

    # Latest signal_date
    latest_date_r = await db.execute(
        select(func.max(QuantSignal.signal_date))
    )
    latest_date = latest_date_r.scalar()

    # Unread alerts count
    unread_r = await db.execute(
        select(func.count()).select_from(QuantAlert).where(QuantAlert.is_read == False)
    )
    unread_count = unread_r.scalar() or 0

    if not latest_date:
        return {
            "signal_date": None,
            "unread_alerts": unread_count,
            "avg_sell_score": None,
            "avg_momentum_30": None,
            "score_distribution": [0, 0, 0, 0, 0],
            "top_sell": [],
            "category_trends": [],
            "collector": collector_state,
        }

    # Only consider signals for items we own
    owned_names_q = (
        select(InventoryItem.market_hash_name)
        .where(InventoryItem.status.in_(["in_steam", "rented_out"]))
        .distinct()
    )

    # Average sell score + momentum
    avg_r = await db.execute(
        select(
            func.avg(QuantSignal.sell_score),
            func.avg(QuantSignal.momentum_30),
        ).where(
            QuantSignal.signal_date == latest_date,
            QuantSignal.market_hash_name.in_(owned_names_q),
        )
    )
    avg_row = avg_r.one()
    avg_sell = round(avg_row[0], 1) if avg_row[0] else None
    avg_mom = round(avg_row[1], 1) if avg_row[1] else None

    # Score distribution: [0-30, 30-50, 50-70, 70-85, 85-100]
    dist_r = await db.execute(text("""
        SELECT
            SUM(CASE WHEN sell_score < 30 THEN 1 ELSE 0 END),
            SUM(CASE WHEN sell_score >= 30 AND sell_score < 50 THEN 1 ELSE 0 END),
            SUM(CASE WHEN sell_score >= 50 AND sell_score < 70 THEN 1 ELSE 0 END),
            SUM(CASE WHEN sell_score >= 70 AND sell_score < 85 THEN 1 ELSE 0 END),
            SUM(CASE WHEN sell_score >= 85 THEN 1 ELSE 0 END)
        FROM quant_signal
        WHERE signal_date = :d
          AND market_hash_name IN (
              SELECT DISTINCT market_hash_name FROM inventory_item
              WHERE status IN ('in_steam', 'rented_out')
          )
    """), {"d": latest_date})
    dist_row = dist_r.one()
    distribution = [int(v or 0) for v in dist_row]

    # Top 10 sell signals
    top_r = await db.execute(
        select(QuantSignal)
        .where(
            QuantSignal.signal_date == latest_date,
            QuantSignal.market_hash_name.in_(owned_names_q),
            QuantSignal.sell_score.isnot(None),
        )
        .order_by(QuantSignal.sell_score.desc())
        .limit(10)
    )
    top_sell = [
        {
            "market_hash_name": s.market_hash_name,
            "sell_score": round(s.sell_score, 1) if s.sell_score else None,
            "rsi_14": round(s.rsi_14, 1) if s.rsi_14 else None,
            "momentum_30": round(s.momentum_30, 1) if s.momentum_30 else None,
            "ath_pct": round(s.ath_pct, 1) if s.ath_pct else None,
        }
        for s in top_r.scalars().all()
    ]

    # Category trends — using market_hash_name patterns
    cat_trends = await _get_category_trends(db, latest_date)

    return {
        "signal_date": latest_date,
        "unread_alerts": unread_count,
        "avg_sell_score": avg_sell,
        "avg_momentum_30": avg_mom,
        "score_distribution": distribution,
        "top_sell": top_sell,
        "category_trends": cat_trends,
        "collector": collector_state,
    }


async def _get_category_trends(db: AsyncSession, signal_date: str) -> list[dict]:
    """Compute per-category average momentum/RSI/count."""
    categories = {
        "knife":   "★%",
        "pistol":  None,  # special
        "rifle":   None,
        "sniper":  None,
        "smg":     None,
        "sticker": "Sticker |%",
        "case":    "% Case%",
    }

    # Simpler approach: fetch all signals, classify in Python
    result = await db.execute(
        select(
            QuantSignal.market_hash_name,
            QuantSignal.momentum_7,
            QuantSignal.momentum_30,
            QuantSignal.rsi_14,
            QuantSignal.sell_score,
        ).where(
            QuantSignal.signal_date == signal_date,
            QuantSignal.market_hash_name.in_(
                select(InventoryItem.market_hash_name)
                .where(InventoryItem.status.in_(["in_steam", "rented_out"]))
                .distinct()
            ),
        )
    )
    rows = result.all()

    # Classify
    from app.api.routes.dashboard import _CATEGORY_PATTERNS
    cat_data: dict[str, list] = {}

    for name, m7, m30, rsi, sell in rows:
        cat = _classify_item(name)
        if cat not in cat_data:
            cat_data[cat] = []
        cat_data[cat].append({"m7": m7, "m30": m30, "rsi": rsi, "sell": sell})

    trends = []
    for cat, items in sorted(cat_data.items()):
        valid_m7 = [x["m7"] for x in items if x["m7"] is not None]
        valid_m30 = [x["m30"] for x in items if x["m30"] is not None]
        valid_rsi = [x["rsi"] for x in items if x["rsi"] is not None]
        valid_sell = [x["sell"] for x in items if x["sell"] is not None]
        trends.append({
            "category": cat,
            "count": len(items),
            "avg_momentum_7": round(sum(valid_m7) / len(valid_m7), 1) if valid_m7 else None,
            "avg_momentum_30": round(sum(valid_m30) / len(valid_m30), 1) if valid_m30 else None,
            "avg_rsi": round(sum(valid_rsi) / len(valid_rsi), 1) if valid_rsi else None,
            "avg_sell_score": round(sum(valid_sell) / len(valid_sell), 1) if valid_sell else None,
        })

    return sorted(trends, key=lambda t: abs(t.get("avg_momentum_7") or 0), reverse=True)


def _classify_item(name: str) -> str:
    """Classify a market_hash_name into a category."""
    if name.startswith("★"):
        if any(kw in name for kw in ("Gloves", "Wraps")):
            return "glove"
        return "knife"
    if name.startswith("Sticker |") or name.startswith("Patch |"):
        return "sticker"
    if " Case" in name or "Capsule" in name or "Package" in name:
        return "case"

    prefixes = {
        "pistol": ["Glock-18", "USP-S", "P250", "CZ75-Auto", "Five-SeveN", "Tec-9",
                    "Desert Eagle", "R8 Revolver", "P2000", "Dual Berettas"],
        "rifle":  ["AK-47", "M4A4", "M4A1-S", "FAMAS", "Galil AR", "AUG", "SG 553"],
        "sniper": ["AWP", "SSG 08", "SCAR-20", "G3SG1"],
        "smg":    ["MP9", "MP5-SD", "MAC-10", "PP-Bizon", "UMP-45", "P90", "MP7"],
        "shotgun": ["XM1014", "MAG-7", "Nova", "Sawed-Off"],
        "mg":     ["M249", "Negev"],
    }
    for cat, plist in prefixes.items():
        for p in plist:
            if name.startswith(p):
                return cat
    return "other"


# ── Single item signals ──────────────────────────────────────────────────

@router.get("/signals")
async def get_item_signals(
    market_hash_name: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """获取单品量化信号详情 + 90 天价格历史"""
    # Latest signal
    sig_r = await db.execute(
        select(QuantSignal)
        .where(QuantSignal.market_hash_name == market_hash_name)
        .order_by(QuantSignal.signal_date.desc())
        .limit(1)
    )
    sig = sig_r.scalar_one_or_none()

    # Price history (90 days, platform=ALL)
    ph_r = await db.execute(
        select(PriceHistory)
        .where(
            PriceHistory.market_hash_name == market_hash_name,
            PriceHistory.platform == "ALL",
        )
        .order_by(PriceHistory.record_date.desc())
        .limit(90)
    )
    history = ph_r.scalars().all()
    history.reverse()

    closes = [h.close_price for h in history if h.close_price]

    # Compute MA and BB for chart overlay
    from app.services.quant_engine import _sma, calc_bollinger
    chart_data = []
    for i, h in enumerate(history):
        sub_closes = closes[:i + 1] if i < len(closes) else closes
        ma7 = _sma(sub_closes, 7)
        ma30 = _sma(sub_closes, 30)
        bb = calc_bollinger(sub_closes) if len(sub_closes) >= 20 else None
        chart_data.append({
            "date": h.record_date,
            "open": h.open_price,
            "close": h.close_price,
            "high": h.high_price,
            "low": h.low_price,
            "sell_count": h.sell_count,
            "ma7": round(ma7, 2) if ma7 else None,
            "ma30": round(ma30, 2) if ma30 else None,
            "bb_upper": round(bb["upper"], 2) if bb else None,
            "bb_lower": round(bb["lower"], 2) if bb else None,
        })

    # Cross-platform latest prices
    platform_r = await db.execute(text("""
        SELECT ps.platform, ps.sell_price, ps.sell_count, ps.bidding_price
        FROM price_snapshot ps
        INNER JOIN (
            SELECT platform, MAX(snapshot_minute) AS latest
            FROM price_snapshot
            WHERE market_hash_name = :name
            GROUP BY platform
        ) lt ON ps.platform = lt.platform AND ps.snapshot_minute = lt.latest
        WHERE ps.market_hash_name = :name
    """), {"name": market_hash_name})
    platforms = [
        {"platform": r[0], "sell_price": r[1], "sell_count": r[2], "bidding_price": r[3]}
        for r in platform_r.fetchall()
    ]

    # Ownership info
    inv_r = await db.execute(
        select(InventoryItem)
        .where(
            InventoryItem.market_hash_name == market_hash_name,
            InventoryItem.status.in_(["in_steam", "rented_out"]),
        )
        .limit(1)
    )
    inv = inv_r.scalar_one_or_none()
    ownership = None
    if inv:
        eff = inv.purchase_price_manual or inv.purchase_price
        current = closes[-1] if closes else None
        pnl = None
        pnl_pct = None
        if eff and eff > 0 and current:
            pnl = current - eff
            pnl_pct = pnl / eff * 100
        ownership = {
            "purchase_price": eff,
            "current_price": current,
            "pnl": round(pnl, 2) if pnl is not None else None,
            "pnl_pct": round(pnl_pct, 1) if pnl_pct is not None else None,
            "status": inv.status,
            "count": 1,  # could aggregate
        }

    signal_data = None
    if sig:
        signal_data = {
            "signal_date": sig.signal_date,
            "rsi_14": round(sig.rsi_14, 1) if sig.rsi_14 else None,
            "bb_position": round(sig.bb_position, 2) if sig.bb_position else None,
            "bb_width": round(sig.bb_width, 3) if sig.bb_width else None,
            "momentum_7": round(sig.momentum_7, 1) if sig.momentum_7 else None,
            "momentum_30": round(sig.momentum_30, 1) if sig.momentum_30 else None,
            "volatility_30": round(sig.volatility_30, 1) if sig.volatility_30 else None,
            "ma_7": round(sig.ma_7, 2) if sig.ma_7 else None,
            "ma_30": round(sig.ma_30, 2) if sig.ma_30 else None,
            "ath_price": round(sig.ath_price, 2) if sig.ath_price else None,
            "ath_pct": round(sig.ath_pct, 1) if sig.ath_pct else None,
            "spread_pct": round(sig.spread_pct, 1) if sig.spread_pct else None,
            "sell_score": round(sig.sell_score, 1) if sig.sell_score else None,
            "opportunity_score": round(sig.opportunity_score, 1) if sig.opportunity_score else None,
        }

    return {
        "market_hash_name": market_hash_name,
        "signal": signal_data,
        "chart_data": chart_data,
        "platforms": platforms,
        "ownership": ownership,
    }


# ── Alerts ───────────────────────────────────────────────────────────────

@router.get("/alerts")
async def list_alerts(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    severity: Optional[str] = Query(None),
    alert_type: Optional[str] = Query(None),
    unread_only: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    """预警列表（分页）"""
    q = select(QuantAlert)
    count_q = select(func.count()).select_from(QuantAlert)

    if severity:
        q = q.where(QuantAlert.severity == severity)
        count_q = count_q.where(QuantAlert.severity == severity)
    if alert_type:
        q = q.where(QuantAlert.alert_type == alert_type)
        count_q = count_q.where(QuantAlert.alert_type == alert_type)
    if unread_only:
        q = q.where(QuantAlert.is_read == False)
        count_q = count_q.where(QuantAlert.is_read == False)

    total = (await db.execute(count_q)).scalar() or 0

    q = q.order_by(QuantAlert.created_at.desc())
    q = q.offset((page - 1) * page_size).limit(page_size)
    rows = (await db.execute(q)).scalars().all()

    return {
        "items": [
            {
                "id": a.id,
                "market_hash_name": a.market_hash_name,
                "alert_type": a.alert_type,
                "severity": a.severity,
                "title": a.title,
                "detail": a.detail,
                "current_value": a.current_value,
                "threshold": a.threshold,
                "is_read": a.is_read,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.patch("/alerts/{alert_id}/read")
async def mark_alert_read(alert_id: int, db: AsyncSession = Depends(get_db)):
    await db.execute(
        update(QuantAlert).where(QuantAlert.id == alert_id).values(is_read=True)
    )
    await db.commit()
    return {"ok": True}


@router.post("/alerts/read-all")
async def mark_all_read(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        update(QuantAlert).where(QuantAlert.is_read == False).values(is_read=True)
    )
    await db.commit()
    return {"ok": True, "count": result.rowcount}


# ── Rankings ─────────────────────────────────────────────────────────────

@router.get("/rankings")
async def signal_rankings(
    sort_by: str = Query("sell_score"),
    sort_order: str = Query("desc"),
    category: Optional[str] = Query(None),
    owned_only: bool = Query(True),
    min_score: Optional[float] = Query(None),
    max_score: Optional[float] = Query(None),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(30, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """按指标排序的信号排名表"""
    # Latest signal date
    latest_r = await db.execute(select(func.max(QuantSignal.signal_date)))
    latest_date = latest_r.scalar()
    if not latest_date:
        return {"items": [], "total": 0, "signal_date": None}

    q = select(QuantSignal).where(QuantSignal.signal_date == latest_date)

    if owned_only:
        owned_q = (
            select(InventoryItem.market_hash_name)
            .where(InventoryItem.status.in_(["in_steam", "rented_out"]))
            .distinct()
        )
        q = q.where(QuantSignal.market_hash_name.in_(owned_q))

    # Category filter
    if category:
        cat_cond = _sql_category_filter(category)
        if cat_cond is not None:
            q = q.where(cat_cond)

    # Score range filter (for clickable distribution)
    if min_score is not None:
        q = q.where(QuantSignal.sell_score >= min_score)
    if max_score is not None:
        q = q.where(QuantSignal.sell_score < max_score)

    # Name search
    if search:
        q = q.where(QuantSignal.market_hash_name.ilike(f"%{search}%"))

    # Sort
    allowed_sorts = {
        "sell_score", "opportunity_score", "rsi_14", "momentum_7",
        "momentum_30", "volatility_30", "spread_pct", "ath_pct",
    }
    if sort_by not in allowed_sorts:
        sort_by = "sell_score"
    col = getattr(QuantSignal, sort_by)
    q = q.order_by(col.desc() if sort_order == "desc" else col.asc())

    # Count
    count_q = select(func.count()).select_from(q.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    q = q.offset((page - 1) * page_size).limit(page_size)
    rows = (await db.execute(q)).scalars().all()

    return {
        "items": [
            {
                "market_hash_name": s.market_hash_name,
                "sell_score": round(s.sell_score, 1) if s.sell_score else None,
                "opportunity_score": round(s.opportunity_score, 1) if s.opportunity_score else None,
                "rsi_14": round(s.rsi_14, 1) if s.rsi_14 else None,
                "bb_position": round(s.bb_position, 2) if s.bb_position else None,
                "momentum_7": round(s.momentum_7, 1) if s.momentum_7 else None,
                "momentum_30": round(s.momentum_30, 1) if s.momentum_30 else None,
                "volatility_30": round(s.volatility_30, 1) if s.volatility_30 else None,
                "ath_pct": round(s.ath_pct, 1) if s.ath_pct else None,
                "spread_pct": round(s.spread_pct, 1) if s.spread_pct else None,
            }
            for s in rows
        ],
        "total": total,
        "signal_date": latest_date,
        "page": page,
    }


def _sql_category_filter(category: str):
    """Quick SQL-based category filter for quant_signal."""
    if category == "knife":
        return and_(
            QuantSignal.market_hash_name.like("★%"),
            ~QuantSignal.market_hash_name.ilike("%Gloves%"),
            ~QuantSignal.market_hash_name.ilike("%Wraps%"),
        )
    if category == "glove":
        return and_(
            QuantSignal.market_hash_name.like("★%"),
            or_(
                QuantSignal.market_hash_name.ilike("%Gloves%"),
                QuantSignal.market_hash_name.ilike("%Wraps%"),
            ),
        )
    patterns_map = {
        "pistol": ["Glock-18%", "USP-S%", "P250%", "CZ75%", "Five-SeveN%", "Tec-9%",
                    "Desert Eagle%", "R8 Revolver%", "P2000%", "Dual Berettas%"],
        "rifle":  ["AK-47%", "M4A4%", "M4A1-S%", "FAMAS%", "Galil AR%", "AUG%", "SG 553%"],
        "sniper": ["AWP%", "SSG 08%", "SCAR-20%", "G3SG1%"],
        "smg":    ["MP9%", "MP5-SD%", "MAC-10%", "PP-Bizon%", "UMP-45%", "P90%", "MP7%"],
        "sticker": ["Sticker |%", "Patch |%"],
        "case":   ["% Case%", "%Capsule%", "%Package%"],
    }
    patterns = patterns_map.get(category, [])
    if not patterns:
        return None
    return or_(*[QuantSignal.market_hash_name.like(p) for p in patterns])


# ── Price History (chart data) ───────────────────────────────────────────

@router.get("/price-history")
async def get_price_history(
    market_hash_name: str = Query(...),
    days: int = Query(90, ge=7, le=365),
    platform: str = Query("ALL"),
    db: AsyncSession = Depends(get_db),
):
    """返回图表数据：日期 + OHLC + MA + BB"""
    result = await db.execute(
        select(PriceHistory)
        .where(
            PriceHistory.market_hash_name == market_hash_name,
            PriceHistory.platform == platform,
        )
        .order_by(PriceHistory.record_date.desc())
        .limit(days)
    )
    rows = result.scalars().all()
    rows.reverse()

    # Filter out rows with 0/null close_price, or replace with latest known
    last_good = None
    for r in rows:
        if r.close_price and r.close_price > 0:
            last_good = r.close_price
        elif last_good:
            # Fill forward: use last known good price
            r.close_price = last_good

    closes = [r.close_price for r in rows if r.close_price and r.close_price > 0]

    from app.services.quant_engine import _sma, calc_bollinger

    dates = []
    close_prices = []
    ma7_list = []
    ma30_list = []
    bb_upper_list = []
    bb_lower_list = []

    ci = 0
    for i, r in enumerate(rows):
        cp = r.close_price if r.close_price and r.close_price > 0 else None
        if cp is None:
            continue  # skip rows with no price
        dates.append(r.record_date)
        close_prices.append(cp)
        ci += 1
        sub = closes[:ci]
        ma7_list.append(round(_sma(sub, 7), 2) if _sma(sub, 7) else None)
        ma30_list.append(round(_sma(sub, 30), 2) if _sma(sub, 30) else None)
        bb = calc_bollinger(sub) if len(sub) >= 20 else None
        bb_upper_list.append(round(bb["upper"], 2) if bb else None)
        bb_lower_list.append(round(bb["lower"], 2) if bb else None)

    return {
        "market_hash_name": market_hash_name,
        "platform": platform,
        "dates": dates,
        "close_prices": close_prices,
        "ma7": ma7_list,
        "ma30": ma30_list,
        "bb_upper": bb_upper_list,
        "bb_lower": bb_lower_list,
    }


# ── Spreads (Arbitrage Radar) ────────────────────────────────────────────

@router.get("/spreads")
async def spread_radar(
    min_spread: float = Query(5.0, ge=0),
    page: int = Query(1, ge=1),
    page_size: int = Query(30, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """跨平台价差套利雷达"""
    # Get latest snapshot per item+platform, compute spread
    stmt = text("""
        WITH latest AS (
            SELECT ps.market_hash_name, ps.platform, ps.sell_price, ps.sell_count
            FROM price_snapshot ps
            INNER JOIN (
                SELECT market_hash_name, platform, MAX(snapshot_minute) AS latest
                FROM price_snapshot
                GROUP BY market_hash_name, platform
            ) lt ON ps.market_hash_name = lt.market_hash_name
                AND ps.platform = lt.platform
                AND ps.snapshot_minute = lt.latest
            WHERE ps.sell_price IS NOT NULL AND ps.sell_price > 0 AND ps.platform != 'STEAM'
        ),
        spreads AS (
            SELECT market_hash_name,
                   MAX(sell_price) AS max_price,
                   MIN(sell_price) AS min_price,
                   COUNT(*) AS platform_count,
                   (MAX(sell_price) - MIN(sell_price)) * 100.0 / MIN(sell_price) AS spread_pct
            FROM latest
            GROUP BY market_hash_name
            HAVING COUNT(*) >= 2 AND MIN(sell_price) > 0
        )
        SELECT market_hash_name, max_price, min_price, platform_count, spread_pct
        FROM spreads
        WHERE spread_pct >= :min_spread
        ORDER BY spread_pct DESC
        LIMIT :limit OFFSET :offset
    """)
    rows = (await db.execute(stmt, {
        "min_spread": min_spread,
        "limit": page_size,
        "offset": (page - 1) * page_size,
    })).fetchall()

    # Get platform breakdown for these items
    items = []
    for row in rows:
        name = row[0]
        # Fetch per-platform prices
        plat_r = await db.execute(text("""
            SELECT ps.platform, ps.sell_price, ps.sell_count
            FROM price_snapshot ps
            INNER JOIN (
                SELECT platform, MAX(snapshot_minute) AS latest
                FROM price_snapshot
                WHERE market_hash_name = :name
                GROUP BY platform
            ) lt ON ps.platform = lt.platform AND ps.snapshot_minute = lt.latest
            WHERE ps.market_hash_name = :name AND ps.sell_price > 0 AND ps.platform != 'STEAM'
        """), {"name": name})
        platforms = [
            {"platform": p[0], "sell_price": p[1], "sell_count": p[2]}
            for p in plat_r.fetchall()
        ]
        items.append({
            "market_hash_name": name,
            "max_price": row[1],
            "min_price": row[2],
            "platform_count": row[3],
            "spread_pct": round(row[4], 1),
            "platforms": platforms,
        })

    # Total count
    count_r = await db.execute(text("""
        SELECT COUNT(*) FROM (
            SELECT market_hash_name
            FROM price_snapshot ps
            INNER JOIN (
                SELECT market_hash_name m, platform p, MAX(snapshot_minute) AS latest
                FROM price_snapshot GROUP BY market_hash_name, platform
            ) lt ON ps.market_hash_name = lt.m AND ps.platform = lt.p AND ps.snapshot_minute = lt.latest
            WHERE ps.sell_price > 0 AND ps.platform != 'STEAM'
            GROUP BY ps.market_hash_name
            HAVING COUNT(*) >= 2
               AND (MAX(ps.sell_price) - MIN(ps.sell_price)) * 100.0 / MIN(ps.sell_price) >= :min_spread
        )
    """), {"min_spread": min_spread})
    total = count_r.scalar() or 0

    return {"items": items, "total": total, "page": page}


# ── Category Trends ──────────────────────────────────────────────────────

@router.get("/categories")
async def category_trends(db: AsyncSession = Depends(get_db)):
    """各武器类别趋势汇总"""
    latest_r = await db.execute(select(func.max(QuantSignal.signal_date)))
    latest_date = latest_r.scalar()
    if not latest_date:
        return {"categories": [], "signal_date": None}

    trends = await _get_category_trends(db, latest_date)
    return {"categories": trends, "signal_date": latest_date}


# ── Backfill / Manual Compute ────────────────────────────────────────────

@router.post("/backfill")
async def trigger_backfill():
    """触发历史数据回填（后台任务）"""
    from app.services.collector import backfill_avg_prices

    if backfill_state["status"] == "running":
        return {"started": False, "message": "回填已在运行中", "state": backfill_state}

    asyncio.create_task(backfill_avg_prices())
    return {"started": True, "message": "历史数据回填已启动", "state": backfill_state}


@router.post("/compute-now")
async def compute_now():
    """手动触发信号计算（不等待定时任务）"""
    from app.services.collector import aggregate_daily, compute_signals
    from datetime import datetime, timezone

    today = datetime.now(timezone.utc).strftime("%Y%m%d")

    try:
        # First aggregate today's snapshots
        await aggregate_daily(today)
        # Then compute signals
        await compute_signals()
        # Also run quick PnL alerts
        from app.services.quant_engine import compute_quick_pnl_alerts
        alert_count = await compute_quick_pnl_alerts()
        return {"ok": True, "message": f"信号计算完成, 生成 {alert_count} 条预警"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/collector/status")
async def get_collector_status():
    """采集器运行状态"""
    return {
        "collector": collector_state,
        "backfill": backfill_state,
    }


# ── Item search for analysis ─────────────────────────────────────────────

@router.get("/search-items")
async def search_items(
    q: str = Query("", min_length=0),
    limit: int = Query(20, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    """搜索物品（用于个股分析搜索框）"""
    if not q:
        # Return items with signals, sorted by sell_score
        latest_r = await db.execute(select(func.max(QuantSignal.signal_date)))
        latest_date = latest_r.scalar()
        if not latest_date:
            return {"items": []}

        result = await db.execute(
            select(QuantSignal.market_hash_name, QuantSignal.sell_score)
            .where(
                QuantSignal.signal_date == latest_date,
                QuantSignal.market_hash_name.in_(
                    select(InventoryItem.market_hash_name)
                    .where(InventoryItem.status.in_(["in_steam", "rented_out"]))
                    .distinct()
                ),
            )
            .order_by(QuantSignal.sell_score.desc())
            .limit(limit)
        )
        return {"items": [{"market_hash_name": r[0], "sell_score": round(r[1], 1) if r[1] else None} for r in result.all()]}

    # Search by name
    result = await db.execute(
        select(InventoryItem.market_hash_name)
        .where(
            InventoryItem.status.in_(["in_steam", "rented_out"]),
            or_(
                InventoryItem.market_hash_name.ilike(f"%{q}%"),
                InventoryItem.name.ilike(f"%{q}%"),
            ),
        )
        .distinct()
        .limit(limit)
    )
    return {"items": [{"market_hash_name": r[0]} for r in result.all()]}
