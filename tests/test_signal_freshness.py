"""
信号新鲜度口径测试（AUDIT Q3）。内存库，无网络。

背景
----
`csqaq_daily_sync` 每天 00:02 会为 244 个品 upsert `quant_signal` 行，但**只填**
租金 / 成交量 / 存世量，技术指标与评分列全是 NULL。而新鲜度取的是裸
`max(signal_date)` —— 于是前端每天都显示「● 信号 <今天>」，看起来无比新鲜。

生产实证：`max(signal_date)` = 20260801（今天），但那天 244 行里
`opportunity_score` 非空的有 **0 行**；最后一次真正算过分是 **20260702**。
信号计算停摆整整一个月，被这个口径完整地掩盖住了。

本文件锁住：
  A. 只有 CSQAQ 行（无评分）时，新鲜度必须反映**真实停摆日**，而不是今天
  B. 完全没有评分行时，新鲜度为 None（而不是谎报一个日期）
  C. sell_score 与 opportunity_score 任一非空即算「已评分」
  D. 同时返回 signal_stale_days，供前端把蓝点变黄
"""

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from app.api.routes import analysis as analysis_route
from app.api.routes import monitoring as monitoring_route
from app.models.db_models import QuantSignal
from tests.conftest import asgi_client, memory_db

ROUTERS = [(analysis_route.router, "/api/analysis")]


def _run(coro):
    return asyncio.run(coro)


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def _days_ago(n: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=n)).strftime("%Y%m%d")


def csqaq_row(date_str, name="AK-47 | Redline (Field-Tested)"):
    """CSQAQ 同步写的行：只有租金/存世量，评分列全空 —— 正是掩盖停摆的元凶。"""
    return QuantSignal(market_hash_name=name, signal_date=date_str,
                       daily_rent=12.5, rental_annual=8.3, global_supply=1234,
                       sell_score=None, opportunity_score=None)


def scored_row(date_str, name="AWP | Asiimov (Field-Tested)",
               sell=72.0, opp=None):
    return QuantSignal(market_hash_name=name, signal_date=date_str,
                       sell_score=sell, opportunity_score=opp)


def _seeder(rows):
    async def seed(db):
        for r in rows:
            db.add(r)
        await db.commit()
    return seed


# ── A. 核心：CSQAQ 行不得冒充信号日期 ──────────────────────────────────────


def test_csqaq_only_rows_do_not_fake_freshness():
    """回归锁：今天有 CSQAQ 行、但最后一次评分在 30 天前 → 必须显示 30 天前那天。

    修复前这里会返回今天，正是这个口径让「停摆一个月」一直没被发现。
    """
    stalled = _days_ago(30)

    async def body():
        rows = [scored_row(stalled)]
        # 停摆之后每天仍有 CSQAQ 行（含今天）
        for d in range(0, 30):
            rows.append(csqaq_row(_days_ago(d), name=f"CSQAQ Item {d}"))
        async with asgi_client(seed=_seeder(rows), routers=ROUTERS) as (client, _):
            d = (await client.get("/api/analysis/overview")).json()
        assert d["signal_date"] == stalled, (
            f"新鲜度应为最后一次评分日 {stalled}，实际 {d['signal_date']}"
            "（若等于今天，说明 CSQAQ 行又在冒充信号日期）")
        assert d["signal_date"] != _today()
        assert d["signal_stale_days"] == 30
    _run(body())


def test_no_scored_rows_at_all_reports_none():
    """从来没算过分 → 老实返回 None，不要拿 CSQAQ 行谎报一个日期。"""
    async def body():
        rows = [csqaq_row(_today()), csqaq_row(_days_ago(1), name="X")]
        async with asgi_client(seed=_seeder(rows), routers=ROUTERS) as (client, _):
            d = (await client.get("/api/analysis/overview")).json()
        assert d["signal_date"] is None
        assert d["signal_stale_days"] is None
    _run(body())


def test_fresh_scoring_reports_today_and_zero_stale():
    """信号计算正常时不能误报过期 —— 修复不该把好的情况也搞坏。"""
    async def body():
        rows = [scored_row(_today()), csqaq_row(_today(), name="CSQAQ X")]
        async with asgi_client(seed=_seeder(rows), routers=ROUTERS) as (client, _):
            d = (await client.get("/api/analysis/overview")).json()
        assert d["signal_date"] == _today()
        assert d["signal_stale_days"] == 0
    _run(body())


# ── C. 两种评分任一非空都算「已评分」 ──────────────────────────────────────


def test_opportunity_score_alone_counts_as_scored():
    """只恢复买入评分（不恢复卖出评分）时，新鲜度也要认。"""
    d5 = _days_ago(5)

    async def body():
        rows = [QuantSignal(market_hash_name="Only Opp", signal_date=d5,
                            sell_score=None, opportunity_score=66.0),
                csqaq_row(_today(), name="CSQAQ Y")]
        async with asgi_client(seed=_seeder(rows), routers=ROUTERS) as (client, _):
            d = (await client.get("/api/analysis/overview")).json()
        assert d["signal_date"] == d5
        assert d["signal_stale_days"] == 5
    _run(body())


def test_sell_score_alone_counts_as_scored():
    d3 = _days_ago(3)

    async def body():
        rows = [scored_row(d3, sell=50.0, opp=None), csqaq_row(_today(), name="CSQAQ Z")]
        async with asgi_client(seed=_seeder(rows), routers=ROUTERS) as (client, _):
            d = (await client.get("/api/analysis/overview")).json()
        assert d["signal_date"] == d3
    _run(body())


def test_latest_of_multiple_scored_days_wins():
    """有多天评分时取最新那天。"""
    async def body():
        rows = [scored_row(_days_ago(10), name="A"),
                scored_row(_days_ago(4), name="B"),
                csqaq_row(_today(), name="CSQAQ W")]
        async with asgi_client(seed=_seeder(rows), routers=ROUTERS) as (client, _):
            d = (await client.get("/api/analysis/overview")).json()
        assert d["signal_date"] == _days_ago(4)
    _run(body())


# ── monitoring 端点同口径 ──────────────────────────────────────────────────


def test_monitoring_freshness_uses_same_scored_only_rule():
    """概览页那条新鲜度走的是 monitoring 端点，口径必须一致，否则两处显示打架。"""
    stalled = _days_ago(20)

    async def body():
        async with memory_db() as Session:
            async with Session() as db:
                db.add(scored_row(stalled))
                db.add(csqaq_row(_today(), name="CSQAQ M"))
                await db.commit()
            async with Session() as db:
                from sqlalchemy import func, or_, select
                got = (await db.execute(
                    select(func.max(QuantSignal.signal_date)).where(
                        or_(QuantSignal.sell_score.isnot(None),
                            QuantSignal.opportunity_score.isnot(None))))).scalar()
            assert got == stalled
        # 并确认 monitoring 源码里两处都带上了该过滤（防止只改一处）
        import inspect
        src = inspect.getsource(monitoring_route)
        assert src.count("QuantSignal.opportunity_score.isnot(None)") == 2, \
            "monitoring 里两处 latest_signal 都要加评分过滤"
    _run(body())


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
