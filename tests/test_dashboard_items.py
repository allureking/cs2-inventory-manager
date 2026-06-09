"""
dashboard /items 列表 + manual-price 测试（DB，经 ASGI，内存库，无网络）。

  - 分页/边界 422、search、status 过滤(始终排除 unknown)、priced_filter、category、
    sort(effective_price 升降 + manual 覆盖优先)、current_price 排序(price 关联)、
    逐件 current_price/pnl 计算
  - manual-price：设置 / 清除(null) / 404
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from app.api.routes import dashboard as dash_route
from app.models.db_models import InventoryItem, PriceSnapshot
from tests.conftest import asgi_client

ROUTERS = [(dash_route.router, "/api/dashboard")]
_seq = {"n": 0}


def _run(coro):
    return asyncio.run(coro)


def item(name="AK-47 | Redline (Field-Tested)", status="in_steam", purchase_price=None,
         manual=None, item_type=None):
    _seq["n"] += 1
    return InventoryItem(
        steam_id="", class_id="c", instance_id=f"i{_seq['n']}",
        market_hash_name=name, name=name, status=status,
        purchase_price=purchase_price, purchase_price_manual=manual, item_type=item_type,
    )


def snap(name, sell_price, minute="202606080000", platform="YOUPIN"):
    return PriceSnapshot(market_hash_name=name, platform=platform, sell_price=sell_price, snapshot_minute=minute)


def _seeder(objs):
    async def seed(db):
        for o in objs:
            db.add(o)
        await db.commit()
    return seed


def test_items_empty():
    async def body():
        async with asgi_client(routers=ROUTERS) as (client, _):
            d = (await client.get("/api/dashboard/items")).json()
            assert d["total"] == 0 and d["items"] == []
    _run(body())


def test_items_pagination_and_bounds():
    async def body():
        objs = [item(name=f"AK-47 | Skin {i}") for i in range(5)]
        async with asgi_client(seed=_seeder(objs), routers=ROUTERS) as (client, _):
            d = (await client.get("/api/dashboard/items", params={"page": 1, "page_size": 2})).json()
            assert d["total"] == 5 and len(d["items"]) == 2
            assert (await client.get("/api/dashboard/items", params={"page": 0})).status_code == 422
            assert (await client.get("/api/dashboard/items", params={"page_size": 201})).status_code == 422
    _run(body())


def test_items_excludes_unknown_status():
    async def body():
        objs = [item(status="in_steam"), item(status="unknown")]
        async with asgi_client(seed=_seeder(objs), routers=ROUTERS) as (client, _):
            d = (await client.get("/api/dashboard/items")).json()
            assert d["total"] == 1  # unknown 永远排除
    _run(body())


def test_items_status_filter():
    async def body():
        objs = [item(status="in_steam"), item(status="rented_out"), item(status="sold")]
        async with asgi_client(seed=_seeder(objs), routers=ROUTERS) as (client, _):
            d = (await client.get("/api/dashboard/items", params={"status": "rented_out"})).json()
            assert d["total"] == 1 and d["items"][0]["status"] == "rented_out"
    _run(body())


def test_items_search():
    async def body():
        objs = [item(name="AK-47 | Redline (Field-Tested)"), item(name="AWP | Asiimov (Field-Tested)")]
        async with asgi_client(seed=_seeder(objs), routers=ROUTERS) as (client, _):
            d = (await client.get("/api/dashboard/items", params={"search": "AWP"})).json()
            assert d["total"] == 1
    _run(body())


def test_items_priced_filter():
    async def body():
        objs = [item(name="AK-47 | A", purchase_price=100.0), item(name="AK-47 | B")]
        async with asgi_client(seed=_seeder(objs), routers=ROUTERS) as (client, _):
            priced = (await client.get("/api/dashboard/items", params={"priced_filter": "priced"})).json()
            unpriced = (await client.get("/api/dashboard/items", params={"priced_filter": "unpriced"})).json()
            assert priced["total"] == 1 and unpriced["total"] == 1
    _run(body())


def test_items_category_rifle():
    async def body():
        objs = [item(name="AK-47 | Redline (Field-Tested)"), item(name="AWP | Asiimov (Field-Tested)")]
        async with asgi_client(seed=_seeder(objs), routers=ROUTERS) as (client, _):
            d = (await client.get("/api/dashboard/items", params={"category": "rifle"})).json()
            # AK-47 属 rifle；AWP 属 sniper → 仅 1
            assert d["total"] == 1 and d["items"][0]["market_hash_name"].startswith("AK-47")
    _run(body())


def test_items_sort_effective_price_with_manual_override():
    async def body():
        # X: purchase 100; Y: purchase 999 但 manual 1 → effective 1 最低
        objs = [item(name="AK-47 | X", purchase_price=100.0),
                item(name="AK-47 | Y", purchase_price=999.0, manual=1.0)]
        async with asgi_client(seed=_seeder(objs), routers=ROUTERS) as (client, _):
            d = (await client.get("/api/dashboard/items",
                                  params={"sort_by": "effective_price", "sort_order": "asc"})).json()
            # effective 升序：Y(1) 在前
            assert d["items"][0]["market_hash_name"] == "AK-47 | Y"
            assert d["items"][0]["effective_price"] == 1.0
    _run(body())


def test_items_pnl_computation():
    async def body():
        objs = [item(name="AK-47 | P", purchase_price=100.0), snap("AK-47 | P", 150.0)]
        async with asgi_client(seed=_seeder(objs), routers=ROUTERS) as (client, _):
            d = (await client.get("/api/dashboard/items")).json()
            row = d["items"][0]
            assert row["current_price"] == 150.0
            assert row["pnl"] == 50.0
            assert row["pnl_pct"] == 50.0
    _run(body())


def test_items_sort_by_current_price():
    async def body():
        objs = [item(name="AK-47 | Lo"), item(name="AK-47 | Hi"),
                snap("AK-47 | Lo", 10.0), snap("AK-47 | Hi", 9000.0)]
        async with asgi_client(seed=_seeder(objs), routers=ROUTERS) as (client, _):
            d = (await client.get("/api/dashboard/items",
                                  params={"sort_by": "current_price", "sort_order": "desc"})).json()
            assert d["items"][0]["market_hash_name"] == "AK-47 | Hi"
    _run(body())


# ── manual-price ────────────────────────────────────────────────────────────


def test_manual_price_set_and_clear():
    async def body():
        async with asgi_client(seed=_seeder([item(name="AK-47 | M", purchase_price=100.0)]), routers=ROUTERS) as (client, S):
            # 取 id
            lst = (await client.get("/api/dashboard/items")).json()["items"]
            iid = lst[0]["id"]
            # 设置 manual
            r = await client.patch(f"/api/dashboard/items/{iid}/manual-price", json={"price": 80.0})
            assert r.status_code == 200
            assert r.json()["purchase_price_manual"] == 80.0
            assert r.json()["effective_price"] == 80.0
            # 清除 manual(null) → effective 回退 purchase_price
            r2 = await client.patch(f"/api/dashboard/items/{iid}/manual-price", json={"price": None})
            assert r2.json()["purchase_price_manual"] is None
            assert r2.json()["effective_price"] == 100.0
    _run(body())


def test_manual_price_404():
    async def body():
        async with asgi_client(routers=ROUTERS) as (client, _):
            r = await client.patch("/api/dashboard/items/99999/manual-price", json={"price": 1.0})
            assert r.status_code == 404
    _run(body())


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
