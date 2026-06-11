"""
dashboard 路由测试（httpx ASGITransport，内存库，无网络）。

overview：
  - ACTIVE_STATUSES 口径：仅 in_steam + rented_out 计入 total_active（in_storage/sold 排除）
  - 空库存 / 全 in_storage / 混合
  - 成本聚合（effective_cost = coalesce(manual, purchase_price)）、定价覆盖率
  - 市值（无 token → 外部估值=0 → fallback 到 price_snapshot 逐件估值）
  - PnL：逐件 snapshot vs effective_cost、manual 覆盖、未覆盖排除、无覆盖→None

chart-data（纯 DB 聚合）：
  - 空 / 类型聚合 / PnL 分桶 / top_value 排序 / gainers·losers / icon_url

为杜绝网络：monkeypatch 掉 _get_cached_rented_value/_steam_value 返回 0（强制 snapshot 估值）。
每个 overview 测试重置 _overview_cache（模块级缓存）。
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from app.api.routes import dashboard
from app.models.db_models import InventoryItem, PriceSnapshot
from tests.conftest import asgi_client

MINUTE = "202606080000"


def _run(coro):
    return asyncio.run(coro)


def _patch_overview_no_network(monkeypatch):
    async def _zero():
        return 0.0
    monkeypatch.setattr(dashboard, "_get_cached_rented_value", _zero)
    monkeypatch.setattr(dashboard, "_get_cached_steam_value", _zero)
    monkeypatch.setattr(dashboard, "_overview_cache", {"data": None, "ts": 0.0})


_seq = {"n": 0}


def item(name="AK-47 | Redline (Field-Tested)", status="in_steam",
         purchase_price=None, manual=None, item_type=None, icon_url=None, cn_name=None):
    _seq["n"] += 1
    return InventoryItem(
        steam_id="76561198000000000",
        class_id="c",
        instance_id=f"i{_seq['n']}",
        market_hash_name=name,
        name=cn_name or name,
        status=status,
        purchase_price=purchase_price,
        purchase_price_manual=manual,
        item_type=item_type,
        icon_url=icon_url,
    )


def snap(name="AK-47 | Redline (Field-Tested)", platform="YOUPIN", sell_price=100.0, minute=MINUTE):
    return PriceSnapshot(market_hash_name=name, platform=platform, sell_price=sell_price, snapshot_minute=minute)


def _seeder(objs):
    async def seed(db):
        for o in objs:
            db.add(o)
        await db.commit()
    return seed


# ── overview ───────────────────────────────────────────────────────────────


def test_overview_empty(monkeypatch):
    _patch_overview_no_network(monkeypatch)

    async def body():
        async with asgi_client() as (client, _):
            r = await client.get("/api/dashboard/overview")
            assert r.status_code == 200
            d = r.json()
            assert d["total_active"] == 0
            assert d["status_breakdown"] == {"in_steam": 0, "rented_out": 0, "in_storage": 0, "sold": 0}
            assert d["market_value"] == 0
            assert d["pnl"] is None and d["pnl_pct"] is None
            assert d["coverage_pct"] == 0
            assert d["total_cost"] == 0
    _run(body())


def test_overview_excludes_in_storage_and_sold(monkeypatch):
    _patch_overview_no_network(monkeypatch)

    async def body():
        objs = [item(status="in_storage", purchase_price=100.0),
                item(status="sold", purchase_price=200.0)]
        async with asgi_client(seed=_seeder(objs)) as (client, _):
            d = (await client.get("/api/dashboard/overview")).json()
            assert d["total_active"] == 0                       # 口径：两者都不计
            assert d["status_breakdown"]["in_storage"] == 1
            assert d["status_breakdown"]["sold"] == 1
            assert d["cost_breakdown"] == {"rented_out": 0, "in_steam": 0}
    _run(body())


def test_overview_active_counts_and_costs(monkeypatch):
    _patch_overview_no_network(monkeypatch)

    async def body():
        objs = [item(name="A", status="in_steam", purchase_price=100.0),
                item(name="B", status="rented_out", purchase_price=200.0)]
        async with asgi_client(seed=_seeder(objs)) as (client, _):
            d = (await client.get("/api/dashboard/overview")).json()
            assert d["total_active"] == 2
            assert d["total_cost"] == 300.0
            assert d["cost_breakdown"] == {"rented_out": 200.0, "in_steam": 100.0}
            assert d["priced_count"] == 2
            assert d["coverage_pct"] == 100.0
    _run(body())


def test_overview_coverage_partial(monkeypatch):
    _patch_overview_no_network(monkeypatch)

    async def body():
        objs = [item(name="A", status="in_steam", purchase_price=100.0),
                item(name="B", status="in_steam")]  # 无成本
        async with asgi_client(seed=_seeder(objs)) as (client, _):
            d = (await client.get("/api/dashboard/overview")).json()
            assert d["priced_count"] == 1
            assert d["unpriced_count"] == 1
            assert d["coverage_pct"] == 50.0
    _run(body())


def test_overview_market_value_from_snapshots(monkeypatch):
    _patch_overview_no_network(monkeypatch)

    async def body():
        objs = [
            item(name="A", status="in_steam"), item(name="A", status="in_steam"),  # 2× A
            item(name="B", status="rented_out"),                                   # 1× B
            snap(name="A", sell_price=150.0), snap(name="B", sell_price=300.0),
        ]
        async with asgi_client(seed=_seeder(objs)) as (client, _):
            d = (await client.get("/api/dashboard/overview")).json()
            assert d["market_value_steam"] == 300.0   # 150 × 2
            assert d["market_value_rented"] == 300.0  # 300 × 1
            assert d["market_value"] == 600.0
    _run(body())


def test_overview_pnl_single(monkeypatch):
    _patch_overview_no_network(monkeypatch)

    async def body():
        objs = [item(name="A", status="in_steam", purchase_price=100.0), snap(name="A", sell_price=150.0)]
        async with asgi_client(seed=_seeder(objs)) as (client, _):
            d = (await client.get("/api/dashboard/overview")).json()
            assert d["pnl"] == 50.0
            assert d["pnl_pct"] == 50.0
            assert d["pnl_covered_count"] == 1
    _run(body())


def test_overview_pnl_manual_override(monkeypatch):
    _patch_overview_no_network(monkeypatch)

    async def body():
        # purchase_price=100, manual=80 → effective_cost=80 → pnl=150-80=70
        objs = [item(name="A", status="in_steam", purchase_price=100.0, manual=80.0), snap(name="A", sell_price=150.0)]
        async with asgi_client(seed=_seeder(objs)) as (client, _):
            d = (await client.get("/api/dashboard/overview")).json()
            assert d["pnl"] == 70.0
    _run(body())


def test_overview_pnl_excludes_uncovered(monkeypatch):
    _patch_overview_no_network(monkeypatch)

    async def body():
        # A: 有成本无快照；B: 有快照无成本 → 无任何「成本+市价」齐全的 → pnl None
        objs = [item(name="A", status="in_steam", purchase_price=100.0),
                item(name="B", status="in_steam"),
                snap(name="B", sell_price=999.0)]
        async with asgi_client(seed=_seeder(objs)) as (client, _):
            d = (await client.get("/api/dashboard/overview")).json()
            assert d["pnl"] is None
            assert d["pnl_covered_count"] == 0
    _run(body())


def test_overview_pnl_multi_same_name(monkeypatch):
    _patch_overview_no_network(monkeypatch)

    async def body():
        # 2 件 A 各成本 100，A 市价 150 → 逐件：market=150×2=300, cost=200 → pnl=100
        objs = [item(name="A", status="in_steam", purchase_price=100.0),
                item(name="A", status="in_steam", purchase_price=100.0),
                snap(name="A", sell_price=150.0)]
        async with asgi_client(seed=_seeder(objs)) as (client, _):
            d = (await client.get("/api/dashboard/overview")).json()
            assert d["pnl"] == 100.0
            assert d["pnl_pct"] == 50.0
            assert d["pnl_covered_count"] == 2
    _run(body())


# ── chart-data ─────────────────────────────────────────────────────────────


def test_chart_data_empty():
    async def body():
        async with asgi_client() as (client, _):
            d = (await client.get("/api/dashboard/chart-data")).json()
            assert d["type_composition"] == []
            assert d["top_value"] == [] and d["top_gainers"] == [] and d["top_losers"] == []
            assert set(d["pnl_distribution"].values()) == {0}
    _run(body())


def test_chart_data_type_composition():
    async def body():
        objs = [
            item(name="A", status="in_steam", item_type="rifle", purchase_price=100.0),
            item(name="B", status="in_steam", item_type="knife", purchase_price=1000.0),
            snap(name="A", sell_price=150.0), snap(name="B", sell_price=2000.0),
        ]
        async with asgi_client(seed=_seeder(objs)) as (client, _):
            d = (await client.get("/api/dashboard/chart-data")).json()
            types = {t["type"]: t for t in d["type_composition"]}
            assert types["rifle"]["market_value"] == 150.0
            assert types["knife"]["market_value"] == 2000.0
            # 排序：market_value 降序 → knife 在前
            assert d["type_composition"][0]["type"] == "knife"
    _run(body())


def test_chart_data_pnl_buckets():
    async def body():
        objs = [
            item(name="WIN", status="in_steam", item_type="rifle", purchase_price=100.0),  # +50% → 50~100
            item(name="LOSE", status="in_steam", item_type="rifle", purchase_price=100.0), # -60% → <-50
            snap(name="WIN", sell_price=150.0), snap(name="LOSE", sell_price=40.0),
        ]
        async with asgi_client(seed=_seeder(objs)) as (client, _):
            d = (await client.get("/api/dashboard/chart-data")).json()
            b = d["pnl_distribution"]
            assert b["50~100"] == 1
            assert b["<-50"] == 1
    _run(body())


def test_chart_data_gainers_losers():
    async def body():
        objs = [
            item(name="WIN", status="in_steam", item_type="rifle", purchase_price=100.0),
            item(name="LOSE", status="in_steam", item_type="rifle", purchase_price=100.0),
            snap(name="WIN", sell_price=150.0), snap(name="LOSE", sell_price=40.0),
        ]
        async with asgi_client(seed=_seeder(objs)) as (client, _):
            d = (await client.get("/api/dashboard/chart-data")).json()
            assert [g["name"] for g in d["top_gainers"]] == ["WIN"]
            assert [l["name"] for l in d["top_losers"]] == ["LOSE"]
    _run(body())


def test_chart_data_top_value_sorted_and_icon():
    async def body():
        objs = [
            item(name="CHEAP", status="in_steam", item_type="rifle", purchase_price=1.0, icon_url="ic_cheap"),
            item(name="PRICEY", status="in_steam", item_type="knife", purchase_price=1.0, icon_url="ic_pricey"),
            snap(name="CHEAP", sell_price=10.0), snap(name="PRICEY", sell_price=5000.0),
        ]
        async with asgi_client(seed=_seeder(objs)) as (client, _):
            d = (await client.get("/api/dashboard/chart-data")).json()
            assert d["top_value"][0]["name"] == "PRICEY"
            assert d["top_value"][0]["icon_url"] == "ic_pricey"
    _run(body())


def test_chart_data_excludes_inactive():
    async def body():
        objs = [
            item(name="STO", status="in_storage", item_type="rifle", purchase_price=100.0),
            item(name="SOLD", status="sold", item_type="rifle", purchase_price=100.0),
            snap(name="STO", sell_price=150.0), snap(name="SOLD", sell_price=150.0),
        ]
        async with asgi_client(seed=_seeder(objs)) as (client, _):
            d = (await client.get("/api/dashboard/chart-data")).json()
            assert d["type_composition"] == []  # in_storage/sold 不计入
    _run(body())


# ── 悠悠估值缓存 SWR（v0.12 性能修复:过期返回旧值+后台刷新,请求不阻塞外部 API）──


def test_swr_fresh_cache_returned_directly(monkeypatch):
    import time as _t
    monkeypatch.setattr(dashboard, "_rented_value_cache",
                        {"value": 123.0, "ts": _t.monotonic(), "refreshing": False})

    async def body():
        assert await dashboard._get_cached_rented_value() == 123.0
    _run(body())


def test_swr_stale_returns_old_value_without_blocking(monkeypatch):
    # 过期+有旧值：立即返回旧值；绝不同步调用外部 API（无 token → 连后台任务都不 kick）
    import time as _t
    monkeypatch.setattr(dashboard, "_rented_value_cache",
                        {"value": 456.0, "ts": _t.monotonic() - 9999, "refreshing": False})
    called = {"n": 0}

    async def boom():
        called["n"] += 1
        raise AssertionError("不应同步调用外部 API")
    monkeypatch.setattr(dashboard, "_fetch_rented_value", boom)

    async def body():
        assert await dashboard._get_cached_rented_value() == 456.0
        assert called["n"] == 0
    _run(body())


def test_swr_background_refresh_updates_cache(monkeypatch):
    # 有 token + 过期：立即返回旧值并 kick 后台任务(标记 refreshing);
    # 刷新体 _refresh_now 单独确定性验证(不赌 create_task 在 CI 上的调度时机)
    import time as _t
    cache = {"value": 1.0, "ts": _t.monotonic() - 9999, "refreshing": False}
    monkeypatch.setattr(dashboard, "_steam_value_cache", cache)

    import app.services.youpin as yp
    monkeypatch.setattr(yp, "get_active_token", lambda: "tok")

    async def fake_fetch():
        return 999.0
    monkeypatch.setattr(dashboard, "_fetch_steam_value", fake_fetch)

    async def body():
        v = await dashboard._get_cached_steam_value()
        assert v == 1.0                    # 旧值立即返回,不阻塞
        assert cache["refreshing"] is True  # 后台任务已被 kick
        # 确定性执行刷新体,验证语义:新值落缓存 + refreshing 复位
        await dashboard._refresh_now(cache, fake_fetch)
        assert cache["value"] == 999.0
        assert cache["refreshing"] is False
    _run(body())


def test_refresh_now_failure_keeps_old_value():
    # 外部失败:保留旧值,refreshing 复位(下次再试)
    cache = {"value": 42.0, "ts": 0.0, "refreshing": True}

    async def boom():
        raise RuntimeError("youpin down")

    async def body():
        await dashboard._refresh_now(cache, boom)
        assert cache["value"] == 42.0
        assert cache["refreshing"] is False
    _run(body())


def test_fetch_steam_value_uses_parse_money(monkeypatch):
    # 回归锁：带 ¥/千分位 的估值必须解析成功（此前 float() 抛错被吞 → 旧值/0）
    import app.services.youpin as yp

    async def fake_stock_records(page=1, page_size=1):
        return [], 0, "¥425,194.14"
    monkeypatch.setattr(yp, "fetch_stock_records", fake_stock_records)

    async def body():
        assert await dashboard._fetch_steam_value() == pytest.approx(425194.14)
    _run(body())


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
