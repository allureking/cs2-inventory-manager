"""
Quantitative signal engine for CS2 skins.

Computes technical indicators from price_history and generates
composite scores + alerts.

Indicators:
  RSI(14)          — Relative Strength Index
  Bollinger %B     — Position within Bollinger Bands (MA20, 2σ)
  Momentum 7d/30d  — Rate of change
  Volatility 30d   — Annualized standard deviation of log returns
  ATH proximity    — Current price / all-time-high %
  Cross-platform spread — (max-min)/min price across platforms
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import and_, delete, func, select, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models.db_models import (
    InventoryItem,
    PriceHistory,
    PriceSnapshot,
    QuantAlert,
    QuantSignal,
)

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════
#  Pure math helpers (operate on plain lists)
# ══════════════════════════════════════════════════════════════

def _sma(values: list[float], period: int) -> Optional[float]:
    """Simple moving average of the last `period` values."""
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def _ema(values: list[float], period: int) -> Optional[float]:
    """Exponential moving average of the full series, returning the last value."""
    if len(values) < period:
        return None
    k = 2 / (period + 1)
    ema = sum(values[:period]) / period  # seed with SMA
    for v in values[period:]:
        ema = v * k + ema * (1 - k)
    return ema


def calc_rsi(closes: list[float], period: int = 14) -> Optional[float]:
    """RSI using EMA smoothing (Wilder's method)."""
    if len(closes) < period + 1:
        return None
    changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(c, 0) for c in changes]
    losses = [max(-c, 0) for c in changes]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - 100 / (1 + rs)


def calc_bollinger(
    closes: list[float], period: int = 20, num_std: float = 2.0
) -> Optional[dict]:
    """
    Returns {ma, upper, lower, pct_b, bandwidth} or None if not enough data.
    pct_b = (close - lower) / (upper - lower)
    """
    if len(closes) < period:
        return None

    window = closes[-period:]
    ma = sum(window) / period
    variance = sum((x - ma) ** 2 for x in window) / period
    std = math.sqrt(variance)

    upper = ma + num_std * std
    lower = ma - num_std * std

    band_range = upper - lower
    if band_range == 0:
        pct_b = 0.5
        bandwidth = 0.0
    else:
        pct_b = (closes[-1] - lower) / band_range
        bandwidth = band_range / ma if ma else 0.0

    return {
        "ma": ma,
        "upper": upper,
        "lower": lower,
        "pct_b": pct_b,
        "bandwidth": bandwidth,
    }


def calc_momentum(closes: list[float], period: int) -> Optional[float]:
    """Rate of change: (close_now - close_N_ago) / close_N_ago * 100."""
    if len(closes) <= period or closes[-period - 1] == 0:
        return None
    return (closes[-1] - closes[-period - 1]) / closes[-period - 1] * 100


def calc_volatility(closes: list[float], period: int = 30) -> Optional[float]:
    """Annualized volatility from log returns over the last `period` days."""
    if len(closes) < period + 1:
        return None

    log_returns = []
    for i in range(-period, 0):
        if closes[i - 1] > 0 and closes[i] > 0:
            log_returns.append(math.log(closes[i] / closes[i - 1]))

    if len(log_returns) < 5:
        return None

    mean = sum(log_returns) / len(log_returns)
    variance = sum((r - mean) ** 2 for r in log_returns) / len(log_returns)
    daily_vol = math.sqrt(variance)
    return daily_vol * math.sqrt(365) * 100  # annualized, as %


# ══════════════════════════════════════════════════════════════
#  Composite scoring
# ══════════════════════════════════════════════════════════════

def compute_sell_score(
    rsi: Optional[float],
    bb_pos: Optional[float],
    momentum_30: Optional[float],
    ath_pct: Optional[float],
    pnl_pct: Optional[float] = None,
) -> float:
    """
    Weighted composite sell score (0-100).
    Higher = stronger sell signal.
    """
    score = 50.0  # neutral baseline

    # RSI contribution (weight 25%)
    if rsi is not None:
        if rsi > 70:
            score += (rsi - 70) * 0.83  # max +25 at RSI=100
        elif rsi < 30:
            score -= (30 - rsi) * 0.83

    # Bollinger %B contribution (weight 20%)
    if bb_pos is not None:
        score += (bb_pos - 0.5) * 40  # range: -20 to +20

    # Momentum contribution (weight 15%)
    if momentum_30 is not None:
        score += max(min(momentum_30 * 0.3, 15), -15)

    # ATH proximity (weight 20%)
    if ath_pct is not None and ath_pct > 80:
        score += (ath_pct - 80) * 1.0  # max +20 at 100%

    # Profit contribution (weight 20%)
    if pnl_pct is not None and pnl_pct > 50:
        score += min((pnl_pct - 50) * 0.4, 20)

    return max(0.0, min(100.0, score))


