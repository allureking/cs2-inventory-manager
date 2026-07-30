"""
提案3+7 修复的特征测试：

  1) parse_money 共享 helper —— 钉死 '¥1,234.56' / '1234.56' / '' / None 四类输入
     （根因：tracker 与 collector 各写一遍解析且不一致，'¥425194.14' 曾致
      snapshot_daily 静默 fallback 到 price_snapshot 口径）。
  2) snapshot_daily fallback 标记 —— 悠悠估值不可用时 notes 必须写
     valuation_source=snapshot，且不得破坏已有备注；成功路径不写标记。
  3) backfill 合成数据只填空日期 —— on_conflict_do_nothing，
     绝不覆盖真实 ALL 聚合行（2026-06-08 污染事故的防再发）。
  4) scripts/restore_all_rows.py —— dry-run 不写库；execute 按
     aggregate_daily 的 ALL 聚合口径重算覆盖、删除无源合成行、窗口外不动。
"""

import asyncio
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from sqlalchemy import create_engine, select

import app.services.collector as collector
import app.services.tracker as tracker
from app.core.utils import parse_money
from app.models.db_models import DailyTracker, PriceHistory, PriceSnapshot
from tests.conftest import make_item, memory_db


def _run(coro):
    return asyncio.run(coro)


# ── 1) parse_money ─────────────────────────────────────────────────────────


def test_parse_money_yen_prefix_with_commas():
    assert parse_money("¥1,234.56") == 1234.56


def test_parse_money_plain_number_string():
    assert parse_money("1234.56") == 1234.56


def test_parse_money_empty_string():
    assert parse_money("") == 0.0


def test_parse_money_none():
    assert parse_money(None) == 0.0


def test_parse_money_journal_incident_value():
    # journal 实锤的崩溃输入：could not convert string to float: '¥425194.14'
    assert parse_money("¥425194.14") == 425194.14


def test_parse_money_numeric_passthrough_and_whitespace():
    assert parse_money(425194.14) == 425194.14
    assert parse_money(" ¥1,000 ") == 1000.0
    assert parse_money("   ") == 0.0


def test_parse_money_garbage_raises():
    # 无法解析的串仍抛 ValueError（调用方已有 warning+fallback 处理）
    with pytest.raises(ValueError):
        parse_money("N/A")


# ── 2) snapshot_daily fallback 标记 ────────────────────────────────────────


