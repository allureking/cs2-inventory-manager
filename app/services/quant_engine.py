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
    pnl_pct: Optional[float] = None,
    target_pnl_pct: float = 30.0,
    annualized_return: Optional[float] = None,
    days_held: int = 0,
    concentration_pct: Optional[float] = None,
    holding_count: int = 1,
    volatility_zscore: Optional[float] = None,
    rsi: Optional[float] = None,
    bb_pos: Optional[float] = None,
    momentum_30: Optional[float] = None,
    market_share_pct: Optional[float] = None,
) -> float:
    """
    CS2 大商决策模型 — 综合卖出评分 (0-100).

    五维度加权:
      1. 收益达标度  30%  — 当前收益 vs 目标收益，达标拉满；深亏则降分
      2. 年化收益衰减 20%  — 持有越久但年化越低 → 卖出信号
      3. 持仓集中度  20%  — 单品件数/市值占比过高 → 减仓
      4. 异常波动    25%  — 波动率 z-score + RSI/BB/动量 子因子
      5. 市场冲击     5%  — 持仓占市场在售比例 → 卖出可行性
    """
    score = 45.0  # slightly below neutral — no signal = 不急卖

    # ── 维度1: 收益达标度 (30%) ── range: -22 ~ +30
    if pnl_pct is not None and target_pnl_pct > 0:
        ratio = pnl_pct / target_pnl_pct
        if ratio >= 1.5:
            # 超额完成 150%+，强烈卖出
            score += 30
        elif ratio >= 1.0:
            # 达标~150%，递增
            score += 20 + (ratio - 1.0) * 20  # 20~30
        elif ratio >= 0:
            # 盈利但未达标，微弱卖出信号
            score += ratio * 12  # 0~12
        else:
            # 亏损：显著降低卖出分数（深亏 = 绝不该卖）
            score += max(-22, pnl_pct * 0.5)  # -25%亏损 → -12.5分

    # ── 维度2: 年化收益衰减 (20%) ── range: -5 ~ +20
    #    仅在盈利状态下生效：物品在涨但增速放缓 → 考虑卖出
    #    亏损时此维度不参与（亏损已在维度1体现）
    if annualized_return is not None and days_held > 30 and (pnl_pct is None or pnl_pct >= 0):
        benchmark = 15.0  # 年化收益率基准（CS2 饰品合理预期）
        if annualized_return < benchmark:
            # 低于基准 → 按差距给分
            score += (benchmark - annualized_return) / benchmark * 15  # 0~15
        elif annualized_return > benchmark * 3:
            # 年化收益极高（>45%），说明还在快速增长，降低卖出分
            score -= 5

    # ── 维度3: 持仓集中度 (20%) ── range: 0 ~ +20
    if concentration_pct is not None:
        if concentration_pct > 15:
            score += min(20, 10 + (concentration_pct - 15) * 0.5)
        elif concentration_pct > 5:
            score += (concentration_pct - 5) * 1.0  # 0~10
        # 持有件数过多额外加分（大批量持仓需要减仓）
        if holding_count > 50:
            score += min(5, (holding_count - 50) * 0.05)
        elif holding_count > 20:
            score += min(3, (holding_count - 20) * 0.1)

    # ── 维度4: 异常波动 (25%) ── range: -12 ~ +25
    wave = 0.0
    # 4a. 波动率 z-score vs 同类（权重最大的子因子）
    if volatility_zscore is not None:
        if volatility_zscore > 2.0:
            wave += min(volatility_zscore * 4, 15)  # 异常高波动
        elif volatility_zscore > 1.0:
            wave += (volatility_zscore - 1.0) * 8   # 偏高
        elif volatility_zscore < -1.5:
            wave -= min(-volatility_zscore * 2, 6)   # 异常低波动（不急卖）
    # 4b. RSI 超买/超卖
    if rsi is not None:
        if rsi > 75:
            wave += min((rsi - 75) * 0.4, 5)
        elif rsi < 25:
            wave -= min((25 - rsi) * 0.24, 6)
    # 4c. 布林带位置
    if bb_pos is not None:
        if bb_pos > 0.9:
            wave += min((bb_pos - 0.9) * 30, 3)     # 接近上轨
        elif bb_pos < 0.1:
            wave -= min((0.1 - bb_pos) * 15, 3)     # 接近下轨
    # 4d. 30日动量
    if momentum_30 is not None:
        if momentum_30 > 15:
            wave += min((momentum_30 - 15) * 0.15, 2)
    score += max(-12, min(25, wave))

    # ── 维度5: 市场冲击 (5%) ── range: 0 ~ +5
    if market_share_pct is not None:
        if market_share_pct > 30:
            score += 5  # 占市场 30%+，卖出会严重砸盘
        elif market_share_pct > 10:
            score += (market_share_pct - 10) * 0.25  # 0~5

    return max(0.0, min(100.0, score))


