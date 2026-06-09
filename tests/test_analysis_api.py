"""
analysis 路由测试（DB-read 端点，经 ASGI，内存库，无网络）。

覆盖：
  - /overview：空(signal_date None)+ 有信号(avg/分布,仅持仓口径)
  - /alerts：空/严重度过滤/未读过滤/分页；PATCH read；POST read-all
  - /search-items：q 空(按信号)+ q 名称模糊；limit 422
  - /rankings：无信号→空
  - /categories：无信号→空
  - /price-history：必填参数 422 / days 范围 422 / 空结构
  - /collector/status、/csqaq-status：状态字典 smoke

外部计算端点(/backfill /compute-now /csqaq-sync)调度后台任务/外部 API,
不在单测范围 —— 见 REPORT.md §2。
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from app.api.routes import analysis as analysis_route
from app.models.db_models import QuantAlert, QuantSignal, InventoryItem, PriceHistory
from tests.conftest import asgi_client

ROUTERS = [(analysis_route.router, "/api/analysis")]
_seq = {"n": 0}


def _run(coro):
    return asyncio.run(coro)


def _seeder(objs):
    async def seed(db):
        for o in objs:
            db.add(o)
        await db.commit()
    return seed


def inv(name, status="in_steam", icon_url=None):
    _seq["n"] += 1
    return InventoryItem(steam_id="", class_id="c", instance_id=f"i{_seq['n']}",
                         market_hash_name=name, name=name, status=status, icon_url=icon_url)


def alert(severity="warning", alert_type="pnl", is_read=False, title="t", name="A"):
    return QuantAlert(market_hash_name=name, alert_type=alert_type, severity=severity,
                      title=title, is_read=is_read)


def signal(name="A", date="20260608", sell_score=80.0, momentum_30=5.0):
    return QuantSignal(market_hash_name=name, signal_date=date, sell_score=sell_score, momentum_30=momentum_30)


# ── /overview ──────────────────────────────────────────────────────────────


def test_overview_empty():
    async def body():
        async with asgi_client(routers=ROUTERS) as (client, _):
            d = (await client.get("/api/analysis/overview")).json()
            assert d["signal_date"] is None
            assert d["score_distribution"] == [0, 0, 0, 0, 0]
            assert d["top_sell"] == []
            assert d["avg_sell_score"] is None
    _run(body())


def test_overview_unread_count():
    async def body():
        objs = [alert(is_read=False), alert(is_read=False), alert(is_read=True)]
        async with asgi_client(seed=_seeder(objs), routers=ROUTERS) as (client, _):
            d = (await client.get("/api/analysis/overview")).json()
            assert d["unread_alerts"] == 2
    _run(body())


def test_overview_with_owned_signal():
    async def body():
        objs = [inv("A", status="in_steam"), signal(name="A", sell_score=88.0, momentum_30=10.0)]
        async with asgi_client(seed=_seeder(objs), routers=ROUTERS) as (client, _):
            d = (await client.get("/api/analysis/overview")).json()
            assert d["signal_date"] == "20260608"
            assert d["avg_sell_score"] == 88.0
            # sell_score 88 → 落在 85-100 桶（最后一个）
            assert d["score_distribution"][4] == 1
    _run(body())


def test_overview_ignores_unowned_signal():
    async def body():
        # 信号物品未持有 → 不计入 avg（持仓口径）
        objs = [signal(name="NOTOWNED", sell_score=88.0)]
        async with asgi_client(seed=_seeder(objs), routers=ROUTERS) as (client, _):
            d = (await client.get("/api/analysis/overview")).json()
            assert d["avg_sell_score"] is None
    _run(body())


# ── /alerts ────────────────────────────────────────────────────────────────


def test_alerts_empty():
    async def body():
        async with asgi_client(routers=ROUTERS) as (client, _):
            d = (await client.get("/api/analysis/alerts")).json()
            assert d["total"] == 0 and d["items"] == []
    _run(body())


def test_alerts_severity_filter():
    async def body():
        objs = [alert(severity="critical"), alert(severity="warning"), alert(severity="warning")]
        async with asgi_client(seed=_seeder(objs), routers=ROUTERS) as (client, _):
            d = (await client.get("/api/analysis/alerts", params={"severity": "warning"})).json()
            assert d["total"] == 2
            assert all(a["severity"] == "warning" for a in d["items"])
    _run(body())


def test_alerts_unread_only():
    async def body():
        objs = [alert(is_read=False), alert(is_read=True)]
        async with asgi_client(seed=_seeder(objs), routers=ROUTERS) as (client, _):
            d = (await client.get("/api/analysis/alerts", params={"unread_only": "true"})).json()
            assert d["total"] == 1
            assert d["items"][0]["is_read"] is False
    _run(body())


def test_alerts_pagination_bounds_422():
    async def body():
        async with asgi_client(routers=ROUTERS) as (client, _):
            assert (await client.get("/api/analysis/alerts", params={"page": 0})).status_code == 422
            assert (await client.get("/api/analysis/alerts", params={"page_size": 101})).status_code == 422
    _run(body())


def test_alerts_mark_read_and_read_all():
    async def body():
        objs = [alert(is_read=False), alert(is_read=False), alert(is_read=False)]
        async with asgi_client(seed=_seeder(objs), routers=ROUTERS) as (client, S):
            # 先取一个 id
            listed = (await client.get("/api/analysis/alerts")).json()["items"]
            first_id = listed[0]["id"]
            r = await client.patch(f"/api/analysis/alerts/{first_id}/read")
            assert r.status_code == 200 and r.json()["ok"] is True
            # read-all
            ra = (await client.post("/api/analysis/alerts/read-all")).json()
            assert ra["ok"] is True
            # 之后未读为 0
            unread = (await client.get("/api/analysis/alerts", params={"unread_only": "true"})).json()
            assert unread["total"] == 0
    _run(body())


# ── /search-items ──────────────────────────────────────────────────────────


def test_search_items_by_name():
    async def body():
        objs = [inv("AK-47 | Redline (Field-Tested)"), inv("AWP | Asiimov (Field-Tested)")]
        async with asgi_client(seed=_seeder(objs), routers=ROUTERS) as (client, _):
            d = (await client.get("/api/analysis/search-items", params={"q": "Redline"})).json()
            assert len(d["items"]) == 1
            assert d["items"][0]["market_hash_name"].startswith("AK-47")
    _run(body())


def test_search_items_empty_q_uses_signals():
    async def body():
        objs = [inv("A"), signal(name="A", sell_score=70.0)]
        async with asgi_client(seed=_seeder(objs), routers=ROUTERS) as (client, _):
            d = (await client.get("/api/analysis/search-items", params={"q": ""})).json()
            assert d["items"] and d["items"][0]["market_hash_name"] == "A"
    _run(body())


def test_search_items_limit_422():
    async def body():
        async with asgi_client(routers=ROUTERS) as (client, _):
            assert (await client.get("/api/analysis/search-items", params={"limit": 99})).status_code == 422
    _run(body())


# ── /rankings, /categories ─────────────────────────────────────────────────


def test_rankings_empty():
    async def body():
        async with asgi_client(routers=ROUTERS) as (client, _):
            d = (await client.get("/api/analysis/rankings")).json()
            assert d == {"items": [], "total": 0, "signal_date": None}
    _run(body())


def test_categories_empty():
    async def body():
        async with asgi_client(routers=ROUTERS) as (client, _):
            d = (await client.get("/api/analysis/categories")).json()
            assert d == {"categories": [], "signal_date": None}
    _run(body())


# ── /price-history ─────────────────────────────────────────────────────────


def test_price_history_missing_name_422():
    async def body():
        async with asgi_client(routers=ROUTERS) as (client, _):
            assert (await client.get("/api/analysis/price-history")).status_code == 422
    _run(body())


def test_price_history_days_range_422():
    async def body():
        async with asgi_client(routers=ROUTERS) as (client, _):
            r = await client.get("/api/analysis/price-history", params={"market_hash_name": "A", "days": 5})
            assert r.status_code == 422
    _run(body())


def test_price_history_empty_ok():
    async def body():
        async with asgi_client(routers=ROUTERS) as (client, _):
            r = await client.get("/api/analysis/price-history", params={"market_hash_name": "A"})
            assert r.status_code == 200
    _run(body())


# ── status 端点(状态字典 smoke) ─────────────────────────────────────────────


def test_collector_status_smoke():
    async def body():
        async with asgi_client(routers=ROUTERS) as (client, _):
            d = (await client.get("/api/analysis/collector/status")).json()
            assert "collector" in d and "backfill" in d
    _run(body())


def test_csqaq_status_smoke():
    async def body():
        async with asgi_client(routers=ROUTERS) as (client, _):
            r = await client.get("/api/analysis/csqaq-status")
            assert r.status_code == 200
    _run(body())


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