def _today_la() -> str:
    return datetime.now(ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d")


def test_snapshot_daily_fallback_writes_notes_marker():
    """无悠悠 token → 估值走 snapshot 口径 **且** 租赁统计取不到 → 两个标记都写。

    v0.13.3 起租赁侧也有标记（此前只 log 一条 warning 就写全零）。没 token 时两条
    通路一起断，因此这里期望两个标记同时出现。
    """
    async def body():
        async with memory_db() as Session:
            import app.core.database as core_db
            with mock.patch.object(core_db, "AsyncSessionLocal", Session), \
                 mock.patch("app.services.youpin.get_active_token", return_value=None):
                row = await tracker.snapshot_daily()
            assert row["notes"] == "valuation_source=snapshot | rental_stats=unavailable"
            # 租赁侧不可信 → 这些字段整组不写，绝不能落成 0
            for k in ("rented_count", "daily_income", "inventory_value", "price_change"):
                assert k not in row
            async with Session() as db:
                saved = (await db.execute(
                    select(DailyTracker).where(DailyTracker.date == _today_la())
                )).scalar_one()
                assert saved.notes == "valuation_source=snapshot | rental_stats=unavailable"
                assert saved.daily_income is None      # 不是 0.0
                assert saved.rented_count is None
    _run(body())


def test_snapshot_daily_rental_failure_does_not_zero_out_existing_row():
    """租赁接口挂掉，但当天已有数据 → 既有租赁/市值不得被清零覆盖。

    这是修复前最伤的一种:inv_value = rental.value + in_steam_value，租赁侧一挂，
    总市值就塌成只剩 in_steam（约整体一成），收益曲线上凭空多一根暴跌。
    """
    async def body():
        async with memory_db() as Session:
            import app.core.database as core_db
            async with Session() as db:
                db.add(DailyTracker(date=_today_la(), rented_count=3832,
                                    rented_value=3_600_000.0, daily_income=2466.82,
                                    inventory_value=4_000_000.0))
                await db.commit()

            async def fake_stock(page=1, page_size=1):
                return [], 0, "¥425,194.14"

            async def boom(page=1, page_size=1):
                raise RuntimeError("simulated youpin timeout")

            with mock.patch.object(core_db, "AsyncSessionLocal", Session), \
                 mock.patch("app.services.youpin.get_active_token", return_value="tok"), \
                 mock.patch("app.services.youpin.fetch_stock_records", fake_stock), \
                 mock.patch("app.services.youpin.fetch_lease_records", boom):
                await tracker.snapshot_daily()

            async with Session() as db:
                saved = (await db.execute(
                    select(DailyTracker).where(DailyTracker.date == _today_la())
                )).scalar_one()
                assert saved.rented_count == 3832              # 原值保留
                assert saved.daily_income == 2466.82
                assert saved.inventory_value == 4_000_000.0    # 没塌成 42 万
                assert "rental_stats=unavailable" in saved.notes
                assert "valuation_source=snapshot" not in saved.notes  # 估值侧是好的
    _run(body())


def test_snapshot_daily_fallback_preserves_existing_notes_and_idempotent():
    """已有手工备注时 append 标记；重复 fallback 不重复追加（两个标记都不重复）。"""
    async def body():
        async with memory_db() as Session:
            import app.core.database as core_db
            async with Session() as db:
                db.add(DailyTracker(date=_today_la(), notes="手工备注"))
                await db.commit()
            with mock.patch.object(core_db, "AsyncSessionLocal", Session), \
                 mock.patch("app.services.youpin.get_active_token", return_value=None):
                await tracker.snapshot_daily()
                await tracker.snapshot_daily()  # 二次 fallback
            async with Session() as db:
                saved = (await db.execute(
                    select(DailyTracker).where(DailyTracker.date == _today_la())
                )).scalar_one()
                assert saved.notes == (
                    "手工备注 | valuation_source=snapshot | rental_stats=unavailable")
    _run(body())


def test_snapshot_daily_success_parses_yen_and_no_marker():
    """悠悠估值带 '¥'+千分位也能解析（修复前在此崩溃走 fallback），成功路径不写标记。"""
    async def body():
        async with memory_db() as Session:
            import app.core.database as core_db

            async def fake_stock(page=1, page_size=1):
                return [], 0, "¥425,194.14"

            async def fake_lease(page=1, page_size=1):
                return [], 0, "件数：2｜价值：¥1000.00｜总租金：¥10.00/天"

            with mock.patch.object(core_db, "AsyncSessionLocal", Session), \
                 mock.patch("app.services.youpin.get_active_token", return_value="tok"), \
                 mock.patch("app.services.youpin.fetch_stock_records", fake_stock), \
                 mock.patch("app.services.youpin.fetch_lease_records", fake_lease):
                row = await tracker.snapshot_daily()
            assert row["inventory_value"] == round(1000.0 + 425194.14, 2)
            assert "notes" not in row  # 成功路径不碰 notes
    _run(body())


# ── 3) backfill 只填空日期，不覆盖真实行 ───────────────────────────────────


def test_backfill_does_not_overwrite_real_rows():
    async def body():
        async with memory_db() as Session:
            real_date = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y%m%d")

            async def fake_avg(name, db, days=7):
                return SimpleNamespace(avg_price=100.0)

            async def fake_signals():
                return None

            async def no_sleep(_):
                return None

            orig = collector.AsyncSessionLocal
            orig_state = dict(collector.backfill_state)
            collector.AsyncSessionLocal = Session
            try:
                async with Session() as db:
                    db.add(make_item(market_hash_name="A", status="in_steam"))
                    # 真实 ALL 聚合行（修复前会被合成数据 do_update 覆盖）
                    db.add(PriceHistory(market_hash_name="A", platform="ALL",
                                        open_price=55.5, close_price=55.5,
                                        high_price=56.0, low_price=55.0,
                                        record_date=real_date))
                    await db.commit()

                with mock.patch("app.core.config.settings.steamdt_api_key", "test-key"), \
                     mock.patch("app.services.steamdt.fetch_avg_price", fake_avg), \
                     mock.patch("app.services.quant_engine.compute_all_signals", fake_signals), \
                     mock.patch("asyncio.sleep", no_sleep):
                    await collector.backfill_avg_prices()

                async with Session() as db:
                    rows = (await db.execute(
                        select(PriceHistory).where(PriceHistory.market_hash_name == "A")
                    )).scalars().all()
                    by_date = {r.record_date: r for r in rows}
                    # 真实行原样保留
                    assert by_date[real_date].close_price == 55.5
                    assert by_date[real_date].high_price == 56.0
                    # 其余空日期被合成数据填充（45 天窗口内）
                    assert len(rows) > 1
                    synth = [r for r in rows if r.record_date != real_date]
                    assert all(80.0 < r.close_price < 120.0 for r in synth)
            finally:
                collector.AsyncSessionLocal = orig
                collector.backfill_state.clear()
                collector.backfill_state.update(orig_state)
    _run(body())


def test_aggregate_daily_zero_price_filter():
    """0 价快照（无报价/抓取失败占位）不产平台行；遗留 0 价平台行不拖垮 ALL 聚合。"""
    async def body():
        async with memory_db() as Session:
            orig = collector.AsyncSessionLocal
            collector.AsyncSessionLocal = Session
            try:
                async with Session() as db:
                    db.add_all([
                        PriceSnapshot(market_hash_name="A", platform="BUFF",
                                      sell_price=100.0, snapshot_minute="202606080800"),
                        PriceSnapshot(market_hash_name="A", platform="CSMONEY",
                                      sell_price=0.0, snapshot_minute="202606080800"),
                    ])
                    # 遗留的 0 价平台行（停用平台时代写入）
                    db.add(PriceHistory(market_hash_name="A", platform="WAXPEER",
                                        open_price=0.0, close_price=0.0,
                                        high_price=0.0, low_price=0.0,
                                        record_date="20260608"))
                    await db.commit()
                await collector.aggregate_daily("20260608")
                async with Session() as db:
                    rows = (await db.execute(select(PriceHistory))).scalars().all()
                    by = {(r.market_hash_name, r.platform): r for r in rows}
                    assert ("A", "CSMONEY") not in by          # 0 价快照不产平台行
                    assert by[("A", "ALL")].close_price == 100.0  # MIN 不被 0 拖垮
                    assert by[("A", "ALL")].low_price == 100.0
            finally:
                collector.AsyncSessionLocal = orig
    _run(body())


# ── 4) scripts/restore_all_rows.py ────────────────────────────────────────


def _make_db(tmp_path) -> str:
    """用真实 ORM schema 建一个临时 sqlite 文件库。"""
    db_path = str(tmp_path / "t.db")
    eng = create_engine(f"sqlite:///{db_path}")
    from app.core.database import Base
    Base.metadata.create_all(eng)
    eng.dispose()
    return db_path


def _seed_restore_fixture(db_path: str):
    conn = sqlite3.connect(db_path)
    ins = ("INSERT INTO price_history (market_hash_name, platform, open_price, "
           "close_price, high_price, low_price, sell_count, bidding_count, record_date) "
           "VALUES (?,?,?,?,?,?,?,?,?)")
    rows = [
        # A @20260501: 两个平台真实行 + 被污染的 ALL 行
        ("A", "BUFF",   100.0, 90.0, 120.0, 85.0, 5, 2, "20260501"),
        ("A", "YOUPIN", 110.0, 95.0, 115.0, 88.0, 3, 1, "20260501"),
        ("A", "ALL",    999.0, 999.0, 1009.0, 989.0, None, None, "20260501"),
        # B @20260501: 只有 ALL 行（纯合成,无源可恢复 → 删除）
        ("B", "ALL",    50.0, 50.0, 50.5, 49.5, None, None, "20260501"),
        # C @20260501: ALL 行已与聚合一致（不动）
        ("C", "BUFF",   10.0, 9.0, 11.0, 8.5, 2, 1, "20260501"),
        ("C", "ALL",    10.0, 9.0, 11.0, 8.5, 2, 1, "20260501"),
        # D @20260301: 窗口外的孤儿 ALL 行（不动）
        ("D", "ALL",    7.0, 7.0, 7.1, 6.9, None, None, "20260301"),
        # E @20260501: 停用平台 0 价占位行 → 不得拖低 A 的聚合;
        #   F 只有 0 价行支撑 → 其 ALL 行视同无源,删除
        ("A", "CSMONEY", 0.0, 0.0, 0.0, 0.0, None, None, "20260501"),
        ("F", "DMARKET", 0.0, 0.0, 0.0, 0.0, None, None, "20260501"),
        ("F", "ALL",    30.0, 30.0, 30.3, 29.7, None, None, "20260501"),
    ]
    conn.executemany(ins, rows)
    conn.commit()
    conn.close()


def _all_rows(db_path: str):
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT market_hash_name, platform, open_price, close_price, high_price, "
        "low_price, sell_count, bidding_count, record_date FROM price_history "
        "ORDER BY market_hash_name, platform, record_date"
    ).fetchall()
    conn.close()
    return rows


