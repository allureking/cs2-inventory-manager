from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=False,
    connect_args={"check_same_thread": False},
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
        ]
        for sql in _new_columns:
            try:
                await conn.execute(text(sql))
            except Exception:
                pass  # 列已存在则忽略
