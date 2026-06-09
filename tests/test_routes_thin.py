"""
薄路由层测试（items / prices·cached / tracker GET），经 httpx ASGITransport。

这些端点是对已测 service/DB 逻辑的 HTTP 包装；这里验证路由参数校验、
DB 读取串通、异常入参（422 / 默认值）。全部内存库,无网络。
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from app.api.routes import items as items_route
from app.api.routes import prices as prices_route
from app.api.routes import tracker as tracker_route
from app.models.db_models import Item, PriceSnapshot, DailyTracker
from tests.conftest import asgi_client


def _run(coro):
    return asyncio.run(coro)


def _seeder(objs):
    async def seed(db):
        for o in objs:
            db.add(o)
        await db.commit()
    return seed


# ── items GET / ────────────────────────────────────────────────────────────

ITEMS = [(items_route.router, "/api/items")]


def test_items_list_empty():
    async def body():
        async with asgi_client(routers=ITEMS) as (client, _):
            d = (await client.get("/api/items/")).json()
            assert d["total"] == 0 and d["data"] == []
    _run(body())


def test_items_list_and_search():
    async def body():
        objs = [
            Item(market_hash_name="AK-47 | Redline (Field-Tested)", name="AK红线"),
            Item(market_hash_name="AWP | Asiimov (Field-Tested)", name="AWP阿西莫夫"),
        ]
        async with asgi_client(seed=_seeder(objs), routers=ITEMS) as (client, _):
            alld = (await client.get("/api/items/")).json()
            assert alld["total"] == 2
            # 中文名模糊搜索
            hit = (await client.get("/api/items/", params={"q": "红线"})).json()
            assert hit["total"] == 1
            assert hit["data"][0]["name"] == "AK红线"
            # marketHashName 搜索
            hit2 = (await client.get("/api/items/", params={"q": "AWP"})).json()
            assert hit2["total"] == 1
    _run(body())


def test_items_pagination():
    async def body():
        objs = [Item(market_hash_name=f"Item {i:02d}", name=f"物品{i}") for i in range(5)]
        async with asgi_client(seed=_seeder(objs), routers=ITEMS) as (client, _):
            d = (await client.get("/api/items/", params={"limit": 2, "offset": 0})).json()
            assert d["total"] == 5 and len(d["data"]) == 2
            assert d["limit"] == 2 and d["offset"] == 0
    _run(body())


def test_items_limit_out_of_range_422():
    async def body():
        async with asgi_client(routers=ITEMS) as (client, _):
            assert (await client.get("/api/items/", params={"limit": 0})).status_code == 422
            assert (await client.get("/api/items/", params={"limit": 999})).status_code == 422
            assert (await client.get("/api/items/", params={"offset": -1})).status_code == 422
    _run(body())


# ── prices GET /cached ─────────────────────────────────────────────────────

PRICES = [(prices_route.router, "/api/prices")]


def test_prices_cached_no_data():
    async def body():
        async with asgi_client(routers=PRICES) as (client, _):
            d = (await client.get("/api/prices/cached", params={"market_hash_name": "X"})).json()
            assert d["data"] == []
            assert "message" in d
    _run(body())


def test_prices_cached_returns_latest_minute():
    async def body():
        objs = [
            PriceSnapshot(market_hash_name="A", platform="YOUPIN", sell_price=10.0, snapshot_minute="202606080000"),
            PriceSnapshot(market_hash_name="A", platform="BUFF", sell_price=9.0, snapshot_minute="202606080100"),
            PriceSnapshot(market_hash_name="A", platform="YOUPIN", sell_price=11.0, snapshot_minute="202606080100"),
        ]
        async with asgi_client(seed=_seeder(objs), routers=PRICES) as (client, _):
            d = (await client.get("/api/prices/cached", params={"market_hash_name": "A"})).json()
            assert d["snapshot_minute"] == "202606080100"  # 最新分钟
            assert len(d["data"]) == 2                      # 该分钟两平台
            platforms = {row["platform"] for row in d["data"]}
            assert platforms == {"BUFF", "YOUPIN"}
    _run(body())


def test_prices_cached_missing_param_422():
    async def body():
        async with asgi_client(routers=PRICES) as (client, _):
            assert (await client.get("/api/prices/cached")).status_code == 422
    _run(body())


# ── tracker GET (daily / monthly / export) ─────────────────────────────────

TRACKER = [(tracker_route.router, "/api/tracker")]


def test_tracker_daily_route():
    async def body():
        objs = [DailyTracker(date="2026-06-01", daily_income=10.0),
                DailyTracker(date="2026-06-02", daily_income=20.0)]
        async with asgi_client(seed=_seeder(objs), routers=TRACKER) as (client, _):
            d = (await client.get("/api/tracker/daily")).json()
            assert [r["date"] for r in d] == ["2026-06-02", "2026-06-01"]  # 倒序
            # 范围过滤
            d2 = (await client.get("/api/tracker/daily", params={"start": "2026-06-02"})).json()
            assert [r["date"] for r in d2] == ["2026-06-02"]
    _run(body())


def test_tracker_monthly_specific():
    async def body():
        objs = [DailyTracker(date="2026-06-01", daily_income=100.0, is_vip=True, inventory_value=1.0)]
        async with asgi_client(seed=_seeder(objs), routers=TRACKER) as (client, _):
            d = (await client.get("/api/tracker/monthly", params={"year": 2026, "month": 6})).json()
            assert d["year"] == 2026 and d["month"] == 6 and d["days"] == 1
    _run(body())


def test_tracker_monthly_year_only_returns_list():
    async def body():
        objs = [DailyTracker(date="2026-01-15", daily_income=5.0, is_vip=True, inventory_value=1.0),
                DailyTracker(date="2026-02-15", daily_income=5.0, is_vip=True, inventory_value=1.0)]
        async with asgi_client(seed=_seeder(objs), routers=TRACKER) as (client, _):
            d = (await client.get("/api/tracker/monthly", params={"year": 2026})).json()
            assert isinstance(d, list)
            months = {m["month"] for m in d}
            assert {1, 2}.issubset(months)
    _run(body())


def test_tracker_export_xlsx():
    async def body():
        objs = [DailyTracker(date="2026-06-01", rented_count=10, daily_income=5.0)]
        async with asgi_client(seed=_seeder(objs), routers=TRACKER) as (client, _):
            r = await client.get("/api/tracker/export")
            assert r.status_code == 200
            assert "spreadsheetml" in r.headers.get("content-type", "")
            assert len(r.content) > 0
    _run(body())


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