def test_restore_dry_run_changes_nothing(tmp_path):
    from scripts.restore_all_rows import restore
    db_path = _make_db(tmp_path)
    _seed_restore_fixture(db_path)
    before = _all_rows(db_path)
    assert restore(db_path, "20260423", "20260609", execute=False) == 0
    assert _all_rows(db_path) == before


def test_restore_execute_recomputes_deletes_orphans_keeps_outside(tmp_path):
    from scripts.restore_all_rows import restore
    db_path = _make_db(tmp_path)
    _seed_restore_fixture(db_path)
    assert restore(db_path, "20260423", "20260609", execute=True) == 0

    rows = {(r[0], r[1], r[8]): r for r in _all_rows(db_path)}
    # A 的 ALL 行被重算为跨平台聚合：MIN open/close、MAX high、MIN low、SUM counts
    # （CSMONEY 的 0 价占位行被过滤,没把 MIN 拖成 0）
    a = rows[("A", "ALL", "20260501")]
    assert a[2:8] == (100.0, 90.0, 120.0, 85.0, 8, 3)
    # B 的无源合成 ALL 行被删除
    assert ("B", "ALL", "20260501") not in rows
    # C 已一致,原样保留
    assert rows[("C", "ALL", "20260501")][2:8] == (10.0, 9.0, 11.0, 8.5, 2, 1)
    # 窗口外的 D 不动
    assert ("D", "ALL", "20260301") in rows
    # F 只有 0 价行支撑 → ALL 行删除（0 价行本身保留,不属于 ALL 恢复范围）
    assert ("F", "ALL", "20260501") not in rows
    assert ("F", "DMARKET", "20260501") in rows
    # 分平台真实行全部原样
    assert rows[("A", "BUFF", "20260501")][2:6] == (100.0, 90.0, 120.0, 85.0)
    assert rows[("A", "YOUPIN", "20260501")][2:6] == (110.0, 95.0, 115.0, 88.0)


def test_restore_execute_idempotent(tmp_path):
    from scripts.restore_all_rows import restore
    db_path = _make_db(tmp_path)
    _seed_restore_fixture(db_path)
    restore(db_path, "20260423", "20260609", execute=True)
    after_first = _all_rows(db_path)
    restore(db_path, "20260423", "20260609", execute=True)
    assert _all_rows(db_path) == after_first