def compute_opportunity_score(
    rsi: Optional[float],
    bb_pos: Optional[float],
    momentum_7: Optional[float],
    spread_pct: Optional[float],
) -> float:
    """
    Buy-opportunity score (0-100).
    Higher = stronger buy signal.
    """
    score = 50.0

    # Oversold RSI (weight 30%)
    if rsi is not None and rsi < 30:
        score += (30 - rsi) * 1.0  # max +30 at RSI=0

    # Below lower Bollinger (weight 25%)
    if bb_pos is not None and bb_pos < 0:
        score += min(-bb_pos * 25, 25)

    # Negative momentum = dip (weight 20%)
    if momentum_7 is not None and momentum_7 < -5:
        score += min((-momentum_7 - 5) * 1.0, 20)

    # Cross-platform spread (weight 25%)
    if spread_pct is not None and spread_pct > 5:
        score += min((spread_pct - 5) * 1.5, 25)

    return max(0.0, min(100.0, score))


# ══════════════════════════════════════════════════════════════
#  Main computation pipeline
# ══════════════════════════════════════════════════════════════

async def compute_all_signals(target_date: Optional[str] = None) -> int:
    """
    Compute all quant signals for each unique market_hash_name.
    Also generates alerts. Returns number of signals written.
    """
    if target_date is None:
        target_date = datetime.now(timezone.utc).strftime("%Y%m%d")

    async with AsyncSessionLocal() as db:
        # Get all unique names that have price_history
        result = await db.execute(
            select(PriceHistory.market_hash_name).distinct()
        )
        all_names = [row[0] for row in result.all()]

        if not all_names:
            logger.info("compute_all_signals: no price_history data yet")
            return 0

        # Also get purchase prices for PnL-based scoring
        inv_result = await db.execute(
            select(
                InventoryItem.market_hash_name,
                func.coalesce(
                    InventoryItem.purchase_price_manual,
                    InventoryItem.purchase_price,
                ).label("eff_price"),
            )
            .where(InventoryItem.status.in_(["in_steam", "rented_out"]))
        )
        purchase_map: dict[str, float] = {}
        for row in inv_result.all():
            if row[1] is not None and row[1] > 0:
                purchase_map[row[0]] = float(row[1])

        # Get latest cross-platform snapshots for spread calculation
        spread_map = await _calc_spread_map(db)

        count = 0
        for name in all_names:
            try:
                sig = await _compute_item_signals(db, name, target_date, purchase_map, spread_map)
                if sig:
                    count += 1
            except Exception as e:
                logger.warning("signal error for %s: %s", name, e)

        await db.commit()
        logger.info("compute_all_signals: wrote %d signals for %s", count, target_date)

        # Generate alerts
        await _generate_alerts(db, target_date, purchase_map)
        await db.commit()

        return count


async def _compute_item_signals(
    db: AsyncSession,
    market_hash_name: str,
    signal_date: str,
    purchase_map: dict[str, float],
    spread_map: dict[str, float],
) -> Optional[dict]:
    """Compute all indicators for a single item and upsert to quant_signal."""
    # Fetch price history (platform=ALL, ordered by date ascending)
    result = await db.execute(
        select(PriceHistory.close_price, PriceHistory.record_date)
        .where(
            and_(
                PriceHistory.market_hash_name == market_hash_name,
                PriceHistory.platform == "ALL",
            )
        )
        .order_by(PriceHistory.record_date.asc())
    )
    rows = result.all()
    closes = [float(r[0]) for r in rows if r[0] is not None and r[0] > 0]

    if len(closes) < 3:
        return None

    current_price = closes[-1]

    # Compute indicators
    rsi = calc_rsi(closes)
    bb = calc_bollinger(closes)
    mom7 = calc_momentum(closes, 7)
    mom30 = calc_momentum(closes, 30)
    vol30 = calc_volatility(closes)
    ma7 = _sma(closes, 7)
    ma30 = _sma(closes, 30)
    ath_price = max(closes)
    ath_pct = (current_price / ath_price * 100) if ath_price > 0 else None
    spread = spread_map.get(market_hash_name)

    # PnL for sell score
    pnl_pct = None
    buy_price = purchase_map.get(market_hash_name)
    if buy_price and buy_price > 0:
        pnl_pct = (current_price - buy_price) / buy_price * 100

    sell = compute_sell_score(rsi, bb["pct_b"] if bb else None, mom30, ath_pct, pnl_pct)
    opp = compute_opportunity_score(rsi, bb["pct_b"] if bb else None, mom7, spread)

    values = {
        "market_hash_name": market_hash_name,
        "signal_date": signal_date,
        "rsi_14": rsi,
        "bb_position": bb["pct_b"] if bb else None,
        "bb_width": bb["bandwidth"] if bb else None,
        "momentum_7": mom7,
        "momentum_30": mom30,
        "volatility_30": vol30,
        "ma_7": ma7,
        "ma_30": ma30,
        "ath_price": ath_price,
        "ath_pct": ath_pct,
        "spread_pct": spread,
        "sell_score": sell,
        "opportunity_score": opp,
    }

    stmt = sqlite_insert(QuantSignal).values(values)
    stmt = stmt.on_conflict_do_update(
        index_elements=["market_hash_name", "signal_date"],
        set_={k: getattr(stmt.excluded, k) for k in values if k not in ("market_hash_name", "signal_date")},
    )
    await db.execute(stmt)
    return values