def compute_opportunity_score(
    rsi: Optional[float],
    bb_pos: Optional[float],
    momentum_7: Optional[float],
    spread_pct: Optional[float],
    pnl_pct: Optional[float] = None,
    target_pnl_pct: float = 30.0,
) -> float:
    """
    Buy-opportunity score (0-100).
    Higher = stronger buy signal.

    维度:
      1. RSI 超卖        25%  — RSI < 30 加分
      2. 布林带下轨      20%  — 价格低于下轨
      3. 短期回调        15%  — 7 日负动量（逢跌买入）
      4. 跨平台价差      20%  — 套利空间
      5. 收益低谷/深亏   20%  — 远低于目标收益 → 增持摊低成本
    """
    score = 50.0

    # 1. Oversold RSI (25%)
    if rsi is not None and rsi < 30:
        score += min((30 - rsi) * 0.83, 25)  # max +25

    # 2. Below lower Bollinger (20%)
    if bb_pos is not None and bb_pos < 0:
        score += min(-bb_pos * 20, 20)

    # 3. Negative momentum = dip (15%)
    if momentum_7 is not None and momentum_7 < -5:
        score += min((-momentum_7 - 5) * 0.75, 15)

    # 4. Cross-platform spread (20%)
    if spread_pct is not None and spread_pct > 5:
        score += min((spread_pct - 5) * 1.2, 20)

    # 5. PnL trough — 深亏 = 增持信号 (20%)
    if pnl_pct is not None and target_pnl_pct > 0:
        if pnl_pct < -20:
            # 亏损超 20%，强买入信号
            score += min((-pnl_pct - 20) * 0.5, 20)
        elif pnl_pct < -5:
            # 轻度亏损
            score += (-pnl_pct - 5) * 0.67  # 0~10
        elif pnl_pct > target_pnl_pct:
            # 已达标，降低买入信号
            score -= min((pnl_pct - target_pnl_pct) * 0.3, 15)

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

        # ── Gather portfolio-wide context ──

        # 1. Purchase prices + target PnL + earliest purchase date per item
        inv_result = await db.execute(
            select(
                InventoryItem.market_hash_name,
                func.coalesce(
                    InventoryItem.purchase_price_manual,
                    InventoryItem.purchase_price,
                ).label("eff_price"),
                InventoryItem.target_pnl_pct,
                func.min(InventoryItem.purchase_date).label("earliest_date"),
                func.min(InventoryItem.first_seen_at).label("earliest_seen"),
            )
            .where(InventoryItem.status.in_(["in_steam", "rented_out"]))
            .group_by(InventoryItem.market_hash_name)
        )
        purchase_map: dict[str, float] = {}
        target_map: dict[str, float] = {}
        days_held_map: dict[str, int] = {}
        now = datetime.now(timezone.utc)
        for row in inv_result.all():
            name = row[0]
            if row[1] is not None and float(row[1]) > 0:
                purchase_map[name] = float(row[1])
            if row[2] is not None:
                target_map[name] = float(row[2])
            # Calculate days held from purchase_date or first_seen_at
            d_str = row[3]  # purchase_date (str like "2025-01-15")
            first_seen = row[4]  # first_seen_at (datetime)
            if d_str:
                try:
                    dt = datetime.strptime(str(d_str)[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
                    days_held_map[name] = max(1, (now - dt).days)
                except ValueError:
                    pass
            if name not in days_held_map and first_seen:
                if hasattr(first_seen, 'days'):
                    days_held_map[name] = max(1, first_seen.days)
                else:
                    try:
                        if first_seen.tzinfo is None:
                            first_seen = first_seen.replace(tzinfo=timezone.utc)
                        days_held_map[name] = max(1, (now - first_seen).days)
                    except (AttributeError, TypeError):
                        pass

        # 2. Holding counts per item (件数)
        count_result = await db.execute(
            select(
                InventoryItem.market_hash_name,
                func.count().label("cnt"),
            )
            .where(InventoryItem.status.in_(["in_steam", "rented_out"]))
            .group_by(InventoryItem.market_hash_name)
        )
        holding_count_map: dict[str, int] = {
            row[0]: int(row[1]) for row in count_result.all()
        }

        # 3. Market sell counts per item (市场在售量 — 各平台合计)
        market_count_map = await _calc_market_count_map(db)

        # 4. Cross-platform spread
        spread_map = await _calc_spread_map(db)

        # 5. Portfolio total value (for concentration calc)
        latest_prices = await _get_latest_prices(db)
        total_portfolio_value = 0.0
        item_market_value: dict[str, float] = {}
        for name, cnt in holding_count_map.items():
            price = latest_prices.get(name, 0)
            val = price * cnt
            item_market_value[name] = val
            total_portfolio_value += val

        # 6. Peer volatility map (item_type → list of vol30)
        #    Pre-compute so we can calculate z-scores
        vol_map: dict[str, float] = {}  # market_hash_name → volatility_30

        count = 0
        # First pass: compute indicators and collect volatility
        item_indicator_cache: dict[str, dict] = {}
        for name in all_names:
            try:
                indicators = await _compute_item_indicators(db, name, purchase_map, spread_map, days_held_map)
                if indicators:
                    item_indicator_cache[name] = indicators
                    if indicators.get("volatility_30") is not None:
                        vol_map[name] = indicators["volatility_30"]
            except Exception as e:
                logger.warning("indicator error for %s: %s", name, e)

        # Build peer volatility groups by category
        from app.api.routes.analysis import _classify_item
        peer_vol_groups: dict[str, list[float]] = {}
        for name, vol in vol_map.items():
            cat = _classify_item(name)
            peer_vol_groups.setdefault(cat, []).append(vol)

        # Second pass: compute scores with z-scores and write
        for name, indicators in item_indicator_cache.items():
            try:
                vol_z = None
                vol = indicators.get("volatility_30")
                if vol is not None:
                    cat = _classify_item(name)
                    peers = peer_vol_groups.get(cat, [])
                    if len(peers) >= 3:
                        mean = sum(peers) / len(peers)
                        std = math.sqrt(sum((v - mean) ** 2 for v in peers) / len(peers))
                        if std > 0:
                            vol_z = (vol - mean) / std

                pnl_pct = indicators.get("pnl_pct")
                target = target_map.get(name, 30.0)  # 默认 30%
                days_held = days_held_map.get(name, 0)
                h_count = holding_count_map.get(name, 0)
                conc = (item_market_value.get(name, 0) / total_portfolio_value * 100
                        if total_portfolio_value > 0 else None)
                mkt_cnt = market_count_map.get(name, 0)
                mkt_share = (h_count / mkt_cnt * 100) if mkt_cnt > 0 and h_count > 0 else None

                ann_ret = None
                buy_price = purchase_map.get(name)
                if buy_price and buy_price > 0 and days_held > 0:
                    current = indicators["current_price"]
                    if current > 0:
                        total_return = current / buy_price
                        if total_return > 0:
                            ann_ret = (total_return ** (365 / days_held) - 1) * 100

                sell = compute_sell_score(
                    pnl_pct=pnl_pct,
                    target_pnl_pct=target,
                    annualized_return=ann_ret,
                    days_held=days_held,
                    concentration_pct=conc,
                    holding_count=h_count,
                    volatility_zscore=vol_z,
                    rsi=indicators.get("rsi"),
                    bb_pos=indicators.get("bb_pos"),
                    momentum_30=indicators.get("momentum_30"),
                    market_share_pct=mkt_share,
                )
                opp = compute_opportunity_score(
                    rsi=indicators.get("rsi"),
                    bb_pos=indicators.get("bb_pos"),
                    momentum_7=indicators.get("momentum_7"),
                    spread_pct=indicators.get("spread"),
                    pnl_pct=pnl_pct,
                    target_pnl_pct=target,
                )

                values = {
                    "market_hash_name": name,
                    "signal_date": target_date,
                    "rsi_14": indicators.get("rsi"),
                    "bb_position": indicators.get("bb_pos"),
                    "bb_width": indicators.get("bb_width"),
                    "momentum_7": indicators.get("momentum_7"),
                    "momentum_30": indicators.get("momentum_30"),
                    "volatility_30": indicators.get("volatility_30"),
                    "ma_7": indicators.get("ma_7"),
                    "ma_30": indicators.get("ma_30"),
                    "ath_price": indicators.get("ath_price"),
                    "ath_pct": indicators.get("ath_pct"),
                    "spread_pct": indicators.get("spread"),
                    "annualized_return": ann_ret,
                    "holding_count": h_count if h_count > 0 else None,
                    "concentration_pct": round(conc, 2) if conc is not None else None,
                    "market_share_pct": round(mkt_share, 2) if mkt_share is not None else None,
                    "volatility_zscore": round(vol_z, 2) if vol_z is not None else None,
                    "sell_score": sell,
                    "opportunity_score": opp,
                }

                stmt = sqlite_insert(QuantSignal).values(values)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["market_hash_name", "signal_date"],
                    set_={k: getattr(stmt.excluded, k) for k in values if k not in ("market_hash_name", "signal_date")},
                )
                await db.execute(stmt)
                count += 1
            except Exception as e:
                logger.warning("signal score error for %s: %s", name, e)

        await db.commit()
        logger.info("compute_all_signals: wrote %d signals for %s", count, target_date)

        # Generate alerts
        await _generate_alerts(db, target_date, purchase_map)
        await db.commit()

        return count


async def _compute_item_indicators(
    db: AsyncSession,
    market_hash_name: str,
    purchase_map: dict[str, float],
    spread_map: dict[str, float],
    days_held_map: dict[str, int],
) -> Optional[dict]:
    """Compute raw technical indicators for a single item (no scoring)."""
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

    pnl_pct = None
    buy_price = purchase_map.get(market_hash_name)
    if buy_price and buy_price > 0:
        pnl_pct = (current_price - buy_price) / buy_price * 100

    return {
        "current_price": current_price,
        "rsi": rsi,
        "bb_pos": bb["pct_b"] if bb else None,
        "bb_width": bb["bandwidth"] if bb else None,
        "momentum_7": mom7,
        "momentum_30": mom30,
        "volatility_30": vol30,
        "ma_7": ma7,
        "ma_30": ma30,
        "ath_price": ath_price,
        "ath_pct": ath_pct,
        "spread": spread,
        "pnl_pct": pnl_pct,
    }


async def _calc_market_count_map(db: AsyncSession) -> dict[str, int]:
    """
    Get total market sell_count per item (sum across platforms).
    Used for market impact / market share calculation.
    """
    stmt = text("""
        SELECT ps.market_hash_name, SUM(ps.sell_count) AS total_sell
        FROM price_snapshot ps
        INNER JOIN (
            SELECT market_hash_name, platform, MAX(snapshot_minute) AS latest
            FROM price_snapshot
            GROUP BY market_hash_name, platform
        ) lt ON ps.market_hash_name = lt.market_hash_name
            AND ps.platform = lt.platform
            AND ps.snapshot_minute = lt.latest
        WHERE ps.sell_count IS NOT NULL AND ps.sell_count > 0
        GROUP BY ps.market_hash_name
    """)
    result = await db.execute(stmt)
    return {row[0]: int(row[1]) for row in result.fetchall()}


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
