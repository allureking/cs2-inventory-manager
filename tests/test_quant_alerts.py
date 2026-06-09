"""
quant_engine 告警规则 / 分类 / 指标聚合（纯函数 + 真实 YAML 配置,无 DB·无网络）。

  - _classify_item：刀/手套/贴纸/箱子/步枪/狙击/手枪/其他
  - _load_alert_rules：从 config/alert_rules.yaml 载入 7 条规则 + category_overrides
  - _get_rules_for_item：按类目覆盖阈值（knife profit_50=60 vs rifle=50）
  - _compute_item_indicators_from_cache：数据不足→None、ath/ pnl_pct 计算
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from app.api.routes.analysis import _classify_item
from app.services.quant_engine import (
    _load_alert_rules,
    _get_rules_for_item,
    _compute_item_indicators_from_cache,
)


def _threshold(rules, rtype):
    for t in rules:
        if t[0] == rtype:
            return t[4]
    return None


# ── _classify_item ─────────────────────────────────────────────────────────


class TestClassifyItem:
    def test_knife(self):
        assert _classify_item("★ Karambit | Doppler (Factory New)") == "knife"

    def test_glove(self):
        assert _classify_item("★ Sport Gloves | Amphibious (Field-Tested)") == "glove"
        assert _classify_item("★ Hand Wraps | Cobalt (Field-Tested)") == "glove"

    def test_sticker(self):
        assert _classify_item("Sticker | Natus Vincere") == "sticker"

    def test_case(self):
        assert _classify_item("Kilowatt Case") == "case"

    def test_rifle(self):
        assert _classify_item("AK-47 | Redline (Field-Tested)") == "rifle"
        assert _classify_item("M4A1-S | Printstream (Minimal Wear)") == "rifle"

    def test_sniper(self):
        assert _classify_item("AWP | Asiimov (Field-Tested)") == "sniper"

    def test_pistol(self):
        assert _classify_item("Desert Eagle | Blaze (Factory New)") == "pistol"

    def test_other(self):
        assert _classify_item("Some Unknown Thing") == "other"


# ── _load_alert_rules ──────────────────────────────────────────────────────


class TestLoadAlertRules:
    def test_loads_rules_and_overrides(self):
        rules, overrides = _load_alert_rules()
        assert len(rules) >= 1
        # 每条规则是 6 元组 (type, severity, field, op, threshold, title)
        for t in rules:
            assert len(t) == 6
            assert isinstance(t[4], float)
        # YAML 含 knife/glove/sticker 覆盖
        assert "knife" in overrides
        assert "sticker" in overrides

    def test_has_profit_rules(self):
        rules, _ = _load_alert_rules()
        types = {t[0] for t in rules}
        assert "profit_50" in types and "profit_100" in types


# ── _get_rules_for_item（类目阈值覆盖）───────────────────────────────────────


class TestGetRulesForItem:
    def test_knife_override_raises_threshold(self):
        knife = _get_rules_for_item("★ Karambit | Doppler (Factory New)")
        # knife profit_50 阈值被覆盖为 60
        assert _threshold(knife, "profit_50") == pytest.approx(60.0)

    def test_rifle_uses_base_threshold(self):
        rifle = _get_rules_for_item("AK-47 | Redline (Field-Tested)")
        # rifle 无覆盖 → 全局默认 50
        assert _threshold(rifle, "profit_50") == pytest.approx(50.0)

    def test_sticker_override(self):
        sticker = _get_rules_for_item("Sticker | Natus Vincere")
        assert _threshold(sticker, "profit_50") == pytest.approx(30.0)

    def test_returns_all_rule_types(self):
        # 覆盖只改阈值,不删规则
        base, _ = _load_alert_rules()
        knife = _get_rules_for_item("★ Karambit | Doppler (Factory New)")
        assert len(knife) == len(base)


# ── _compute_item_indicators_from_cache ────────────────────────────────────


class TestComputeIndicatorsFromCache:
    def test_insufficient_closes(self):
        assert _compute_item_indicators_from_cache("A", [1.0, 2.0], {}, {}, {}) is None

    def test_basic_fields(self):
        closes = [float(i) for i in range(1, 41)]  # 1..40，最后 40 最高
        r = _compute_item_indicators_from_cache("A", closes, {"A": 20.0}, {"A": 3.3}, {})
        assert r["current_price"] == 40.0
        assert r["ath_price"] == 40.0
        assert r["ath_pct"] == pytest.approx(100.0)   # current==ath
        assert r["spread"] == 3.3
        # pnl_pct = (40-20)/20*100 = 100
        assert r["pnl_pct"] == pytest.approx(100.0)

    def test_no_purchase_price_pnl_none(self):
        closes = [10.0, 11.0, 12.0]
        r = _compute_item_indicators_from_cache("A", closes, {}, {}, {})
        assert r["pnl_pct"] is None

    def test_zero_purchase_price_pnl_none(self):
        closes = [10.0, 11.0, 12.0]
        r = _compute_item_indicators_from_cache("A", closes, {"A": 0.0}, {}, {})
        assert r["pnl_pct"] is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
