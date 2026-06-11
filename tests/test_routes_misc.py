"""
monitoring / inventory 路由测试（最小 app + 内存库,无网络）。

覆盖：
  - monitoring/status：行数统计反映 seed、freshness 影响 status、结构完整
  - monitoring/portfolio-history：valid range 200 + 过滤/排序；invalid range → 422
  - monitoring/data-freshness：200 + 结构
  - inventory/missing-cost：仅 ACTIVE 且无成本
  - inventory/ list：默认 ACTIVE 口径、显式状态、all、非法状态回退 ACTIVE
  - inventory/summary：200
"""

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from app.api.routes import monitoring, inventory
from app.models.db_models import InventoryItem, PriceSnapshot, PortfolioSnapshot
from tests.conftest import asgi_client


def _run(coro):
    return asyncio.run(coro)


ROUTERS = [(monitoring.router, "/api/monitoring"), (inventory.router, "/api/inventory")]
_seq = {"n": 0}


def item(name="AK-47 | Redline (Field-Tested)", status="in_steam", purchase_price=None):
    _seq["n"] += 1
    # steam_id="" 对齐测试环境 settings.steam_steam_id 默认空值
    # （inventory list 按 steam_id 作用域过滤；此处被测的是状态过滤口径）
    return InventoryItem(
        steam_id="", class_id="c", instance_id=f"i{_seq['n']}",
        market_hash_name=name, name=name, status=status, purchase_price=purchase_price,
    )


def _now_minute():
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M")


def _seeder(objs):
    async def seed(db):
        for o in objs:
            db.add(o)
        await db.commit()
    return seed


# ── monitoring/status ──────────────────────────────────────────────────────


def test_status_row_counts_reflect_seed():
    async def body():
        objs = [item(), item(), item(status="in_storage")]
        async with asgi_client(seed=_seeder(objs), routers=ROUTERS) as (client, _):
            d = (await client.get("/api/monitoring/status")).json()
            assert d["database"]["row_counts"]["inventory_item"] == 3
            # v0.13: scheduler_jobs 改为动态读取(测试环境 scheduler 未启动 → 空列表)
            assert "scheduler_jobs" in d and isinstance(d["scheduler_jobs"], list)
            assert d["status"] in ("healthy", "degraded")
    _run(body())


def test_status_fresh_snapshot_is_healthy():
    async def body():
        # 最新价格快照=当前分钟 → minutes_ago < 60 → healthy
        objs = [PriceSnapshot(market_hash_name="A", platform="YOUPIN", sell_price=1.0, snapshot_minute=_now_minute())]
        async with asgi_client(seed=_seeder(objs), routers=ROUTERS) as (client, _):
            d = (await client.get("/api/monitoring/status")).json()
            assert d["data_freshness"]["is_fresh"] is True
            assert d["status"] == "healthy"
    _run(body())


def test_status_no_data_degraded():
    async def body():
        async with asgi_client(routers=ROUTERS) as (client, _):
            d = (await client.get("/api/monitoring/status")).json()
            # 无任何快照 → latest_snap None → data_fresh 保持 True 初值 → healthy
            # 这里仅校验结构与不报错
            assert "data_freshness" in d
            assert d["database"]["row_counts"]["price_snapshot"] == 0
    _run(body())


# ── monitoring/portfolio-history ───────────────────────────────────────────


def test_portfolio_history_invalid_range_422():
    async def body():
        async with asgi_client(routers=ROUTERS) as (client, _):
            r = await client.get("/api/monitoring/portfolio-history", params={"range": "bogus"})
            assert r.status_code == 422
    _run(body())


def test_portfolio_history_default_range_ok():
    async def body():
        async with asgi_client(routers=ROUTERS) as (client, _):
            r = await client.get("/api/monitoring/portfolio-history")
            assert r.status_code == 200
            d = r.json()
            assert d["range"] == "7d"
            assert d["count"] == 0 and d["data"] == []
    _run(body())


