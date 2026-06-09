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
