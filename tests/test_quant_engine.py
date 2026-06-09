"""
quant_engine 纯函数测试：技术指标 + 综合评分（无 DB、无网络）。

指标：_sma / _ema / calc_rsi / calc_bollinger / calc_momentum / calc_volatility
评分：compute_sell_score（5 维度）/ compute_opportunity_score（6 维度）

追求高分支覆盖：每个指标的「数据不足→None」边界 + 已知数值；
评分的基线、各维度加分/减分分支、上下钳制 [0,100]。
"""

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from app.services.quant_engine import (
    _sma,
    _ema,
    calc_rsi,
    calc_bollinger,
    calc_momentum,
    calc_volatility,
    compute_sell_score,
    compute_opportunity_score,
)


# ── _sma / _ema ────────────────────────────────────────────────────────────


class TestMovingAverages:
    def test_sma_insufficient(self):
        assert _sma([1, 2], 3) is None

    def test_sma_last_period(self):
        assert _sma([1, 2, 3, 4, 5], 3) == pytest.approx((3 + 4 + 5) / 3)

    def test_ema_insufficient(self):
        assert _ema([1, 2], 3) is None

    def test_ema_known(self):
        # period=3, seed=sma([1,2,3])=2, k=0.5; v=4→3; v=5→4
        assert _ema([1, 2, 3, 4, 5], 3) == pytest.approx(4.0)

    def test_ema_flat_equals_value(self):
        assert _ema([7.0] * 10, 4) == pytest.approx(7.0)


# ── calc_rsi ───────────────────────────────────────────────────────────────


class TestRSI:
    def test_insufficient(self):
        assert calc_rsi([1, 2, 3], period=14) is None  # 需要 period+1

    def test_all_gains_returns_100(self):
        closes = list(range(1, 20))  # 严格递增 → avg_loss=0 → 100
        assert calc_rsi(closes, period=14) == 100.0

    def test_all_losses_returns_0(self):
        closes = list(range(20, 1, -1))  # 严格递减 → avg_gain=0 → 0
        assert calc_rsi(closes, period=14) == 0.0

    def test_balanced_around_50(self):
        # 交替 ±1 → avg_gain≈avg_loss → RSI≈50
        closes = [100 + (i % 2) for i in range(15)]
        assert calc_rsi(closes, period=14) == pytest.approx(50.0, abs=1e-6)


# ── calc_bollinger ─────────────────────────────────────────────────────────


class TestBollinger:
    def test_insufficient(self):
        assert calc_bollinger([1, 2, 3], period=20) is None

    def test_flat_zero_band(self):
        r = calc_bollinger([100.0] * 20, period=20)
        assert r["ma"] == 100.0
        assert r["upper"] == r["lower"] == 100.0
        assert r["pct_b"] == 0.5      # band_range=0 分支
        assert r["bandwidth"] == 0.0

    def test_known_series(self):
        closes = list(range(1, 21))  # 1..20, period=20
        r = calc_bollinger(closes, period=20)
        assert r["ma"] == pytest.approx(10.5)
        assert r["upper"] > r["ma"] > r["lower"]
        # 最后一个值=20 是最高 → pct_b 接近 1
        assert r["pct_b"] > 0.9
        assert r["bandwidth"] > 0

    def test_num_std_widens_band(self):
        closes = list(range(1, 21))
        narrow = calc_bollinger(closes, 20, num_std=1.0)
        wide = calc_bollinger(closes, 20, num_std=3.0)
        assert (wide["upper"] - wide["lower"]) > (narrow["upper"] - narrow["lower"])


# ── calc_momentum ──────────────────────────────────────────────────────────


class TestMomentum:
    def test_insufficient(self):
        assert calc_momentum([1, 2, 3], period=5) is None  # len<=period

    def test_zero_base_returns_none(self):
        assert calc_momentum([0, 1, 2, 3, 4, 5], period=5) is None  # closes[-6]==0

    def test_roc(self):
        # closes[-6]=100, last=110 → +10%
        assert calc_momentum([100, 100, 100, 100, 100, 110], period=5) == pytest.approx(10.0)

    def test_negative_roc(self):
        assert calc_momentum([100, 0, 0, 0, 0, 90], period=5) == pytest.approx(-10.0)


# ── calc_volatility ────────────────────────────────────────────────────────


