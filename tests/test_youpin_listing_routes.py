"""
youpin / listing 路由的「无网络」部分：
  - youpin 状态读取端点 auth_state / market_refresh_status / import_status（读模块状态,不发请求）
  - listing 快照只读端点 list_snapshots / get_snapshot（DB-only,用全局 AsyncSessionLocal）

这些路由函数无 db 参数（用全局 session）或无 IO,直接 await 调用最干净。
其余 youpin/listing 端点是悠悠外部动作（登录/上架/改价/下架/同步），见 REPORT §2。
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from app.api.routes import youpin as youpin_route
from app.api.routes import listing as listing_route
from app.models.db_models import ListingSnapshot, ListingSnapshotItem
from tests.conftest import memory_db


def _run(coro):
    return asyncio.run(coro)


# ── youpin 状态端点（无网络）────────────────────────────────────────────────


def test_youpin_auth_state_no_token():
    async def body():
        d = await youpin_route.auth_state()
        # 测试环境无 token
        assert d["has_token"] is False
        assert d["token_source"] == "none"
    _run(body())


def test_youpin_market_status_shape():
    async def body():
        d = await youpin_route.market_refresh_status()
        assert "status" in d and "progress" in d
    _run(body())


def test_youpin_import_status_shape():
    async def body():
        d = await youpin_route.import_status()
        assert isinstance(d, dict) and "status" in d
    _run(body())


# ── listing 快照只读（DB）────────────────────────────────────────────────────


def test_listing_snapshots_empty():
    async def body():
        async with memory_db() as Session:
            orig = listing_route.AsyncSessionLocal
            listing_route.AsyncSessionLocal = Session
            try:
                assert await listing_route.list_snapshots() == []
            finally:
                listing_route.AsyncSessionLocal = orig
    _run(body())


def test_listing_snapshots_list_and_detail():
    async def body():
        async with memory_db() as Session:
            orig = listing_route.AsyncSessionLocal
            listing_route.AsyncSessionLocal = Session
            try:
                async with Session() as db:
                    snap = ListingSnapshot(name="出售货架快照", shelf_type="sell", item_count=2, total_value=300.0)
                    db.add(snap)
                    await db.flush()
                    db.add_all([
                        ListingSnapshotItem(snapshot_id=snap.id, commodity_hash_name="A", name="A", sell_price=200.0),
                        ListingSnapshotItem(snapshot_id=snap.id, commodity_hash_name="B", name="B", sell_price=100.0),
                    ])
                    await db.commit()
                    sid = snap.id

                lst = await listing_route.list_snapshots()
                assert len(lst) == 1 and lst[0]["name"] == "出售货架快照"

                detail = await listing_route.get_snapshot(sid)
                assert detail["item_count"] == 2
                assert len(detail["items"]) == 2
                # items 按 sell_price 降序
                assert detail["items"][0]["sell_price"] == 200.0
            finally:
                listing_route.AsyncSessionLocal = orig
    _run(body())


def test_listing_snapshot_detail_404():
    async def body():
        from fastapi import HTTPException
        async with memory_db() as Session:
            orig = listing_route.AsyncSessionLocal
            listing_route.AsyncSessionLocal = Session
            try:
                with pytest.raises(HTTPException) as ei:
                    await listing_route.get_snapshot(99999)
                assert ei.value.status_code == 404
            finally:
                listing_route.AsyncSessionLocal = orig
    _run(body())


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


# ── 上架/改价入参约束（v0.13.3）─────────────────────────────────────────────
#
# 这一组端点会把价格**直接推到悠悠线上**（真金白银），此前全部是裸 float/int：
# 0、负数、NaN、1e308 都能原样穿到悠悠。下面只用纯 Pydantic 校验，不发任何请求。


import pytest as _pytest
from pydantic import ValidationError

from app.api.routes.listing import (
    BatchSmartRepriceRequest,
    BothRequest,
    LeaseRequest,
    RepriceRequest,
    SellRequest,
    SmartListRequest,
)

NAN = float("nan")
INF = float("inf")


class TestListingInputGuards:
    @_pytest.mark.parametrize("price", [0, -1, -0.01, NAN, INF, 1e308, 3_000_000])
    def test_sell_price_rejected(self, price):
        with _pytest.raises(ValidationError):
            SellRequest(asset_id="a1", price=price)

    def test_sell_price_accepted(self):
        assert SellRequest(asset_id="a1", price=1234.56).price == 1234.56

    def test_empty_asset_id_rejected(self):
        with _pytest.raises(ValidationError):
            SellRequest(asset_id="", price=10.0)

    @_pytest.mark.parametrize("kw", [
        {"lease_unit": 0}, {"lease_unit": -5}, {"lease_unit": NAN},
        {"long_lease_unit": 0}, {"deposit": -1},
        {"max_days": 0}, {"max_days": 91}, {"max_days": -30},
    ])
    def test_lease_bounds(self, kw):
        base = dict(asset_id="a1", lease_unit=3.0, long_lease_unit=2.5, deposit=100.0)
        base.update(kw)
        with _pytest.raises(ValidationError):
            LeaseRequest(**base)

    def test_lease_accepted(self):
        r = LeaseRequest(asset_id="a1", lease_unit=3.0, long_lease_unit=2.5,
                         deposit=100.0, max_days=90)
        assert r.max_days == 90 and r.deposit == 100.0

    def test_both_sell_price_bounds(self):
        base = dict(asset_id="a1", sell_price=100.0, lease_unit=3.0,
                    long_lease_unit=2.5, deposit=100.0)
        assert BothRequest(**base).sell_price == 100.0
        with _pytest.raises(ValidationError):
            BothRequest(**{**base, "sell_price": 0})

    @_pytest.mark.parametrize("kw", [
        {"commodity_id": 0}, {"commodity_id": -1},
        {"sell_price": 0}, {"sell_price": -10}, {"sell_price": NAN},
        {"lease_unit": 0}, {"deposit": -1},
    ])
    def test_reprice_bounds(self, kw):
        with _pytest.raises(ValidationError):
            RepriceRequest(**{"commodity_id": 123, **kw})

    def test_reprice_none_fields_still_allowed(self):
        """改价允许只传部分字段（None = 不改），约束不能把 None 也挡掉。"""
        r = RepriceRequest(commodity_id=123, sell_price=50.0)
        assert r.lease_unit is None and r.deposit is None

    def test_smart_mode_is_enumerated(self):
        assert SmartListRequest(asset_id="a", template_id=1, mode="both").mode == "both"
        with _pytest.raises(ValidationError):
            SmartListRequest(asset_id="a", template_id=1, mode="selll")

    @_pytest.mark.parametrize("kw", [
        {"template_id": 0}, {"member_level": 0}, {"member_level": 4},
        {"abrade": 1.5}, {"abrade": -0.1}, {"buy_price": -1},
    ])
    def test_smart_bounds(self, kw):
        with _pytest.raises(ValidationError):
            SmartListRequest(**{"asset_id": "a", "template_id": 1, **kw})

    def test_batch_size_capped_at_30(self):
        item = {"commodity_id": 1, "template_id": 2}
        assert len(BatchSmartRepriceRequest(items=[item] * 30).items) == 30
        with _pytest.raises(ValidationError):
            BatchSmartRepriceRequest(items=[item] * 31)
