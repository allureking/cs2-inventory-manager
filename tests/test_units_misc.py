"""
零散纯函数 / DB 工具单测：
  - youpin_listing._normalize_shelf_item：货架原始字段 → 前端字段映射
  - steamdt.get_latest_snapshots：取某饰品最新一分钟的快照（DB-only）
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from app.services.youpin_listing import _normalize_shelf_item
from app.services.steamdt import get_latest_snapshots
from app.models.db_models import PriceSnapshot
from tests.conftest import memory_db


def _run(coro):
    return asyncio.run(coro)


# ── _normalize_shelf_item ──────────────────────────────────────────────────


class TestNormalizeShelfItem:
    def test_full_mapping(self):
        raw = {
            "id": 123, "templateId": 456, "name": "AK红线", "commodityHashName": "AK-47 | Redline",
            "abrade": "0.2", "imgUrl": "u", "sellAmount": 100.0,
            "shortLeaseAmount": 1.5, "longLeaseAmount": 1.2, "depositAmount": 50.0,
            "leaseMaxDays": 30, "openSublet": True, "orderId": "o1", "steamAssetId": "s1",
            "status": 1, "canLease": True, "commodityCanSell": True,
        }
        r = _normalize_shelf_item(raw)
        assert r["commodityId"] == 123
        assert r["templateId"] == 456
        assert r["price"] == 100.0                # sellAmount → price
        assert r["leaseUnitPrice"] == 1.5         # shortLeaseAmount
        assert r["longLeasePrice"] == 1.2
        assert r["leaseDeposit"] == 50.0
        assert r["canSell"] is True               # commodityCanSell → canSell
        assert r["openSublet"] is True

    def test_missing_keys_become_none(self):
        r = _normalize_shelf_item({})
        # 所有字段存在但为 None（统一结构,前端不会 KeyError）
        for k in ("commodityId", "price", "leaseUnitPrice", "leaseDeposit", "canSell", "status"):
            assert k in r and r[k] is None

    def test_does_not_crash_on_partial(self):
        r = _normalize_shelf_item({"id": 1, "sellAmount": 9.9})
        assert r["commodityId"] == 1 and r["price"] == 9.9
        assert r["leaseUnitPrice"] is None


# ── steamdt.get_latest_snapshots ───────────────────────────────────────────


class TestGetLatestSnapshots:
    def test_no_data(self):
        async def body():
            async with memory_db() as Session:
                async with Session() as db:
                    assert await get_latest_snapshots("X", db) == []
        _run(body())

    def test_returns_only_latest_minute(self):
        async def body():
            async with memory_db() as Session:
                async with Session() as db:
                    for r in [
                        PriceSnapshot(market_hash_name="A", platform="YOUPIN", sell_price=1.0, snapshot_minute="202606080000"),
                        PriceSnapshot(market_hash_name="A", platform="YOUPIN", sell_price=2.0, snapshot_minute="202606080100"),
                        PriceSnapshot(market_hash_name="A", platform="BUFF", sell_price=3.0, snapshot_minute="202606080100"),
                        PriceSnapshot(market_hash_name="B", platform="YOUPIN", sell_price=9.0, snapshot_minute="202606080100"),
                    ]:
                        db.add(r)
                    await db.commit()
                    rows = await get_latest_snapshots("A", db)
                    assert len(rows) == 2  # 仅最新分钟 0100 的两条
                    assert all(s.snapshot_minute == "202606080100" for s in rows)
                    assert {s.platform for s in rows} == {"YOUPIN", "BUFF"}
        _run(body())

    def test_isolated_by_name(self):
        async def body():
            async with memory_db() as Session:
                async with Session() as db:
                    db.add(PriceSnapshot(market_hash_name="A", platform="YOUPIN", sell_price=1.0, snapshot_minute="202606080100"))
                    db.add(PriceSnapshot(market_hash_name="B", platform="YOUPIN", sell_price=2.0, snapshot_minute="202606080100"))
                    await db.commit()
                    rows = await get_latest_snapshots("A", db)
                    assert len(rows) == 1 and rows[0].market_hash_name == "A"
        _run(body())


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