async def _calc_spread_map(db: AsyncSession) -> dict[str, float]:
    """
    Calculate cross-platform spread for each item from latest price_snapshot.
    spread = (max_sell - min_sell) / min_sell * 100
    """
    # Get latest snapshot_minute per item+platform
    stmt = text("""
        SELECT market_hash_name,
               MAX(sell_price) AS max_p,
               MIN(sell_price) AS min_p
        FROM (
            SELECT ps.market_hash_name, ps.platform, ps.sell_price
            FROM price_snapshot ps
            INNER JOIN (
                SELECT market_hash_name, platform, MAX(snapshot_minute) AS latest
                FROM price_snapshot
                GROUP BY market_hash_name, platform
            ) lt ON ps.market_hash_name = lt.market_hash_name
                AND ps.platform = lt.platform
                AND ps.snapshot_minute = lt.latest
            WHERE ps.sell_price IS NOT NULL AND ps.sell_price > 0
        )
        GROUP BY market_hash_name
        HAVING COUNT(*) >= 2 AND MIN(sell_price) > 0
    """)
    result = await db.execute(stmt)
    spread_map = {}
    for row in result.fetchall():
        name, max_p, min_p = row[0], row[1], row[2]
        if min_p > 0:
            spread_map[name] = (max_p - min_p) / min_p * 100
    return spread_map


# ══════════════════════════════════════════════════════════════
#  Alert generation
# ══════════════════════════════════════════════════════════════

_ALERT_RULES = [
    # (alert_type, severity, field, op, threshold, title_template)
    ("profit_50",       "warning",  "pnl_pct",     ">", 50,  "盈利超50%: {name} ({val:.1f}%)"),
    ("profit_100",      "critical", "pnl_pct",     ">", 100, "盈利超100%: {name} ({val:.1f}%)"),
    ("near_ath",        "warning",  "ath_pct",     ">", 90,  "接近历史高点: {name} (ATH {val:.1f}%)"),
    ("rsi_overbought",  "warning",  "rsi_14",      ">", 75,  "RSI超买: {name} (RSI={val:.1f})"),
    ("rsi_oversold",    "info",     "rsi_14",      "<", 25,  "RSI超卖: {name} (RSI={val:.1f})"),
    ("momentum_surge",  "warning",  "momentum_7",  ">", 20,  "7日暴涨: {name} (+{val:.1f}%)"),
    ("spread_arb",      "info",     "spread_pct",  ">", 15,  "跨平台价差: {name} ({val:.1f}%)"),
]


