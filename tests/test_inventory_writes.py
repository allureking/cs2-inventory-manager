"""
inventory 写端点测试（DB 写，经 ASGI，内存库，无网络）。

  - PATCH /{asset_id}/cost：成功写入 / 404
  - POST  /bulk-cost：部分命中 + not_found
  - PATCH /{asset_id}/status：成功 / 非法状态 400 / 404
  - POST  /refresh-prices：非法 status 400 / 无匹配物品早返回（不触发外部 batch 拉价）
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from app.api.routes import inventory as inv_route
from app.models.db_models import InventoryItem
from tests.conftest import asgi_client

ROUTERS = [(inv_route.router, "/api/inventory")]
_seq = {"n": 0}


def _run(coro):
    return asyncio.run(coro)


def item(asset_id, name="AK-47 | Redline (Field-Tested)", status="in_steam", purchase_price=None):
    _seq["n"] += 1
    return InventoryItem(
        steam_id="", class_id="c", instance_id=f"i{_seq['n']}", asset_id=asset_id,
        market_hash_name=name, name=name, status=status, purchase_price=purchase_price,
    )


def _seeder(objs):
    async def seed(db):
        for o in objs:
            db.add(o)
        await db.commit()
    return seed


# ── PATCH /{asset_id}/cost ──────────────────────────────────────────────────


def test_patch_cost_success():
    async def body():
        async with asgi_client(seed=_seeder([item("A1")]), routers=ROUTERS) as (client, _):
            r = await client.patch("/api/inventory/A1/cost",
                                   json={"purchase_price": 3200.0, "purchase_date": "2024-11-20", "purchase_platform": "BUFF"})
            assert r.status_code == 200
            d = r.json()
            assert d["purchase_price"] == 3200.0
            assert d["purchase_date"] == "2024-11-20"
            assert d["purchase_platform"] == "BUFF"
    _run(body())


def test_patch_cost_404():
    async def body():
        async with asgi_client(routers=ROUTERS) as (client, _):
            r = await client.patch("/api/inventory/NOPE/cost", json={"purchase_price": 1.0})
            assert r.status_code == 404
    _run(body())


def test_patch_cost_missing_price_422():
    async def body():
        async with asgi_client(seed=_seeder([item("A1")]), routers=ROUTERS) as (client, _):
            r = await client.patch("/api/inventory/A1/cost", json={})
            assert r.status_code == 422  # purchase_price 必填
    _run(body())


# ── POST /bulk-cost ─────────────────────────────────────────────────────────


def test_bulk_cost_partial():
    async def body():
        objs = [item("A1"), item("A2")]
        async with asgi_client(seed=_seeder(objs), routers=ROUTERS) as (client, _):
            r = await client.post("/api/inventory/bulk-cost", json={"items": [
                {"asset_id": "A1", "purchase_price": 100.0},
                {"asset_id": "A2", "purchase_price": 200.0},
                {"asset_id": "MISSING", "purchase_price": 999.0},
            ]})
            assert r.status_code == 200
            d = r.json()
            assert d["updated"] == 2
            assert d["not_found"] == ["MISSING"]
    _run(body())


# ── PATCH /{asset_id}/status ────────────────────────────────────────────────


def test_patch_status_success():
    async def body():
        async with asgi_client(seed=_seeder([item("A1", status="rented_out")]), routers=ROUTERS) as (client, _):
            r = await client.patch("/api/inventory/A1/status", json={"status": "sold"})
            assert r.status_code == 200
            d = r.json()
            assert d["old_status"] == "rented_out" and d["new_status"] == "sold"
    _run(body())


def test_patch_status_invalid_400():
    async def body():
        async with asgi_client(seed=_seeder([item("A1")]), routers=ROUTERS) as (client, _):
            r = await client.patch("/api/inventory/A1/status", json={"status": "bogus"})
            assert r.status_code == 400
    _run(body())


def test_patch_status_404():
    async def body():
        async with asgi_client(routers=ROUTERS) as (client, _):
            r = await client.patch("/api/inventory/NOPE/status", json={"status": "sold"})
            assert r.status_code == 404
    _run(body())


# ── POST /refresh-prices（仅校验/早返回分支,不触发外部拉价）────────────────────


def test_refresh_prices_invalid_status_400():
    async def body():
        async with asgi_client(routers=ROUTERS) as (client, _):
            r = await client.post("/api/inventory/refresh-prices", params={"status": "nonsense"})
            assert r.status_code == 400
    _run(body())


def test_refresh_prices_no_items_early_return():
    async def body():
        # status 合法但库存为空 → 不调用外部 batch,返回 total 0
        async with asgi_client(routers=ROUTERS) as (client, _):
            r = await client.post("/api/inventory/refresh-prices", params={"status": "in_steam"})
            assert r.status_code == 200
            assert r.json()["total"] == 0
    _run(body())


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
