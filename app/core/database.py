from sqlalchemy import text
from sqlalchemy.schema import CreateIndex
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=False,
    connect_args={"check_same_thread": False, "timeout": 30},
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session


async def init_db() -> None:
    """创建所有表，并对已有 DB 自动补齐新增列（轻量 migration）"""
    from app.models import db_models  # noqa: F401 — 触发模型注册

    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA journal_mode=WAL"))
        await conn.execute(text("PRAGMA busy_timeout=5000"))
        await conn.run_sync(Base.metadata.create_all)

        # 对已存在的表补加新列（SQLite 不支持修改约束，只能 ADD COLUMN）
        _new_columns = [
            "ALTER TABLE inventory_item ADD COLUMN youpin_order_id TEXT",
            "ALTER TABLE inventory_item ADD COLUMN youpin_commodity_id INTEGER",
            "ALTER TABLE inventory_item ADD COLUMN abrade REAL",
            "ALTER TABLE inventory_item ADD COLUMN purchase_price_manual REAL",
            "ALTER TABLE inventory_item ADD COLUMN youpin_template_id INTEGER",
            "ALTER TABLE portfolio_snapshot ADD COLUMN in_steam_value FLOAT",
            "ALTER TABLE portfolio_snapshot ADD COLUMN rented_out_value FLOAT",
            # v0.5.1: 盈亏率、含租预期收益率、CSQAQ ATH
            "ALTER TABLE quant_signal ADD COLUMN pnl_rate FLOAT",
            "ALTER TABLE quant_signal ADD COLUMN projected_annual_return FLOAT",
            "ALTER TABLE quant_signal ADD COLUMN csqaq_ath_price FLOAT",
            # v0.6.0: 每日追踪大会员标记
            "ALTER TABLE daily_tracker ADD COLUMN is_vip BOOLEAN DEFAULT 1",
            "ALTER TABLE daily_tracker ADD COLUMN cost_basis FLOAT",
        ]
        import logging
        _logger = logging.getLogger(__name__)
        for sql in _new_columns:
            try:
                await conn.execute(text(sql))
                _logger.info("migration: %s", sql)
            except Exception:
                pass  # 列已存在则忽略

        # 性能索引
        _indexes = [
            "CREATE INDEX IF NOT EXISTS ix_ps_name_minute ON price_snapshot (market_hash_name, snapshot_minute)",
            "CREATE INDEX IF NOT EXISTS ix_ps_platform_name_minute ON price_snapshot (market_hash_name, platform, snapshot_minute)",
            "CREATE INDEX IF NOT EXISTS ix_ps_snapshot_minute ON price_snapshot (snapshot_minute)",
            # analysis/* 端点全部按 signal_date 过滤；唯一约束 (name,date) 帮不上单列过滤
            "CREATE INDEX IF NOT EXISTS ix_qs_signal_date ON quant_signal (signal_date)",
            "CREATE INDEX IF NOT EXISTS ix_ph_name_platform_date ON price_history (market_hash_name, platform, record_date)",
            # v0.13 租赁实绩:单品近 N 天查询
            "CREATE INDEX IF NOT EXISTS ix_lid_name_date ON lease_income_daily (market_hash_name, date)",
        ]
        for sql in _indexes:
            await conn.execute(text(sql))

        # ── 补齐模型里声明但库上缺失的索引（AUDIT H1）────────────────────────
        # 上面那批 ALTER TABLE 后补的列（youpin_commodity_id / youpin_order_id /
        # youpin_template_id）在模型里都写了 index=True，但 create_all(checkfirst=True)
        # 对**已存在的表整表跳过**，不会回头补建索引。于是新建库（所有测试走的路径）
        # 索引齐全，而老库（生产）永远缺这几个 —— 测试结构性照不到这个漂移。
        #
        # 实测代价：生产 inventory_item 79,760 行，缺 ix_..._youpin_commodity_id 时
        # 租赁导入里 3,555 次按该列的查询全部走 SCAN，单次 23.4ms → 合计 ~83 秒，
        # 而这 83 秒整段握着 SQLite 写锁（先 UPDATE 全部 rented_out 再 flush，
        # 循环跑完才 commit），并发写只能排队等 timeout=30s 然后报 database is locked。
        #
        # 这里不再手工维护清单，直接以模型声明为准逐个补建 —— 以后再加带 index=True
        # 的新列，老库也会在下次启动时自愈。
        created_idx = []
        for _table in Base.metadata.sorted_tables:
            for _idx in _table.indexes:
                try:
                    await conn.execute(CreateIndex(_idx, if_not_exists=True))
                    created_idx.append(_idx.name)
                except Exception as e:
                    # 单个索引建不上不能挡住启动（例如列真的不存在的历史残留表）
                    _logger.warning("index ensure failed: %s (%s)", _idx.name, e)
        if created_idx:
            _logger.info("index ensure: 已确保 %d 个模型声明索引存在", len(created_idx))

        await conn.execute(text("ANALYZE"))
