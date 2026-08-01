"""
大盘指数自动填入（v0.13.5）测试。内存库 + 构造 K 线，无网络。

口径是从生产数据反推出来的：SteamDT 小时线里 **PT 00:00 那根的收盘价**，与
snapshot_daily 写库存价值同刻（78 天手工值比对，6 天完全精确匹配、偏差中位数 -0.06）。

本文件锁住的不变量：
  A. 取的是 PT 0 点、取的是 close（不是 open/high/low，不是别的小时）
  B. **只填空，不覆盖**手工值 —— 生产上有 235 天手工数据，覆盖即不可逆
  C. **不新建行** —— 指数依附于「那天有库存数据」，不能凭空造出孤立行
  D. 脏数据（列缺失/非数值/非正数/坏时间戳）跳过而非整批失败
  E. 拉取失败时安静返回，不抛异常炸掉调度链
"""

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from sqlalchemy import select

import app.core.database as core_db
import app.services.market_index as mi
from app.models.db_models import DailyTracker
from tests.conftest import memory_db

PT = ZoneInfo("America/Los_Angeles")


def _run(coro):
    return asyncio.run(coro)


def kline_row(date_str: str, hour: int, close: float,
              open_=None, high=None, low=None):
    """构造一根 PT 指定日期/小时的 K 线：[ts, open, close, high, low]。"""
    t = datetime.strptime(date_str, "%Y-%m-%d").replace(hour=hour, tzinfo=PT)
    ts = int(t.astimezone(timezone.utc).timestamp())
    return [str(ts), open_ if open_ is not None else close + 5,
            close, high if high is not None else close + 9,
            low if low is not None else close - 9]


async def _seed(Session, rows):
    async with Session() as db:
        for date_str, idx in rows:
            db.add(DailyTracker(date=date_str, steamdt_index=idx))
        await db.commit()


async def _indexes(Session):
    async with Session() as db:
        return {d: v for d, v in (await db.execute(
            select(DailyTracker.date, DailyTracker.steamdt_index))).all()}


# ── A. 口径：PT 0 点的 close ────────────────────────────────────────────────


class TestExtraction:
    def test_picks_pt_midnight_close_only(self):
        """同一天给出多个小时,只能取 PT 0 点那根;取的必须是 close。"""
        kl = [
            kline_row("2026-07-22", 0, close=880.0, open_=888.0, high=890.0, low=870.0),
            kline_row("2026-07-22", 1, close=881.5),
            kline_row("2026-07-22", 12, close=885.0),
            kline_row("2026-07-22", 23, close=879.0),
        ]
        assert mi.extract_daily_index(kl) == {"2026-07-22": 880.0}

    def test_close_not_open(self):
        """回归锁:close 与 open 差一列,取错了整条序列会系统性偏移。"""
        kl = [kline_row("2026-07-22", 0, close=880.0, open_=999.0)]
        assert mi.extract_daily_index(kl)["2026-07-22"] == 880.0

    def test_multiple_days(self):
        kl = [kline_row("2026-07-22", 0, 880.0),
              kline_row("2026-07-23", 0, 875.5),
              kline_row("2026-07-24", 0, 883.25)]
        assert mi.extract_daily_index(kl) == {
            "2026-07-22": 880.0, "2026-07-23": 875.5, "2026-07-24": 883.25}

    def test_dst_boundary_still_maps_to_local_midnight(self):
        """PT 有夏令时切换,用固定 UTC 偏移会在切换日错行 —— 必须走时区库。"""
        for day in ("2026-03-08", "2026-11-01"):   # 美国 DST 起讫日
            got = mi.extract_daily_index([kline_row(day, 0, 900.0)])
            assert got == {day: 900.0}, f"{day} 映射错位"


# ── D. 脏数据 ───────────────────────────────────────────────────────────────


