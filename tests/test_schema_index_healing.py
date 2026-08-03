"""
索引自愈测试（AUDIT H1）。真实 SQLite 文件库，无网络。

为什么必须专门造「老库」场景
----------------------------
`youpin_commodity_id` / `youpin_order_id` / `youpin_template_id` 这三列在模型里都写了
`index=True`，但它们是靠 `init_db` 里的 `ALTER TABLE ADD COLUMN` 后补上去的。而
`create_all(checkfirst=True)` 对**已存在的表整表跳过**，不会回头补建索引。

后果是一个结构性盲区：
  - 新建库（现有 472 个测试全部走这条路径）→ create_all 一次性建表 + 建索引 → 索引齐全
  - 老库（生产）→ 表早就存在 → create_all 跳过 → 这三个索引**永远不会被创建**

生产实测：`inventory_item` 79,760 行，缺索引时按 `youpin_commodity_id` 的查询走
`SCAN`，单次 23.4ms；租赁导入要跑 3,555 次 → ~83 秒，且整段握着 SQLite 写锁
（日志实测该段耗时 91s / 82s / 88s）。并发写等满 timeout=30s 即 `database is locked`。

所以本文件的做法是：**先手工建一张缺索引的旧表**（模拟 ALTER TABLE 后补列的历史状态），
再走一次 `init_db`，断言索引被补上。这是唯一能覆盖该盲区的测试形状。
"""

import asyncio
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

# 这三个是 ALTER TABLE 后补列上的索引 —— 老库缺的正是它们
LATE_ADDED_INDEXES = [
    "ix_inventory_item_youpin_commodity_id",
    "ix_inventory_item_youpin_order_id",
    "ix_inventory_item_youpin_template_id",
]


def _indexes_of(db_path: str, table: str) -> set[str]:
    con = sqlite3.connect(db_path)
    try:
        return {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name=?", (table,)
        ) if r[0] and not r[0].startswith("sqlite_autoindex")}
    finally:
        con.close()


def _make_legacy_db(db_path: str) -> None:
    """构造一个「老库」：inventory_item 已存在，且那几列是 ALTER TABLE 补上的、无索引。

    这里刻意只建最小列集 + 手工 ALTER，完全复刻生产库的历史形成过程。
    """
    con = sqlite3.connect(db_path)
    try:
        con.executescript("""
            CREATE TABLE inventory_item (
                id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                steam_id VARCHAR NOT NULL,
                class_id VARCHAR NOT NULL,
                instance_id VARCHAR NOT NULL,
                market_hash_name VARCHAR NOT NULL,
                name VARCHAR NOT NULL,
                asset_id VARCHAR,
                status VARCHAR(16) NOT NULL DEFAULT 'in_steam',
                CONSTRAINT uq_item_fingerprint UNIQUE (steam_id, class_id, instance_id)
            );
            CREATE INDEX ix_inventory_item_status ON inventory_item (status);
        """)
        # 后补列（正是生产 init_db 里那几条 ALTER TABLE）—— 注意：不带索引
        for col, typ in (("youpin_order_id", "TEXT"),
                         ("youpin_commodity_id", "INTEGER"),
                         ("youpin_template_id", "INTEGER"),
                         ("abrade", "REAL"),
                         ("purchase_price_manual", "REAL")):
            con.execute(f"ALTER TABLE inventory_item ADD COLUMN {col} {typ}")
        con.commit()
    finally:
        con.close()


def _run_init_db(db_path: str) -> None:
    """用指向该文件库的独立 engine 跑一次真实的 init_db。"""
    import app.core.database as core_db
    from sqlalchemy.ext.asyncio import create_async_engine

    orig_engine = core_db.engine
    core_db.engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    try:
        asyncio.run(core_db.init_db())
        asyncio.run(core_db.engine.dispose())
    finally:
        core_db.engine = orig_engine


# ── 核心：老库缺索引 → init_db 后补上 ──────────────────────────────────────


def test_legacy_db_missing_indexes_are_healed_by_init_db():
    """本次审计最重要的一条测试。

    老库（ALTER TABLE 后补列、无索引）走一次 init_db 后，模型里声明的索引必须全部存在。
    修复前这条会红：create_all 见表已存在就整表跳过，三个索引一个都不会建。
    """
    with tempfile.TemporaryDirectory() as d:
        db = str(Path(d) / "legacy.db")
        _make_legacy_db(db)

        before = _indexes_of(db, "inventory_item")
        # 前置断言：确实处于「老库」状态，否则这个测试就白做了
        for name in LATE_ADDED_INDEXES:
            assert name not in before, f"构造的老库不该有 {name}，测试前提不成立"
        assert "ix_inventory_item_status" in before   # 老库本来就有的那个还在

        _run_init_db(db)

        after = _indexes_of(db, "inventory_item")
        for name in LATE_ADDED_INDEXES:
            assert name in after, f"init_db 后仍缺索引 {name}（H1 未修复）"
        # 不能把老库原有的索引弄丢
        assert before <= after, f"init_db 丢失了原有索引: {before - after}"


