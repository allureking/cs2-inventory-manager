"""
手滑低价防线（v0.13.4）测试。内存库 + mock，无网络。

防线的判据：price < 基准 × LOW_PRICE_CONFIRM_RATIO(0.95) → 409 + 结构化 detail，
前端据此弹二次确认，用户确认后带 confirm_below_market=true 重发。

本文件锁住的不变量：
  A. 低于市价 5% 以上 → 触发；正好等于/略高于阈值 → 不触发（边界不能跑偏）
  B. confirm_below_market=true → 一律放行（否则用户点了确认还是提交不了）
  C. 查不到基准（无名字/无报价/无 token/接口抛错）→ **放行**，绝不能拦
     （fail-open 是刻意选择：缺基准最集中的就是"刚买入、第一次上架"的品）
  D. 租金基准取 min(units) 而非 units[0]——出租查询没带排序参数
  E. 409 的 detail 结构稳定（前端在按 code 字段匹配）
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi import HTTPException

import app.services.price_guard as pg
import app.services.youpin as yp
from app.api.routes import listing as listing_route
from app.models.db_models import PriceSnapshot
from tests.conftest import memory_db

NAME = "AK-47 | Redline (Field-Tested)"


def _run(coro):
    return asyncio.run(coro)


async def _seed_price(Session, price, name=NAME):
    async with Session() as db:
        db.add(PriceSnapshot(market_hash_name=name, platform="YOUPIN",
                             sell_price=price, snapshot_minute="202607290700"))
        await db.commit()


# ── A. 阈值边界 ─────────────────────────────────────────────────────────────


class TestThreshold:
    def _basis(self, v=100.0):
        return pg.Basis(value=v, source="snapshot", detail="本地快照·跨平台最低价")

    @pytest.mark.parametrize("price,expected", [
        (100.0, False),   # 等于市价
        (96.0,  False),   # 低 4%
        (95.0,  False),   # 正好低 5% —— 判据是严格小于 basis*0.95，边界不触发
        (94.99, True),    # 刚过线
        (50.0,  True),    # 半价
        (1.0,   True),    # 100 倍单位错误
        (120.0, False),   # 高于市价
    ])
    def test_boundary(self, price, expected):
        assert pg.is_below_market(price, self._basis()) is expected

    def test_ratio_constant_is_the_single_knob(self):
        """阈值必须只由这一个常数决定,便于一行改语义。"""
        assert pg.LOW_PRICE_CONFIRM_RATIO == 0.95
        b = self._basis(200.0)
        assert pg.is_below_market(200.0 * 0.95 - 0.01, b) is True
        assert pg.is_below_market(200.0 * 0.95, b) is False

    def test_none_price_or_basis_never_triggers(self):
        assert pg.is_below_market(None, self._basis()) is False
        assert pg.is_below_market(1.0, pg.NO_BASIS) is False
        assert pg.is_below_market(1.0, pg.Basis(value=0.0, source="snapshot")) is False
        assert pg.is_below_market(1.0, pg.Basis(value=-5.0, source="snapshot")) is False


# ── C. 售价基准与 fail-open ─────────────────────────────────────────────────


class TestSellBasis:
    def test_basis_from_snapshot(self):
        async def body():
            async with memory_db() as Session:
                await _seed_price(Session, 365.0)
                async with Session() as db:
                    b = await pg.sell_basis(db, NAME)
            assert b.usable and b.value == 365.0 and b.source == "snapshot"
        _run(body())

    def test_no_name_no_basis(self):
        async def body():
            async with memory_db() as Session:
                async with Session() as db:
                    assert (await pg.sell_basis(db, None)).usable is False
                    assert (await pg.sell_basis(db, "")).usable is False
        _run(body())

    def test_unpriced_item_yields_no_basis_not_zero(self):
        """没有报价的饰品必须是"无基准"(放行),而不是基准=0 或抛错。"""
        async def body():
            async with memory_db() as Session:
                async with Session() as db:
                    b = await pg.sell_basis(db, "从未采过价的饰品")
                assert b.usable is False
                assert pg.is_below_market(0.01, b) is False   # 再离谱也放行
        _run(body())

    def test_query_failure_fails_open(self, monkeypatch):
        """基准查询本身炸了,不能连累改价。"""
        async def boom(names, db):
            raise RuntimeError("db exploded")
        monkeypatch.setattr("app.services.pricing.get_latest_prices", boom)

        async def body():
            async with memory_db() as Session:
                async with Session() as db:
                    b = await pg.sell_basis(db, NAME)
            assert b.usable is False
        _run(body())


# ── D. 租金基准 ─────────────────────────────────────────────────────────────


class TestLeaseBasis:
    def _patch(self, monkeypatch, rows, token="tok"):
        async def fake(template_id, page_size=20):
            return rows
        monkeypatch.setattr(yp, "fetch_market_lease_price", fake)
        monkeypatch.setattr(yp, "get_active_token", lambda: token)

    def test_takes_min_not_first(self, monkeypatch):
        """出租查询的请求体没有排序参数,列表可能无序 → 必须取 min 而非 [0]。

        若退回 units[0],基准会变成 9.0,一个 6.0 的日租就不再触发确认。
        """
        self._patch(monkeypatch, [
            {"leaseUnitPrice": "9.0"},
            {"leaseUnitPrice": "5.0"},    # 真正的最低价排在后面
            {"leaseUnitPrice": "7.0"},
        ])
        b = _run(pg.lease_basis(123))
        assert b.value == 5.0 and b.source == "youpin_lease"

    def test_no_token_no_basis(self, monkeypatch):
        self._patch(monkeypatch, [{"leaseUnitPrice": "5.0"}], token=None)
        assert _run(pg.lease_basis(123)).usable is False

    def test_no_template_no_basis(self):
        assert _run(pg.lease_basis(None)).usable is False
        assert _run(pg.lease_basis(0)).usable is False

    def test_empty_or_garbage_list_fails_open(self, monkeypatch):
        self._patch(monkeypatch, [])
        assert _run(pg.lease_basis(123)).usable is False
        self._patch(monkeypatch, [{"leaseUnitPrice": None}, {"leaseUnitPrice": "abc"},
                                  {"leaseUnitPrice": 0}])
        assert _run(pg.lease_basis(123)).usable is False

    def test_api_exception_fails_open(self, monkeypatch):
        async def boom(template_id, page_size=20):
            raise RuntimeError("rate limited")
        monkeypatch.setattr(yp, "fetch_market_lease_price", boom)
        monkeypatch.setattr(yp, "get_active_token", lambda: "tok")
        assert _run(pg.lease_basis(123)).usable is False

    def test_alt_casing_field(self, monkeypatch):
        self._patch(monkeypatch, [{"LeaseUnitPrice": "3.5"}])
        assert _run(pg.lease_basis(123)).value == 3.5


# ── E. 端点行为：409 / 确认放行 / 无基准放行 ────────────────────────────────


class TestGuardEndpointBehaviour:
    """直接测 _guard_low_price —— 它是四个端点共用的那一层。"""

    def _patch_basis(self, monkeypatch, sell=None, lease=None):
        async def fake_sell(name):
            return (pg.Basis(value=sell, source="snapshot", detail="本地快照·跨平台最低价")
                    if sell else pg.NO_BASIS)
        async def fake_lease(tid):
            return (pg.Basis(value=lease, source="youpin_lease", detail="悠悠市场·最低日租")
                    if lease else pg.NO_BASIS)
        monkeypatch.setattr(listing_route, "_sell_basis_for", fake_sell)
        monkeypatch.setattr(pg, "lease_basis", fake_lease)

    def test_sell_below_raises_409_with_structured_detail(self, monkeypatch):
        self._patch_basis(monkeypatch, sell=1000.0)
        with pytest.raises(HTTPException) as ei:
            _run(listing_route._guard_low_price(
                confirmed=False, sell_price=10.0, market_hash_name=NAME))
        assert ei.value.status_code == 409
        d = ei.value.detail
        # 前端按 code 匹配,字段名不能漂
        assert d["code"] == "below_market_price"
        assert d["field"] == "售价"
        assert d["price"] == 10.0 and d["basis"] == 1000.0
        assert d["pct_below"] == 99.0
        assert d["threshold_pct"] == 5.0
        assert d["basis_source"] == "snapshot"
        assert "message" in d

    def test_sell_at_market_passes(self, monkeypatch):
        self._patch_basis(monkeypatch, sell=1000.0)
        _run(listing_route._guard_low_price(
            confirmed=False, sell_price=990.0, market_hash_name=NAME))  # 低 1%,放行

    def test_confirmed_always_passes(self, monkeypatch):
        """用户点过确认就必须能提交,否则功能等于硬拦截。"""
        self._patch_basis(monkeypatch, sell=1000.0, lease=10.0)
        _run(listing_route._guard_low_price(
            confirmed=True, sell_price=0.01, lease_unit=0.01,
            market_hash_name=NAME, template_id=1))

    def test_no_basis_passes(self, monkeypatch):
        self._patch_basis(monkeypatch, sell=None, lease=None)
        _run(listing_route._guard_low_price(
            confirmed=False, sell_price=0.01, lease_unit=0.01,
            market_hash_name=NAME, template_id=1))

    def test_lease_below_raises_409(self, monkeypatch):
        self._patch_basis(monkeypatch, lease=10.0)
        with pytest.raises(HTTPException) as ei:
            _run(listing_route._guard_low_price(
                confirmed=False, lease_unit=3.0, template_id=1))
        assert ei.value.status_code == 409
        assert ei.value.detail["field"] == "日租金"

    def test_lease_skipped_without_template(self, monkeypatch):
        """没有 template_id 就没有租金基准 → 放行,不得报错。"""
        self._patch_basis(monkeypatch, lease=10.0)
        _run(listing_route._guard_low_price(confirmed=False, lease_unit=0.01))

    def test_sell_checked_before_lease(self, monkeypatch):
        """两侧都超标时先报售价,detail 里 field 必须指明是哪一个。"""
        self._patch_basis(monkeypatch, sell=1000.0, lease=10.0)
        with pytest.raises(HTTPException) as ei:
            _run(listing_route._guard_low_price(
                confirmed=False, sell_price=1.0, lease_unit=1.0,
                market_hash_name=NAME, template_id=1))
        assert ei.value.detail["field"] == "售价"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


# ── F. 真实 DB 路径（不 mock _sell_basis_for，走 AsyncSessionLocal）─────────


class TestRealDbResolution:
    """上面的端点测试把 _sell_basis_for 换成了假的；这里跑真家伙，
    确保 AsyncSessionLocal 那条真实取数路径没写错。"""

    def test_guard_end_to_end_with_real_snapshot(self):
        async def body():
            async with memory_db() as Session:
                import app.core.database as core_db
                import app.api.routes.listing as lr
                await _seed_price(Session, 1000.0)
                orig = core_db.AsyncSessionLocal
                lr_orig = getattr(lr, "AsyncSessionLocal", None)
                core_db.AsyncSessionLocal = Session
                lr.AsyncSessionLocal = Session
                try:
                    # 低于 1000×0.95 → 触发
                    with pytest.raises(HTTPException) as ei:
                        await lr._guard_low_price(
                            confirmed=False, sell_price=100.0, market_hash_name=NAME)
                    assert ei.value.status_code == 409
                    assert ei.value.detail["basis"] == 1000.0
                    # 未低于阈值 → 放行
                    await lr._guard_low_price(
                        confirmed=False, sell_price=960.0, market_hash_name=NAME)
                    # 名字查不到报价 → 放行
                    await lr._guard_low_price(
                        confirmed=False, sell_price=0.01, market_hash_name="没采过价的东西")
                finally:
                    core_db.AsyncSessionLocal = orig
                    if lr_orig is not None:
                        lr.AsyncSessionLocal = lr_orig
        _run(body())

    def test_hash_name_by_asset_id(self):
        """asset_id 无 unique 约束（租赁导入甚至往里写 order_id），
        重复时必须只取一行而不是抛 MultipleResultsFound。"""
        async def body():
            from app.models.db_models import InventoryItem
            async with memory_db() as Session:
                import app.api.routes.listing as lr
                async with Session() as db:
                    for i in (1, 2):   # 同一个 asset_id 两行
                        db.add(InventoryItem(steam_id="", class_id="STEAM",
                                             instance_id=f"x{i}", asset_id="dup-1",
                                             market_hash_name=NAME, name=NAME,
                                             status="in_steam"))
                    await db.commit()
                lr_orig = lr.AsyncSessionLocal
                lr.AsyncSessionLocal = Session
                try:
                    assert await lr._hash_name_by_asset("dup-1") == NAME
                    assert await lr._hash_name_by_asset("不存在") is None
                finally:
                    lr.AsyncSessionLocal = lr_orig
        _run(body())


def test_lease_basis_times_out_and_fails_open(monkeypatch):
    """悠悠卡住时不能把改价对话框一起卡住(共享 client 超时是 20s)。"""
    import app.services.price_guard as _pg

    async def slow(template_id, page_size=20):
        await asyncio.sleep(5)
        return [{"leaseUnitPrice": "5.0"}]

    monkeypatch.setattr(yp, "fetch_market_lease_price", slow)
    monkeypatch.setattr(yp, "get_active_token", lambda: "tok")
    monkeypatch.setattr(_pg, "LEASE_BASIS_TIMEOUT_S", 0.05)

    import time
    t0 = time.monotonic()
    b = _run(_pg.lease_basis(123))
    assert b.usable is False
    assert time.monotonic() - t0 < 1.0, "应当立刻超时放行,而不是干等"