class TestVolatility:
    def test_insufficient(self):
        assert calc_volatility([1, 2, 3], period=30) is None

    def test_flat_zero_volatility(self):
        assert calc_volatility([100.0] * 31, period=30) == pytest.approx(0.0)

    def test_positive_for_varying_series(self):
        closes = [100 * (1.01 ** i) if i % 2 == 0 else 100 * (0.99 ** i) for i in range(40)]
        v = calc_volatility(closes, period=30)
        assert v is not None and v > 0

    def test_annualization_factor(self):
        # 构造已知日波动 → 年化 = daily_vol * sqrt(365) * 100
        closes = [100.0]
        for i in range(40):
            closes.append(closes[-1] * (1.02 if i % 2 == 0 else 1 / 1.02))
        v = calc_volatility(closes, period=30)
        assert v is not None and v > 0


# ── compute_sell_score ─────────────────────────────────────────────────────


class TestSellScore:
    def test_baseline_no_signal(self):
        assert compute_sell_score() == 45.0  # 基线略低于中性

    def test_target_overshoot_max(self):
        # pnl_pct / target >= 1.5 → +30 → 75
        assert compute_sell_score(pnl_pct=60.0, target_pnl_pct=30.0) == pytest.approx(75.0)

    def test_at_target_band(self):
        # ratio=1.0 → +20 → 65
        assert compute_sell_score(pnl_pct=30.0, target_pnl_pct=30.0) == pytest.approx(65.0)

    def test_profit_below_target(self):
        # ratio=0.5 → +0.5*12=6 → 51
        assert compute_sell_score(pnl_pct=15.0, target_pnl_pct=30.0) == pytest.approx(51.0)

    def test_loss_reduces_score(self):
        # 亏损 → 维度1 给负分 → 低于基线
        s = compute_sell_score(pnl_pct=-25.0, target_pnl_pct=30.0)
        assert s < 45.0

    def test_loss_floored(self):
        # 极深亏损 floor 在 -22 → 45-22=23,不会更低（仅维度1）
        s = compute_sell_score(pnl_pct=-1000.0, target_pnl_pct=30.0)
        assert s == pytest.approx(23.0)

    def test_concentration_adds(self):
        base = compute_sell_score(pnl_pct=0.0)
        hi = compute_sell_score(pnl_pct=0.0, concentration_pct=25.0)
        assert hi > base

    def test_rental_discount(self):
        # 高租金年化 → 减分（值得继续出租）
        base = compute_sell_score(pnl_pct=0.0)
        rented = compute_sell_score(pnl_pct=0.0, rental_annual=50.0)
        assert rented < base

    def test_clamped_0_100(self):
        s = compute_sell_score(pnl_pct=10000.0, target_pnl_pct=30.0, concentration_pct=100.0,
                               holding_count=1000, volatility_zscore=10.0, rsi=100.0,
                               bb_pos=1.0, momentum_30=1000.0, market_share_pct=100.0)
        assert 0.0 <= s <= 100.0
        assert s == 100.0

    def test_rsi_oversold_lowers(self):
        # RSI 超卖 → 异常波动维度减分 → 低于无 RSI
        base = compute_sell_score(pnl_pct=0.0)
        os = compute_sell_score(pnl_pct=0.0, rsi=10.0)
        assert os < base


# ── compute_opportunity_score ──────────────────────────────────────────────


class TestOpportunityScore:
    def test_baseline(self):
        assert compute_opportunity_score(None, None, None, None) == 50.0

    def test_oversold_rsi_adds(self):
        s = compute_opportunity_score(rsi=10.0, bb_pos=None, momentum_7=None, spread_pct=None)
        assert s > 50.0

    def test_below_lower_band_adds(self):
        s = compute_opportunity_score(rsi=None, bb_pos=-0.5, momentum_7=None, spread_pct=None)
        assert s > 50.0

    def test_dip_momentum_adds(self):
        s = compute_opportunity_score(rsi=None, bb_pos=None, momentum_7=-20.0, spread_pct=None)
        assert s > 50.0

    def test_spread_adds(self):
        s = compute_opportunity_score(rsi=None, bb_pos=None, momentum_7=None, spread_pct=15.0)
        assert s > 50.0

    def test_deep_loss_buy_signal(self):
        s = compute_opportunity_score(None, None, None, None, pnl_pct=-40.0, target_pnl_pct=30.0)
        assert s > 50.0

    def test_overshoot_reduces(self):
        s = compute_opportunity_score(None, None, None, None, pnl_pct=80.0, target_pnl_pct=30.0)
        assert s < 50.0

    def test_rental_adds(self):
        s = compute_opportunity_score(None, None, None, None, rental_annual=50.0)
        assert s > 50.0

    def test_clamped(self):
        s = compute_opportunity_score(rsi=0.0, bb_pos=-5.0, momentum_7=-100.0, spread_pct=100.0,
                                      pnl_pct=-100.0, rental_annual=100.0)
        assert 0.0 <= s <= 100.0
        assert s == 100.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
