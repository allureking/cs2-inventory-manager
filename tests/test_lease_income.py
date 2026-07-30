"""
单品租赁实绩(v0.13.0 提案9a)测试:mock fetch_lease_records,内存库,无网络。

  - record_lease_income:分页落库/幂等覆盖/无 token 跳过/单位分→元
  - get_item_lease_income:逐日聚合+汇总
  - get_lease_income_rankings:按品聚合排序
  - API /analysis/lease-income(含实际年化)+ /rankings + 入参 422
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from sqlalchemy import select

import app.core.database as core_db
import app.services.lease_income as li
import app.services.youpin as yp
from app.api.routes import analysis as analysis_route
from app.models.db_models import LeaseIncomeDaily, PriceSnapshot
from tests.conftest import asgi_client, memory_db


def _run(coro):
    return asyncio.run(coro)


def lease_rec(cid, name, rent_cents):
    return {"orderId": f"o{cid}", "commodityInfo": {
        "commodityId": cid, "commodityHashName": name, "shortLeasePrice": rent_cents}}


def _patch_fetch(monkeypatch, pages):
    async def fake(page=1, page_size=100):
        batch = pages[page - 1] if page - 1 < len(pages) else []
        return batch, sum(len(p) for p in pages), ""
    monkeypatch.setattr(yp, "fetch_lease_records", fake)
    monkeypatch.setattr(yp, "get_active_token", lambda: "tok")


# ── record_lease_income ────────────────────────────────────────────────────


def test_record_pagination_and_cents_to_yuan(monkeypatch):
    # 两页:首页满 100 件套路太长,用页尾不满终止:p1=2条, 终止
    _patch_fetch(monkeypatch, [[lease_rec(1, "AK-47 | A", 150), lease_rec(2, "AWP | B", 2350)]])

    async def body():
        async with memory_db() as Session:
            monkeypatch.setattr(core_db, "AsyncSessionLocal", Session)
            r = await li.record_lease_income("2026-06-11")
            assert r["recorded"] == 2
            assert r["total_rent"] == pytest.approx(25.0)  # 1.5 + 23.5
            async with Session() as db:
                rows = (await db.execute(select(LeaseIncomeDaily))).scalars().all()
                by = {x.commodity_id: x for x in rows}
                assert by[1].daily_rent == 1.5     # 分→元
                assert by[2].daily_rent == 23.5
                assert by[1].date == "2026-06-11"
    _run(body())


def test_record_idempotent_overwrite(monkeypatch):
    async def body():
        async with memory_db() as Session:
            monkeypatch.setattr(core_db, "AsyncSessionLocal", Session)
            _patch_fetch(monkeypatch, [[lease_rec(1, "AK-47 | A", 100)]])
            await li.record_lease_income("2026-06-11")
            _patch_fetch(monkeypatch, [[lease_rec(1, "AK-47 | A", 200)]])  # 同日改价
            await li.record_lease_income("2026-06-11")
            async with Session() as db:
                rows = (await db.execute(select(LeaseIncomeDaily))).scalars().all()
                assert len(rows) == 1          # 不重复
                assert rows[0].daily_rent == 2.0  # 覆盖为新值
    _run(body())


def test_record_skips_without_token(monkeypatch):
    monkeypatch.setattr(yp, "get_active_token", lambda: None)

    async def body():
        r = await li.record_lease_income("2026-06-11")
        assert r.get("skipped_no_token") is True
    _run(body())


# ── 聚合查询 ────────────────────────────────────────────────────────────────


async def _seed_income(Session, rows):
    async with Session() as db:
        for r in rows:
            db.add(LeaseIncomeDaily(**r))
        await db.commit()


def test_item_income_series_and_totals():
    async def body():
        async with memory_db() as Session:
            await _seed_income(Session, [
                dict(date="2026-06-09", commodity_id=1, market_hash_name="AK", daily_rent=1.0),
                dict(date="2026-06-09", commodity_id=2, market_hash_name="AK", daily_rent=2.0),
                dict(date="2026-06-10", commodity_id=1, market_hash_name="AK", daily_rent=1.0),
                dict(date="2026-06-10", commodity_id=9, market_hash_name="AWP", daily_rent=9.0),  # 它品
            ])
            async with Session() as db:
                d = await li.get_item_lease_income(db, "AK", days=30)
                assert d["days_recorded"] == 2
                assert d["series"][0] == {"date": "2026-06-09", "rented_count": 2, "rent": 3.0}
                assert d["series"][1] == {"date": "2026-06-10", "rented_count": 1, "rent": 1.0}
                assert d["total_rent"] == 4.0
                assert d["avg_daily_rent"] == 2.0
    _run(body())


def test_rankings_aggregation():
    async def body():
        async with memory_db() as Session:
            await _seed_income(Session, [
                dict(date="2026-06-09", commodity_id=1, market_hash_name="AK", daily_rent=2.0),
                dict(date="2026-06-10", commodity_id=1, market_hash_name="AK", daily_rent=2.0),
                dict(date="2026-06-10", commodity_id=9, market_hash_name="AWP", daily_rent=1.0),
            ])
            async with Session() as db:
                rows = await li.get_lease_income_rankings(db, days=30)
                assert rows[0]["market_hash_name"] == "AK"   # 总租金降序
                assert rows[0]["days_rented"] == 2
                assert rows[0]["units"] == 1
                assert rows[0]["total_rent"] == 4.0
                assert rows[0]["avg_rent_per_unit_day"] == pytest.approx(2.0)
    _run(body())


def test_rankings_units_not_inflated_by_commodity_id_churn():
    """回归锁：同一物理饰品每个租赁周期换新 commodity_id,不得被算成多件。

    2 件饰品满租 10 天,每 5 天换约 → 出现 4 个不同 commodity_id。
    旧实现 units=COUNT(DISTINCT commodity_id)=4 → 件均日租被除大 2 倍、
    实际年化同比例低估,且周转越快低估越狠(与单品弹窗自相矛盾)。
    正确:units = 单日在租件数的峰值 = 2。
    """
    async def body():
        async with memory_db() as Session:
            rows = []
            for day in range(1, 6):            # 前 5 天:cid 1,2
                for cid in (1, 2):
                    rows.append(dict(date=f"2026-06-{day:02d}", commodity_id=cid,
                                     market_hash_name="AK", daily_rent=1.5))
            for day in range(6, 11):           # 后 5 天:换约 → cid 3,4
                for cid in (3, 4):
                    rows.append(dict(date=f"2026-06-{day:02d}", commodity_id=cid,
                                     market_hash_name="AK", daily_rent=1.5))
            await _seed_income(Session, rows)
            async with Session() as db:
                r = (await li.get_lease_income_rankings(db, days=30))[0]
                assert r["units"] == 2                    # 不是 4
                assert r["days_rented"] == 10
                assert r["total_rent"] == pytest.approx(30.0)   # 2 件 × 1.5 × 10 天
                # 件均日租应回到 1.5,而非被 4 件除成 0.75
                assert r["avg_rent_per_unit_day"] == pytest.approx(1.5)
    _run(body())


def test_rankings_empty():
    async def body():
        async with memory_db() as Session:
            async with Session() as db:
                assert await li.get_lease_income_rankings(db) == []
    _run(body())


# ── API ────────────────────────────────────────────────────────────────────

ROUTERS = [(analysis_route.router, "/api/analysis")]


def test_api_item_income_with_actual_annual():
    async def body():
        def seed_objs():
            return [
                LeaseIncomeDaily(date="2026-06-10", commodity_id=1, market_hash_name="AK", daily_rent=1.0),
                PriceSnapshot(market_hash_name="AK", platform="YOUPIN", sell_price=365.0, snapshot_minute="202606100000"),
            ]
        async def seed(db):
            for o in seed_objs():
                db.add(o)
            await db.commit()
        async with asgi_client(seed=seed, routers=ROUTERS) as (client, _):
            d = (await client.get("/api/analysis/lease-income", params={"market_hash_name": "AK"})).json()
            assert d["days_recorded"] == 1
            assert d["current_price"] == 365.0
            # v0.13.3 口径修正：区分「在租日年化」与「按日历天摊薄的真实回报」。
            # 1 件、日租 1.0、市价 365 → 在租日年化 = 1.0×365/365 = 100%
            assert d["utilization_annual_pct"] == pytest.approx(100.0)
            # 但 30 天窗口里只租出去 1 天 → 出租率 1/30,真实回报 ≈ 3.33%
            # (旧实现分母只数"有租记录的天数",闲置期被自动剔除 → 恒报 100%,
            #  出租率越差虚高越多,恰好抵消实绩归因的意义)
            assert d["utilization_pct"] == pytest.approx(3.3, abs=0.1)
            assert d["actual_annual_pct"] == pytest.approx(3.33, abs=0.01)
    _run(body())


def test_api_item_income_full_utilization_matches_both_metrics():
    """满租(窗口内每天都在租) → 两个口径应当一致,证明摊薄公式没有系统性偏移。"""
    async def body():
        async def seed(db):
            for i in range(1, 31):        # 30 天窗口全部有租
                db.add(LeaseIncomeDaily(date=f"2026-06-{i:02d}", commodity_id=i,
                                        market_hash_name="AK", daily_rent=1.0))
            db.add(PriceSnapshot(market_hash_name="AK", platform="YOUPIN",
                                 sell_price=365.0, snapshot_minute="202606300000"))
            await db.commit()
        async with asgi_client(seed=seed, routers=ROUTERS) as (client, _):
            d = (await client.get("/api/analysis/lease-income",
                                  params={"market_hash_name": "AK", "days": 30})).json()
            assert d["utilization_pct"] == pytest.approx(100.0, abs=0.1)
            assert d["actual_annual_pct"] == pytest.approx(d["utilization_annual_pct"], abs=0.01)
            assert d["actual_annual_pct"] == pytest.approx(100.0, abs=0.01)
    _run(body())


def test_api_rankings_and_validation():
    async def body():
        async with asgi_client(routers=ROUTERS) as (client, _):
            r = await client.get("/api/analysis/lease-income/rankings")
            assert r.status_code == 200 and r.json()["items"] == []
            assert (await client.get("/api/analysis/lease-income")).status_code == 422  # 缺必填
            assert (await client.get("/api/analysis/lease-income",
                                     params={"market_hash_name": "A", "days": 999})).status_code == 422
    _run(body())


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