async def _generate_alerts(
    db: AsyncSession,
    signal_date: str,
    purchase_map: dict[str, float],
) -> int:
    """Generate alerts from latest signals. Avoids duplicate alerts within 24h."""
    result = await db.execute(
        select(QuantSignal).where(QuantSignal.signal_date == signal_date)
    )
    signals = result.scalars().all()

    # Get latest snapshot prices for PnL calculation
    price_map = await _get_latest_prices(db)

    alert_count = 0
    for sig in signals:
        # Build a values dict for rule matching
        vals: dict[str, Optional[float]] = {
            "rsi_14": sig.rsi_14,
            "bb_position": sig.bb_position,
            "momentum_7": sig.momentum_7,
            "momentum_30": sig.momentum_30,
            "ath_pct": sig.ath_pct,
            "spread_pct": sig.spread_pct,
        }
        # Add PnL
        buy = purchase_map.get(sig.market_hash_name)
        current = price_map.get(sig.market_hash_name)
        if buy and buy > 0 and current and current > 0:
            vals["pnl_pct"] = (current - buy) / buy * 100
        else:
            vals["pnl_pct"] = None

        for alert_type, severity, field, op, threshold, title_tpl in _ALERT_RULES:
            val = vals.get(field)
            if val is None:
                continue

            triggered = (op == ">" and val > threshold) or (op == "<" and val < threshold)
            if not triggered:
                continue

            # Check for recent duplicate (same type + item within last 24h)
            existing = await db.execute(
                select(func.count()).select_from(QuantAlert).where(
                    and_(
                        QuantAlert.market_hash_name == sig.market_hash_name,
                        QuantAlert.alert_type == alert_type,
                        QuantAlert.created_at > func.datetime("now", "-1 day"),
                    )
                )
            )
            if (existing.scalar() or 0) > 0:
                continue

            title = title_tpl.format(name=sig.market_hash_name, val=val)
            db.add(QuantAlert(
                market_hash_name=sig.market_hash_name,
                alert_type=alert_type,
                severity=severity,
                title=title,
                detail=f"signal_date={signal_date}, {field}={val:.2f}, threshold={threshold}",
                current_value=val,
                threshold=float(threshold),
            ))
            alert_count += 1

    logger.info("generated %d alerts for %s", alert_count, signal_date)
    return alert_count


async def _get_latest_prices(db: AsyncSession) -> dict[str, float]:
    """Get latest sell_price per item from price_snapshot (platform with lowest price)."""
    stmt = text("""
        SELECT ps.market_hash_name, MIN(ps.sell_price)
        FROM price_snapshot ps
        INNER JOIN (
            SELECT market_hash_name, MAX(snapshot_minute) AS latest
            FROM price_snapshot
            GROUP BY market_hash_name
        ) lt ON ps.market_hash_name = lt.market_hash_name
            AND ps.snapshot_minute = lt.latest
        WHERE ps.sell_price IS NOT NULL AND ps.sell_price > 0
        GROUP BY ps.market_hash_name
    """)
    result = await db.execute(stmt)
    return {row[0]: float(row[1]) for row in result.fetchall()}


# ══════════════════════════════════════════════════════════════
#  Day-1 quick signals (no history needed)
# ══════════════════════════════════════════════════════════════

async def compute_quick_pnl_alerts() -> int:
    """
    Generate profit-based alerts using purchase_price + latest price_snapshot.
    Works on Day 1 without any price_history accumulation.
    """
    async with AsyncSessionLocal() as db:
        price_map = await _get_latest_prices(db)
        if not price_map:
            return 0

        result = await db.execute(
            select(
                InventoryItem.market_hash_name,
                func.coalesce(
                    InventoryItem.purchase_price_manual,
                    InventoryItem.purchase_price,
                ).label("eff_price"),
            )
            .where(
                InventoryItem.status.in_(["in_steam", "rented_out"]),
                func.coalesce(
                    InventoryItem.purchase_price_manual,
                    InventoryItem.purchase_price,
                ).isnot(None),
            )
        )

        alert_count = 0
        for row in result.all():
            name, buy_price = row[0], float(row[1])
            if buy_price <= 0:
                continue
            current = price_map.get(name)
            if not current:
                continue

            pnl_pct = (current - buy_price) / buy_price * 100

            for threshold, alert_type, severity in [
                (100, "profit_100", "critical"),
                (50,  "profit_50",  "warning"),
            ]:
                if pnl_pct > threshold:
                    # Check duplicate
                    existing = await db.execute(
                        select(func.count()).select_from(QuantAlert).where(
                            and_(
                                QuantAlert.market_hash_name == name,
                                QuantAlert.alert_type == alert_type,
                                QuantAlert.created_at > func.datetime("now", "-1 day"),
                            )
                        )
                    )
                    if (existing.scalar() or 0) > 0:
                        continue

                    db.add(QuantAlert(
                        market_hash_name=name,
                        alert_type=alert_type,
                        severity=severity,
                        title=f"盈利超{threshold}%: {name} ({pnl_pct:.1f}%)",
                        detail=f"buy={buy_price:.2f}, current={current:.2f}",
                        current_value=pnl_pct,
                        threshold=float(threshold),
                    ))
                    alert_count += 1
                    break  # Only highest alert per item

        await db.commit()
        logger.info("quick_pnl_alerts: generated %d alerts", alert_count)
        return alert_count
