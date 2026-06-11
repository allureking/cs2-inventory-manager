"""
测试基建（零额外依赖：用 asyncio.run + 内存 SQLite，不需要 pytest-asyncio）。

设计要点：
  - memory_db(): 每次创建独立的内存 SQLite(StaticPool 让同一连接在多个 session 间共享),
    建表后产出 sessionmaker。pricing / tracker 等"接收 db 参数"的纯 DB 函数直接传 session 测。
  - asgi_client(): 用 httpx.ASGITransport 在「同一事件循环」内 seed + 发请求,
    覆盖 get_db 依赖为内存库。**不以 context manager 进入 lifespan**,
    因此绝不触发 main.py 的 startup(init_db / APScheduler / 外部快照)。
  - 一切都在内存库 + 依赖覆盖里跑：不连生产 DB、不发真实网络请求。
"""

from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path

# 让 tests/ 能 import app.*
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import Base
import app.models.db_models  # noqa: F401 — 触发模型注册到 Base.metadata


@asynccontextmanager
async def memory_db():
    """产出一个绑定到独立内存库的 async_sessionmaker（表已建好）。"""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,  # 单连接共享 → 内存库在多 session 间可见
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        yield Session
    finally:
        await engine.dispose()


def _default_routers():
    """默认只挂 dashboard 路由（无 Form 依赖,不需要 python-multipart）。"""
    from app.api.routes import dashboard
    return [(dashboard.router, "/api/dashboard")]


def _reset_module_caches():
    """重置各路由模块的进程内 TTL 缓存（overview/chart-data/analysis-overview）。"""
    from app.api.routes import dashboard, analysis
    dashboard._overview_cache.update(data=None, ts=0.0)
    dashboard._chart_cache.update(data=None, ts=0.0)
    analysis._ao_cache.update(data=None, ts=0.0)


@asynccontextmanager
async def asgi_client(seed=None, routers=None):
    """
    产出 (httpx.AsyncClient, sessionmaker)，get_db 已覆盖为内存库。

    - 不导入 main：自建最小 FastAPI app,只挂载传入的 routers
      （从而不触发 lifespan / APScheduler / StaticFiles / 含 Form 的路由对
       python-multipart 的依赖）。
    - seed: 可选 async 函数 seed(db)，发请求前注入 fixtures。
    - routers: [(router, prefix), ...]，默认仅 dashboard。
    """
    import httpx
    from fastapi import FastAPI

    from app.core.database import get_db

    _reset_module_caches()  # 模块级 TTL 缓存逐测重置,避免跨测试串数据

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    if seed is not None:
        async with Session() as db:
            await seed(db)

    async def _override_get_db():
        async with Session() as db:
            yield db

    app = FastAPI()
    for router, prefix in (routers if routers is not None else _default_routers()):
        app.include_router(router, prefix=prefix)
    app.dependency_overrides[get_db] = _override_get_db

    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client, Session
    finally:
        await engine.dispose()


# ── 构造 fixtures 的小工具 ──────────────────────────────────────────────

def make_item(**kw):
    """构造一个 InventoryItem，必填字段给合理默认值。"""
    from app.models.db_models import InventoryItem

    defaults = dict(
        steam_id="76561198000000000",
        class_id="c1",
        instance_id="i1",
        market_hash_name="AK-47 | Redline (Field-Tested)",
        name="AK-47 | 红线 (久经沙场)",
        status="in_steam",
    )
    defaults.update(kw)
    return InventoryItem(**defaults)


def make_snapshot(**kw):
    """构造一个 PriceSnapshot。"""
    from app.models.db_models import PriceSnapshot

    defaults = dict(
        market_hash_name="AK-47 | Redline (Field-Tested)",
        platform="YOUPIN",
        sell_price=100.0,
        snapshot_minute="202606080000",
    )
    defaults.update(kw)
    return PriceSnapshot(**defaults)