class TestDirtyRows:
    def test_skips_malformed_without_failing_batch(self):
        kl = [
            [],                                   # 空行
            ["abc", 1, 2, 3, 4],                  # 时间戳非数
            kline_row("2026-07-22", 0, 880.0)[:2],  # 列数不足
            [str(int(datetime(2026, 7, 23, 7, tzinfo=timezone.utc).timestamp())), 1, "x", 3, 4],
            kline_row("2026-07-24", 0, 0),        # 非正数
            kline_row("2026-07-25", 0, -5),
            kline_row("2026-07-26", 0, 883.25),   # 唯一有效
        ]
        assert mi.extract_daily_index(kl) == {"2026-07-26": 883.25}

    def test_column_drift_rejected_not_silently_written(self):
        """上游 K 线是无字段名的纯数组,列序一旦调整必须**拒绝**而不是静默写错列。

        最坏情况:时间戳(约 1.78e9)落到指数列。它照样 > 0,光靠正数校验拦不住,
        结果就是往「大盘指数」里写进 17 亿这种数,而且没有任何报错。
        """
        ts = int(datetime(2026, 7, 22, 7, tzinfo=timezone.utc).timestamp())
        # 指数列变成时间戳
        assert mi.extract_daily_index([[str(ts), 1.0, ts, 3.0, 4.0]]) == {}
        # 第 0 列不再是时间戳(列序整体平移)
        assert mi.extract_daily_index([[880.0, ts, 881.0, 882.0, 879.0]]) == {}
        # 指数为荒谬大值
        assert mi.extract_daily_index([[str(ts), 1.0, 999_999.0, 3.0, 4.0]]) == {}

    def test_empty_input(self):
        assert mi.extract_daily_index([]) == {}
        assert mi.extract_daily_index(None) == {}


# ── B/C. 写库：只填空、不覆盖、不新建 ───────────────────────────────────────


class TestSync:
    def _days(self, n=3, start_offset=1):
        """生成最近几天的 PT 日期（保证落在 days 窗口内）。"""
        today = datetime.now(PT)
        return [(today - timedelta(days=start_offset + i)).strftime("%Y-%m-%d")
                for i in range(n)]

    def test_fills_only_nulls(self):
        d0, d1, d2 = self._days(3)

        async def body():
            async with memory_db() as Session:
                core_db.AsyncSessionLocal = Session
                await _seed(Session, [(d0, None), (d1, 999.99), (d2, None)])
                kl = [kline_row(d, 0, 880.0) for d in (d0, d1, d2)]
                r = await mi.sync_market_index(kline=kl)
                assert r["ok"] and r["filled"] == 2
                assert r["skipped_existing"] == 1
                got = await _indexes(Session)
                assert got[d0] == 880.0 and got[d2] == 880.0
                assert got[d1] == 999.99, "手工值必须原样保留"
        _run(body())

    def test_overwrite_flag_does_overwrite(self):
        d0, = self._days(1)

        async def body():
            async with memory_db() as Session:
                core_db.AsyncSessionLocal = Session
                await _seed(Session, [(d0, 999.99)])
                r = await mi.sync_market_index(kline=[kline_row(d0, 0, 880.0)],
                                               overwrite=True)
                assert r["filled"] == 1
                assert (await _indexes(Session))[d0] == 880.0
        _run(body())

    def test_never_creates_rows(self):
        """K 线里有的日期,若 daily_tracker 没这一行,不得凭空新建。"""
        d0, d1 = self._days(2)

        async def body():
            async with memory_db() as Session:
                core_db.AsyncSessionLocal = Session
                await _seed(Session, [(d0, None)])          # 只有 d0 这一行
                kl = [kline_row(d0, 0, 880.0), kline_row(d1, 0, 875.0)]
                r = await mi.sync_market_index(kline=kl)
                assert r["filled"] == 1
                got = await _indexes(Session)
                assert set(got) == {d0}, "不得为 d1 新建行"
        _run(body())

    def test_idempotent(self):
        """跑两次结果一致,第二次不再写。"""
        d0, = self._days(1)

        async def body():
            async with memory_db() as Session:
                core_db.AsyncSessionLocal = Session
                await _seed(Session, [(d0, None)])
                kl = [kline_row(d0, 0, 880.0)]
                r1 = await mi.sync_market_index(kline=kl)
                r2 = await mi.sync_market_index(kline=kl)
                assert r1["filled"] == 1 and r2["filled"] == 0
                assert (await _indexes(Session))[d0] == 880.0
        _run(body())

    def test_days_window_excludes_older(self):
        """days 窗口外的日期不处理。"""
        old = (datetime.now(PT) - timedelta(days=60)).strftime("%Y-%m-%d")
        recent, = self._days(1)

        async def body():
            async with memory_db() as Session:
                core_db.AsyncSessionLocal = Session
                await _seed(Session, [(old, None), (recent, None)])
                kl = [kline_row(old, 0, 800.0), kline_row(recent, 0, 880.0)]
                r = await mi.sync_market_index(days=7, kline=kl)
                got = await _indexes(Session)
                assert got[recent] == 880.0
                assert got[old] is None, "窗口外不该被填"
                assert r["filled"] == 1
        _run(body())


