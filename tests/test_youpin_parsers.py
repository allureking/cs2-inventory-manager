"""
悠悠记录解析工具的纯函数边界测试（无 DB、无网络）。

_parse_price  : totalAmount(分) / 100；缺失/非数 → None
_parse_qty    : commodityNum>count>quantity>goodsNum 取首个有效正整数；否则 1
_parse_date   : createOrderTime>finishOrderTime>payTime 毫秒时间戳 → YYYY-MM-DD(UTC)；否则 None
_parse_hash_name : productDetail.commodityHashName 或 None
_parse_abrade : productDetail.abrade / commodityAbrade，float>0 否则 None
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from app.services.youpin import (
    _parse_price,
    _parse_qty,
    _parse_date,
    _parse_hash_name,
    _parse_abrade,
)


# ── _parse_price ───────────────────────────────────────────────────────────


class TestParsePrice:
    def test_cents_to_yuan(self):
        assert _parse_price({"totalAmount": 12345}) == 123.45

    def test_string_amount(self):
        assert _parse_price({"totalAmount": "10000"}) == 100.0

    def test_zero(self):
        assert _parse_price({"totalAmount": 0}) == 0.0

    def test_missing(self):
        assert _parse_price({}) is None

    def test_non_numeric(self):
        assert _parse_price({"totalAmount": "abc"}) is None

    def test_none_value(self):
        assert _parse_price({"totalAmount": None}) is None


# ── _parse_qty ─────────────────────────────────────────────────────────────


class TestParseQty:
    def test_commodity_num(self):
        assert _parse_qty({"commodityNum": 3}) == 3

    def test_priority_commodity_over_count(self):
        assert _parse_qty({"commodityNum": 2, "count": 9}) == 2

    def test_fallback_to_count(self):
        assert _parse_qty({"count": 5}) == 5

    def test_default_one_when_missing(self):
        assert _parse_qty({}) == 1

    def test_zero_falls_through_to_default(self):
        # 0 不是正整数 → 继续找 → 都没有 → 1
        assert _parse_qty({"commodityNum": 0}) == 1

    def test_negative_falls_through(self):
        assert _parse_qty({"commodityNum": -3}) == 1

    def test_string_int(self):
        assert _parse_qty({"commodityNum": "7"}) == 7

    def test_non_int_falls_through(self):
        assert _parse_qty({"commodityNum": "x", "count": 4}) == 4


# ── _parse_date ────────────────────────────────────────────────────────────


class TestParseDate:
    def test_create_order_time_ms(self):
        # 1700000000000 ms = 2023-11-14 22:13:20 UTC
        assert _parse_date({"createOrderTime": 1700000000000}) == "2023-11-14"

    def test_priority_order(self):
        # createOrderTime 优先于 payTime
        r = {"createOrderTime": 1700000000000, "payTime": 1600000000000}
        assert _parse_date(r) == "2023-11-14"

    def test_fallback_pay_time(self):
        # 仅 payTime → 1600000000000 ms = 2020-09-13 UTC
        assert _parse_date({"payTime": 1600000000000}) == "2020-09-13"

    def test_missing(self):
        assert _parse_date({}) is None

    def test_invalid(self):
        assert _parse_date({"createOrderTime": "not-a-number"}) is None

    def test_zero_skipped(self):
        # 0 为 falsy → 跳过 → None
        assert _parse_date({"createOrderTime": 0}) is None


# ── _parse_hash_name ───────────────────────────────────────────────────────


class TestParseHashName:
    def test_from_product_detail(self):
        r = {"productDetail": {"commodityHashName": "AK-47 | Redline (Field-Tested)"}}
        assert _parse_hash_name(r) == "AK-47 | Redline (Field-Tested)"

    def test_missing_product_detail(self):
        assert _parse_hash_name({}) is None

    def test_empty_hash_name(self):
        assert _parse_hash_name({"productDetail": {"commodityHashName": ""}}) is None

    def test_product_detail_none(self):
        assert _parse_hash_name({"productDetail": None}) is None


# ── _parse_abrade ──────────────────────────────────────────────────────────


class TestParseAbrade:
    def test_valid_abrade(self):
        assert _parse_abrade({"productDetail": {"abrade": "0.1234"}}) == pytest.approx(0.1234)

    def test_zero_is_none(self):
        assert _parse_abrade({"productDetail": {"abrade": 0}}) is None

    def test_negative_is_none(self):
        assert _parse_abrade({"productDetail": {"abrade": -0.5}}) is None

    def test_fallback_commodity_abrade(self):
        assert _parse_abrade({"productDetail": {"commodityAbrade": "0.5"}}) == pytest.approx(0.5)

    def test_missing(self):
        assert _parse_abrade({"productDetail": {}}) is None

    def test_non_numeric(self):
        assert _parse_abrade({"productDetail": {"abrade": "n/a"}}) is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