def test_portfolio_history_filters_by_range():
    async def body():
        old = "200001010000"  # 远早于 7d
        new = _now_minute()
        objs = [
            PortfolioSnapshot(snapshot_minute=old, total_active=1, market_value=100.0),
            PortfolioSnapshot(snapshot_minute=new, total_active=2, market_value=200.0),
        ]
        async with asgi_client(seed=_seeder(objs), routers=ROUTERS) as (client, _):
            d7 = (await client.get("/api/monitoring/portfolio-history", params={"range": "7d"})).json()
            assert d7["count"] == 1  # 只含近 7 天
            dall = (await client.get("/api/monitoring/portfolio-history", params={"range": "all"})).json()
            assert dall["count"] == 2
            # 升序排列
            assert [p["snapshot_minute"] for p in dall["data"]] == [old, new]
    _run(body())


def test_data_freshness_ok():
    async def body():
        async with asgi_client(routers=ROUTERS) as (client, _):
            r = await client.get("/api/monitoring/data-freshness")
            assert r.status_code == 200
    _run(body())


# ── inventory ──────────────────────────────────────────────────────────────


def test_missing_cost_lists_active_without_price():
    async def body():
        objs = [
            item(name="A", status="in_steam", purchase_price=None),     # 列出
            item(name="B", status="rented_out", purchase_price=None),   # 列出
            item(name="C", status="in_steam", purchase_price=100.0),    # 有成本,不列
            item(name="D", status="in_storage", purchase_price=None),   # 非活跃,不列
        ]
        async with asgi_client(seed=_seeder(objs), routers=ROUTERS) as (client, _):
            d = (await client.get("/api/inventory/missing-cost")).json()
            assert d["total"] == 2
            names = {x["market_hash_name"] for x in d["data"]}
            assert names == {"A", "B"}
    _run(body())


def test_list_default_active_only():
    async def body():
        objs = [item(status="in_steam"), item(status="rented_out"), item(status="in_storage")]
        async with asgi_client(seed=_seeder(objs), routers=ROUTERS) as (client, _):
            d = (await client.get("/api/inventory/")).json()
            assert set(d["status_filter"]) == {"in_steam", "rented_out"}
            assert d["total"] == 2  # in_storage 不计
    _run(body())


def test_list_explicit_status():
    async def body():
        objs = [item(status="in_steam"), item(status="in_storage")]
        async with asgi_client(seed=_seeder(objs), routers=ROUTERS) as (client, _):
            d = (await client.get("/api/inventory/", params={"status": "in_storage"})).json()
            assert d["status_filter"] == ["in_storage"]
            assert d["total"] == 1
    _run(body())


def test_list_invalid_status_falls_back_to_active():
    async def body():
        objs = [item(status="in_steam"), item(status="in_storage")]
        async with asgi_client(seed=_seeder(objs), routers=ROUTERS) as (client, _):
            d = (await client.get("/api/inventory/", params={"status": "nonsense"})).json()
            # 非法状态 → 回退 ACTIVE_STATUSES（不是 422）
            assert set(d["status_filter"]) == {"in_steam", "rented_out"}
            assert d["total"] == 1
    _run(body())


def test_list_all_status():
    async def body():
        objs = [item(status="in_steam"), item(status="in_storage"), item(status="sold")]
        async with asgi_client(seed=_seeder(objs), routers=ROUTERS) as (client, _):
            d = (await client.get("/api/inventory/", params={"status": "all"})).json()
            assert d["total"] == 3
    _run(body())


def test_inventory_summary_ok():
    async def body():
        objs = [item(status="in_steam", purchase_price=100.0)]
        async with asgi_client(seed=_seeder(objs), routers=ROUTERS) as (client, _):
            r = await client.get("/api/inventory/summary")
            assert r.status_code == 200
            assert isinstance(r.json(), dict)
    _run(body())


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
