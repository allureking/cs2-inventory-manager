"""
核心定价算法单元测试

覆盖 calc_sell_price / calc_lease_price 的关键场景：
  - 正常定价 & 低一分策略
  - outlier 过滤
  - 止盈率保护
  - 浮点精度边界
  - 空列表 / 单价格
  - 租赁价格计算
"""

import sys
from pathlib import Path

# 让 tests/ 可以直接 import app.*
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.youpin_listing import calc_sell_price, calc_lease_price


def _market(prices: list[float]) -> list[dict]:
    """构造模拟市场挂单列表"""
    return [{"price": p} for p in prices]


def _lease_market(units, long_units=None, deposits=None):
    """构造模拟租赁挂单列表"""
    result = []
    for i, u in enumerate(units):
        item = {"leaseUnitPrice": u}
        if long_units and i < len(long_units):
            item["longLeaseUnitPrice"] = long_units[i]
        if deposits and i < len(deposits):
            item["leaseDeposit"] = deposits[i]
        result.append(item)
    return result


# ── calc_sell_price ──────────────────────────────────────────────────


class TestCalcSellPrice:
    def test_empty_list_returns_none(self):
        assert calc_sell_price([]) is None

    def test_single_price(self):
        # 单价格：直接取该价格 - 0.01（低一分）
        result = calc_sell_price(_market([100.0]))
        assert result == 99.99

    def test_single_price_no_undercut(self):
        result = calc_sell_price(_market([100.0]), use_undercut=False)
        assert result == 100.0

    def test_close_prices_follow_lowest(self):
        # 前两档差距 < 5%，跟最低价 - 0.01
        result = calc_sell_price(_market([100.0, 103.0, 105.0]))
        assert result == 99.99

    def test_gap_prices_take_second(self):
        # 差距 >= 5%，取第二低 - 0.01
        result = calc_sell_price(_market([50.0, 100.0, 105.0]))
        # 50 < 100 * 0.5 → outlier, 被过滤 → prices=[100, 105]
        # 105 < 100 * 1.05 → 跟最低 100 → 100 - 0.01 = 99.99
        assert result == 99.99

    def test_outlier_filter(self):
        # 最低价是异常挂单（< 第二价 * 0.5），过滤掉
        result = calc_sell_price(_market([10.0, 100.0, 102.0, 105.0]))
        # 10 < 100 * 0.5 → 过滤 → prices=[100, 102, 105]
        # 102 < 100 * 1.05 → 跟最低 100 → 99.99
        assert result == 99.99

    def test_take_profit_floor(self):
        # 止盈率保护：buy_price=80, ratio=0.3 → floor=104
        result = calc_sell_price(
            _market([100.0, 102.0, 105.0]),
            buy_price=80.0,
            take_profit_ratio=0.3,
        )
        # 正常算出 99.99，但 floor = 80 * 1.3 = 104 → 取 max(99.99, 104) = 104
        # 低一分：104 - 0.01 = 103.99
        assert result == 103.99

    def test_take_profit_below_market(self):
        # 止盈率保护不抬价（floor < 市价时不影响）
        result = calc_sell_price(
            _market([100.0, 102.0, 105.0]),
            buy_price=50.0,
            take_profit_ratio=0.1,
        )
        # floor = 50 * 1.1 = 55, market price = 99.99, max(99.99, 55) = 99.99
        assert result == 99.99

    def test_min_price_protection(self):
        # 价格不能低于 min_price
        # 0.02 时，低一分条件 0.02 > 0.01+0.01=0.02 为 false，不减价
        result = calc_sell_price(_market([0.02]), min_price=0.01)
        assert result == 0.02
        # 0.03 时，0.03 > 0.02 为 true → 0.03 - 0.01 = 0.02
        result2 = calc_sell_price(_market([0.03]), min_price=0.01)
        assert result2 == 0.02

    def test_float_precision(self):
        # 浮点精度测试：确保不会出现 xx.xx0000001 之类的问题
        result = calc_sell_price(_market([3200.01, 3200.02, 3200.05]))
        assert result == 3200.0
        assert isinstance(result, float)
        # 确认结果精确到分
        assert result == round(result, 2)

    def test_float_precision_take_profit(self):
        # 止盈率涉及乘法，更容易出精度问题
        result = calc_sell_price(
            _market([200.0, 202.0, 205.0]),
            buy_price=123.45,
            take_profit_ratio=0.15,
        )
        # floor = 123.45 * 1.15 = 141.9675 → round → 141.97
        # market = 199.99, max(199.99, 141.97) = 199.99
        assert result == 199.99
        assert result == round(result, 2)

    def test_only_invalid_prices(self):
        # 列表中无有效价格
        assert calc_sell_price([{"price": "abc"}, {"price": None}]) is None

    def test_mixed_key_formats(self):
        # 不同 key 格式混合
        market = [{"Price": 100.0}, {"sellPrice": 102.0}, {"price": 105.0}]
        result = calc_sell_price(market)
        assert result is not None


# ── calc_lease_price ─────────────────────────────────────────────────


class TestCalcLeasePrice:
    def test_empty_list_returns_none(self):
        assert calc_lease_price([]) is None

    def test_basic_lease(self):
        result = calc_lease_price(
            _lease_market([1.0, 1.2, 1.1], [0.8, 0.9, 0.85], [50.0, 55.0, 52.0])
        )
        assert result is not None
        assert "lease_unit" in result
        assert "long_lease_unit" in result
        assert "deposit" in result
        # 所有值应该是 2 位小数
        assert result["lease_unit"] == round(result["lease_unit"], 2)
        assert result["long_lease_unit"] == round(result["long_lease_unit"], 2)
        assert result["deposit"] == round(result["deposit"], 2)

    def test_long_unit_never_exceeds_short(self):
        result = calc_lease_price(
            _lease_market([1.0, 1.0, 1.0], [2.0, 2.0, 2.0], [50.0])
        )
        assert result["long_lease_unit"] <= result["lease_unit"]

    def test_no_long_lease_data(self):
        result = calc_lease_price(_lease_market([1.0, 1.2]))
        assert result is not None
        assert result["long_lease_unit"] <= result["lease_unit"]

    def test_fix_lease_ratio(self):
        result = calc_lease_price(
            _lease_market([0.5, 0.6]),
            sell_price=1000.0,
            fix_lease_ratio=0.01,
        )
        # ratio_unit = 1000 * 0.01 = 10.0，远大于市场均价 0.55
        assert result["lease_unit"] >= 10.0

    def test_deposit_fallback_to_sell_price(self):
        # 无押金数据时，按售价 30% 计算
        result = calc_lease_price(
            _lease_market([1.0, 1.2]),
            sell_price=500.0,
        )
        assert result["deposit"] == 150.0  # 500 * 0.3


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
