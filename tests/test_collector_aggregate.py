"""
collector.py 的纯 DB 部分测试：aggregate_daily（OHLC 聚合）+ cleanup_old_snapshots。
（采价/快照编排依赖外部 SteamDT/悠悠,见 REPORT §2 故意不覆盖。）

这些函数用全局 AsyncSessionLocal,测试时把模块属性 patch 到内存库 sessionmaker,
并直接 await 调用（不经 ASGI）。
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from sqlalchemy import select

import app.services.collector as collector
from app.models.db_models import PriceSnapshot, PriceHistory
from tests.conftest import memory_db


def _run(coro):
    return asyncio.run(coro)


def snap(name, platform, sell_price, minute, sell_count=None):
    return PriceSnapshot(market_hash_name=name, platform=platform, sell_price=sell_price,
                         snapshot_minute=minute, sell_count=sell_count)


# ── aggregate_daily ────────────────────────────────────────────────────────


def test_aggregate_daily_ohlc():
    async def body():
        async with memory_db() as Session:
            orig = collector.AsyncSessionLocal
            collector.AsyncSessionLocal = Session
            try:
                async with Session() as db:
                    # date 20260608, A/BUFF: open=100(08:00) high=120 low=90 close=90(16:00)
                    db.add_all([
                        snap("A", "BUFF", 100.0, "202606080800", sell_count=5),
                        snap("A", "BUFF", 120.0, "202606081200"),
                        snap("A", "BUFF", 90.0, "202606081600", sell_count=7),
                    ])
                    await db.commit()
                n = await collector.aggregate_daily("20260608")
                assert n >= 1
                async with Session() as db:
                    rows = (await db.execute(select(PriceHistory))).scalars().all()
                    by = {(r.market_hash_name, r.platform): r for r in rows}
                    h = by[("A", "BUFF")]
                    assert h.record_date == "20260608"
                    assert h.open_price == 100.0
                    assert h.close_price == 90.0
                    assert h.high_price == 120.0
                    assert h.low_price == 90.0
            finally:
                collector.AsyncSessionLocal = orig
    _run(body())


def test_aggregate_daily_excludes_other_dates():
    async def body():
        async with memory_db() as Session:
            orig = collector.AsyncSessionLocal
            collector.AsyncSessionLocal = Session
            try:
                async with Session() as db:
                    db.add_all([
                        snap("A", "BUFF", 100.0, "202606080800"),
                        snap("A", "BUFF", 555.0, "202606070800"),  # 前一天,不应进入
                    ])
                    await db.commit()
                await collector.aggregate_daily("20260608")
                async with Session() as db:
                    rows = (await db.execute(select(PriceHistory))).scalars().all()
                    # BUFF 行 + 合成 ALL 行（跨平台），均为 0608；前一天 555 不应出现
                    assert all(r.record_date == "20260608" for r in rows)
                    assert all(r.high_price == 100.0 for r in rows)  # 只含 0608 数据,无 555
                    by = {(r.market_hash_name, r.platform) for r in rows}
                    assert ("A", "BUFF") in by and ("A", "ALL") in by
            finally:
                collector.AsyncSessionLocal = orig
    _run(body())


def test_aggregate_daily_empty_date():
    async def body():
        async with memory_db() as Session:
            orig = collector.AsyncSessionLocal
            collector.AsyncSessionLocal = Session
            try:
                n = await collector.aggregate_daily("20260608")
                assert n == 0
            finally:
                collector.AsyncSessionLocal = orig
    _run(body())


# ── cleanup_old_snapshots ──────────────────────────────────────────────────


def test_cleanup_deletes_old_keeps_recent():
    async def body():
        from datetime import datetime, timezone
        now_minute = datetime.now(timezone.utc).strftime("%Y%m%d%H%M")
        async with memory_db() as Session:
            orig = collector.AsyncSessionLocal
            collector.AsyncSessionLocal = Session
            try:
                async with Session() as db:
                    db.add_all([
                        snap("A", "BUFF", 1.0, "200001010000"),  # 远古 → 删
                        snap("A", "BUFF", 2.0, now_minute),       # 最近 → 留
                    ])
                    await db.commit()
                deleted = await collector.cleanup_old_snapshots(keep_days=7)
                assert deleted == 1
                async with Session() as db:
                    remaining = (await db.execute(select(PriceSnapshot))).scalars().all()
                    assert len(remaining) == 1
                    assert remaining[0].snapshot_minute == now_minute
            finally:
                collector.AsyncSessionLocal = orig
    _run(body())


def test_cleanup_empty_returns_zero():
    async def body():
        async with memory_db() as Session:
            orig = collector.AsyncSessionLocal
            collector.AsyncSessionLocal = Session
            try:
                assert await collector.cleanup_old_snapshots(keep_days=7) == 0
            finally:
                collector.AsyncSessionLocal = orig
    _run(body())


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
