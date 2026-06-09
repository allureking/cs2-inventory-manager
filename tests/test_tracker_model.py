"""
租赁效率/年化模型 + 解析工具 的纯函数测试（无 DB）。

覆盖：
  - _calc_annuals: VIP/非VIP 参数选取、净比例、0.7/0.3 综合权重、rented_value<=0 边界
  - 常量自洽：_SHORT/_LONG_DAYS 是否符合文档公式 期望周期 = R + (1-S)×CD,
              有效天数 = (365/周期)×R  —— S=0(传统) vs S=0.85(0CD), CD 边界
  - _parse_stats_desc: 标准摘要 / 缺字段 / 空串 / 千分位逗号 / 全角冒号
  - _safe_float / _safe_int: None / 合法 / 非法 / NaN 边界
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import math

import pytest

from app.services import tracker
from app.services.tracker import (
    _calc_annuals,
    _parse_stats_desc,
    _safe_float,
    _safe_int,
    _FEE_RATE,
    _VIP_FEE_RATE,
    _NET_RATE,
    _VIP_NET_RATE,
    _SHORT_DAYS,
    _LONG_DAYS,
    _VIP_SHORT_DAYS,
    _VIP_LONG_DAYS,
    _SHORT_WEIGHT,
    _LONG_WEIGHT,
)


def _effective_days(R, S, CD):
    """文档公式：期望周期 = R + (1-S)×CD；有效出租天数 = (365/周期)×R"""
    cycle = R + (1 - S) * CD
    return (365 / cycle) * R


# ── 常量自洽（验证常量确实由 expected_cycle 公式推导）───────────────────────


class TestModelConstantsMatchFormula:
    def test_non_vip_short_R8_CD8(self):
        # 传统模式 S=0: R=8, CD=8 → 周期16 → 365/16*8 = 182.5（精确）
        assert _SHORT_DAYS == pytest.approx(_effective_days(8, 0, 8), abs=0.05)
        assert _SHORT_DAYS == pytest.approx(182.5, abs=1e-9)

    def test_non_vip_long_R22_CD8(self):
        # 传统模式 S=0: R=22, CD=8 → 周期30 → 365/30*22 ≈ 267.67（常量取 267.7）
        assert _LONG_DAYS == pytest.approx(_effective_days(22, 0, 8), abs=0.05)

    def test_vip_short_R8_S085_CD8(self):
        # 0CD 模式 S=0.85: R=8, CD=8 → 周期=8+0.15*8=9.2 → 365/9.2*8 ≈ 317.39
        assert _VIP_SHORT_DAYS == pytest.approx(_effective_days(8, 0.85, 8), abs=0.05)

    def test_vip_long_R22_S085_CD8(self):
        # 0CD 模式 S=0.85: R=22, CD=8 → 周期=23.2 → 365/23.2*22 ≈ 346.12
        assert _VIP_LONG_DAYS == pytest.approx(_effective_days(22, 0.85, 8), abs=0.05)

    def test_vip_days_exceed_non_vip(self):
        # 0CD 转租把有效出租天数显著拉高
        assert _VIP_SHORT_DAYS > _SHORT_DAYS
        assert _VIP_LONG_DAYS > _LONG_DAYS

    def test_S1_perfect_sublet_zero_cooldown_effect(self):
        # S=1（转租 100% 成功）→ 冷却完全不计 → 周期=R → 有效天数=365
        assert _effective_days(8, 1.0, 8) == pytest.approx(365.0)
        assert _effective_days(22, 1.0, 99) == pytest.approx(365.0)

    def test_CD0_zero_cooldown(self):
        # CD=0（无冷却）→ 周期=R → 有效天数=365，与 S 无关
        assert _effective_days(8, 0.0, 0) == pytest.approx(365.0)
        assert _effective_days(8, 0.5, 0) == pytest.approx(365.0)

    def test_fee_and_net_rates_consistent(self):
        # 服务费 + 净比例 = 1
        assert _FEE_RATE + _NET_RATE == pytest.approx(1.0)
        assert _VIP_FEE_RATE + _VIP_NET_RATE == pytest.approx(1.0)
        # VIP 服务费更低
        assert _VIP_FEE_RATE < _FEE_RATE

    def test_weights_sum_to_one(self):
        assert _SHORT_WEIGHT + _LONG_WEIGHT == pytest.approx(1.0)


# ── _calc_annuals ──────────────────────────────────────────────────────────


class TestCalcAnnuals:
    def test_zero_rented_value_returns_none(self):
        r = _calc_annuals(daily_income=100.0, rented_value=0.0)
        assert r == {"short": None, "long": None, "combined": None}

    def test_negative_rented_value_returns_none(self):
        r = _calc_annuals(daily_income=100.0, rented_value=-5.0)
        assert r == {"short": None, "long": None, "combined": None}

    def test_none_rented_value_returns_none(self):
        r = _calc_annuals(daily_income=100.0, rented_value=None)
        assert r == {"short": None, "long": None, "combined": None}

    def test_vip_formula(self):
        income, value = 1000.0, 1_000_000.0
        r = _calc_annuals(income, value, is_vip=True)
        net = income * _VIP_NET_RATE
        exp_short = round(net * _VIP_SHORT_DAYS / value, 8)
        exp_long = round(net * _VIP_LONG_DAYS / value, 8)
        exp_combined = round(exp_short * _SHORT_WEIGHT + exp_long * _LONG_WEIGHT, 8)
        assert r["short"] == pytest.approx(exp_short)
        assert r["long"] == pytest.approx(exp_long)
        assert r["combined"] == pytest.approx(exp_combined)

    def test_non_vip_formula(self):
        income, value = 1000.0, 1_000_000.0
        r = _calc_annuals(income, value, is_vip=False)
        net = income * _NET_RATE
        exp_short = round(net * _SHORT_DAYS / value, 8)
        assert r["short"] == pytest.approx(exp_short)

    def test_vip_higher_than_non_vip(self):
        # 同样收入/价值，VIP（低费率+高有效天数）年化更高
        income, value = 1000.0, 1_000_000.0
        vip = _calc_annuals(income, value, is_vip=True)
        non = _calc_annuals(income, value, is_vip=False)
        assert vip["short"] > non["short"]
        assert vip["combined"] > non["combined"]

    def test_combined_is_weighted_blend(self):
        r = _calc_annuals(500.0, 800_000.0, is_vip=True)
        # combined 必落在 short/long 之间
        lo, hi = sorted([r["short"], r["long"]])
        assert lo <= r["combined"] <= hi

    def test_default_is_vip_true(self):
        # 默认 is_vip=True
        assert _calc_annuals(1000.0, 1e6) == _calc_annuals(1000.0, 1e6, is_vip=True)

    def test_zero_income_yields_zero(self):
        r = _calc_annuals(0.0, 1e6, is_vip=True)
        assert r["short"] == 0.0 and r["long"] == 0.0 and r["combined"] == 0.0


# ── _parse_stats_desc ──────────────────────────────────────────────────────


class TestParseStatsDesc:
    def test_standard(self):
        s = "件数：3,320｜价值：¥3612634.69｜总租金：¥2466.82/天"
        r = _parse_stats_desc(s)
        assert r == {"count": 3320, "value": 3612634.69, "income": 2466.82}

    def test_empty_string(self):
        assert _parse_stats_desc("") == {"count": 0, "value": 0.0, "income": 0.0}

    def test_none(self):
        assert _parse_stats_desc(None) == {"count": 0, "value": 0.0, "income": 0.0}

    def test_partial_only_count(self):
        r = _parse_stats_desc("件数：12")
        assert r["count"] == 12 and r["value"] == 0.0 and r["income"] == 0.0

    def test_half_width_colon(self):
        r = _parse_stats_desc("件数: 5 | 价值: ¥100.5 | 总租金: ¥2.5/天")
        assert r["count"] == 5 and r["value"] == 100.5 and r["income"] == 2.5

    def test_thousands_separator(self):
        r = _parse_stats_desc("件数：1,234,567｜价值：¥9,999,999.99｜总租金：¥1,000.00")
        assert r["count"] == 1234567
        assert r["value"] == 9999999.99
        assert r["income"] == 1000.0

    def test_garbage_text(self):
        assert _parse_stats_desc("no numbers here") == {"count": 0, "value": 0.0, "income": 0.0}


# ── _safe_float / _safe_int ────────────────────────────────────────────────


class TestSafeConversions:
    def test_safe_float_none(self):
        assert _safe_float(None) is None

    def test_safe_float_valid(self):
        assert _safe_float("3.14") == 3.14
        assert _safe_float(2) == 2.0

    def test_safe_float_invalid(self):
        assert _safe_float("abc") is None
        assert _safe_float("") is None

    def test_safe_float_nan(self):
        assert _safe_float(float("nan")) is None

    def test_safe_int_none(self):
        assert _safe_int(None) is None

    def test_safe_int_from_float_string(self):
        assert _safe_int("3.0") == 3
        assert _safe_int(7.9) == 7  # int(float()) 截断

    def test_safe_int_invalid(self):
        assert _safe_int("xyz") is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