# ── E. 失败处理 ─────────────────────────────────────────────────────────────


class TestFailureHandling:
    def test_fetch_failure_returns_quietly(self, monkeypatch):
        """拉取失败不能抛异常 —— 它挂在调度链里,炸了会连累后续任务。"""
        async def boom():
            raise RuntimeError("4005 rate limited")
        monkeypatch.setattr("app.services.steamdt.fetch_broad_kline", boom)
        monkeypatch.setattr(mi, "_RETRY_WAIT_S", 0)   # 别让重试等待拖慢测试

        async def body():
            async with memory_db() as Session:
                core_db.AsyncSessionLocal = Session
                r = await mi.sync_market_index()
                assert r["ok"] is False and r["filled"] == 0
                assert "4005" in r["error"]
        _run(body())

    def test_no_usable_rows_reports_not_ok(self):
        async def body():
            async with memory_db() as Session:
                core_db.AsyncSessionLocal = Session
                r = await mi.sync_market_index(kline=[kline_row("2026-07-22", 5, 880.0)])
                assert r["ok"] is False and r["filled"] == 0
        _run(body())


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


class TestRetry:
    def test_retries_then_succeeds(self, monkeypatch):
        """限流(4005)后重试应能拿到数据,而不是白白等一天。"""
        d0 = (datetime.now(PT) - timedelta(days=1)).strftime("%Y-%m-%d")
        calls = {"n": 0}

        async def flaky():
            calls["n"] += 1
            if calls["n"] < 3:
                raise RuntimeError("4005 当前接口请求已达到上限")
            return [kline_row(d0, 0, 880.0)]

        monkeypatch.setattr("app.services.steamdt.fetch_broad_kline", flaky)
        monkeypatch.setattr(mi, "_RETRY_WAIT_S", 0)

        async def body():
            async with memory_db() as Session:
                core_db.AsyncSessionLocal = Session
                await _seed(Session, [(d0, None)])
                r = await mi.sync_market_index()
                assert r["ok"] and r["filled"] == 1
                assert calls["n"] == 3
        _run(body())

    def test_retry_is_bounded(self, monkeypatch):
        """一直失败也必须停下来,不能无限重试拖住调度链。"""
        calls = {"n": 0}

        async def always_fail():
            calls["n"] += 1
            raise RuntimeError("4005")

        monkeypatch.setattr("app.services.steamdt.fetch_broad_kline", always_fail)
        monkeypatch.setattr(mi, "_RETRY_WAIT_S", 0)

        async def body():
            async with memory_db() as Session:
                core_db.AsyncSessionLocal = Session
                r = await mi.sync_market_index()
                assert r["ok"] is False
                assert calls["n"] == mi._FETCH_ATTEMPTS
        _run(body())