def test_healed_index_actually_used_by_query_planner():
    """光有索引名不够 —— 查询计划必须真的从 SCAN 变成 SEARCH。

    生产 EXPLAIN QUERY PLAN 实测就是 `SCAN inventory_item`（79,760 行），
    这条断言直接钉住「按 youpin_commodity_id 查不再全表扫」。
    """
    with tempfile.TemporaryDirectory() as d:
        db = str(Path(d) / "legacy.db")
        _make_legacy_db(db)

        con = sqlite3.connect(db)
        plan_before = " ".join(
            str(r) for r in con.execute(
                "EXPLAIN QUERY PLAN SELECT * FROM inventory_item WHERE youpin_commodity_id = 1"
            ).fetchall())
        con.close()
        assert "SCAN" in plan_before.upper(), "老库应当是全表扫描，测试前提不成立"

        _run_init_db(db)

        con = sqlite3.connect(db)
        plan_after = " ".join(
            str(r) for r in con.execute(
                "EXPLAIN QUERY PLAN SELECT * FROM inventory_item WHERE youpin_commodity_id = 1"
            ).fetchall())
        con.close()
        assert "SEARCH" in plan_after.upper(), f"仍未走索引: {plan_after}"
        assert "ix_inventory_item_youpin_commodity_id" in plan_after


def test_all_declared_indexes_exist_after_init_on_legacy_db():
    """不只那三个 —— 模型里声明的每一个索引都要在老库上存在。

    这样以后再加带 index=True 的新列，老库也会自愈，不需要回来改这份清单。
    """
    from app.core.database import Base
    import app.models.db_models  # noqa: F401

    with tempfile.TemporaryDirectory() as d:
        db = str(Path(d) / "legacy.db")
        _make_legacy_db(db)
        _run_init_db(db)

        con = sqlite3.connect(db)
        try:
            actual = {r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='index'") if r[0]}
        finally:
            con.close()

        declared = {idx.name for t in Base.metadata.sorted_tables for idx in t.indexes}
        missing = declared - actual
        assert not missing, f"模型声明但库上缺失的索引: {sorted(missing)}"


def test_missing_column_only_warns_and_does_not_block_startup(caplog):
    """历史残留表可能缺列，此时该索引建不上 —— 必须只记 warning、不阻断 init_db。

    （若某天模型加了新列却没配套 ALTER TABLE，这条保证服务仍能起来。）
    """
    import logging

    with tempfile.TemporaryDirectory() as d:
        db = str(Path(d) / "legacy.db")
        _make_legacy_db(db)
        con = sqlite3.connect(db)
        con.execute("ALTER TABLE inventory_item DROP COLUMN asset_id")
        con.commit(); con.close()

        with caplog.at_level(logging.WARNING, logger="app.core.database"):
            _run_init_db(db)      # 不得抛

        assert any("ix_inventory_item_asset_id" in r.getMessage()
                   for r in caplog.records), "缺列时应当留下 warning"
        # 其余索引照建不误
        assert "ix_inventory_item_youpin_commodity_id" in _indexes_of(db, "inventory_item")


def test_init_db_is_idempotent_on_legacy_db():
    """连跑两次不得报错（CREATE INDEX IF NOT EXISTS 的语义）。"""
    with tempfile.TemporaryDirectory() as d:
        db = str(Path(d) / "legacy.db")
        _make_legacy_db(db)
        _run_init_db(db)
        first = _indexes_of(db, "inventory_item")
        _run_init_db(db)          # 第二次不应抛
        assert _indexes_of(db, "inventory_item") == first


def test_fresh_db_still_gets_all_indexes():
    """新建库路径不能被这次改动弄坏（现有 472 个测试走的就是这条）。"""
    from app.core.database import Base
    import app.models.db_models  # noqa: F401

    with tempfile.TemporaryDirectory() as d:
        db = str(Path(d) / "fresh.db")
        _run_init_db(db)          # 空文件直接 init

        con = sqlite3.connect(db)
        try:
            actual = {r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='index'") if r[0]}
        finally:
            con.close()
        declared = {idx.name for t in Base.metadata.sorted_tables for idx in t.indexes}
        assert declared <= actual, f"新建库缺索引: {sorted(declared - actual)}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
