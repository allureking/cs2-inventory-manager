import asyncio
import logging
import sys
import uvicorn

logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings
from app.core.database import init_db
from app.api.routes import prices, items, inventory, youpin, listing
from app.api.routes import dashboard, analysis, monitoring, tracker
from app.api.routes import auth as auth_routes
from app.services import auth as auth_svc

# ── 定时任务 ────────────────────────────────────────────────────────────────
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.services.collector import (
    collect_prices,
    aggregate_daily,
    compute_signals,
    cleanup_old_snapshots,
    snapshot_portfolio,
)
from app.services.csqaq import csqaq_daily_sync
from app.services.tracker import snapshot_daily

scheduler = AsyncIOScheduler()
logger = logging.getLogger(__name__)
# ────────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="CS2 Inventory Manager",
    description="CS2 饰品量化交易监控系统",
    version="0.13.4",
)

def _api_key_ok(request: Request) -> bool:
    if not settings.app_api_key:
        return False
    if request.headers.get("Authorization", "") == f"Bearer {settings.app_api_key}":
        return True
    # 历史上 nginx Basic Auth 占用 Authorization 头，保留 X-API-Key 通道（脚本/curl 用）
    return request.headers.get("X-API-Key", "") == settings.app_api_key


class APIKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not settings.app_api_key:
            return await call_next(request)
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return await call_next(request)
        if not request.url.path.startswith("/api/"):
            return await call_next(request)
        # v0.10.0: 登录/登出本身必须可匿名 POST（凭证在 body 里验证）
        if request.url.path in ("/api/auth/login", "/api/auth/logout"):
            return await call_next(request)
        # v0.10.0: 已登录的 session 用户可直接写（SessionAuthMiddleware 在外层设 state.user）
        if getattr(request.state, "user", None):
            return await call_next(request)
        if _api_key_ok(request):
            return await call_next(request)
        return JSONResponse(status_code=401, content={"detail": "Unauthorized"})


class SessionAuthMiddleware(BaseHTTPMiddleware):
    """
    应用级登录门禁（v0.10.0 用户系统）。

    - 白名单：/health（monitor.sh）、/login、/api/auth/login|logout、/static/*、favicon。
    - 用户表为空（系统未初始化/本地开发）→ 直通，行为与 0.9.x 相同。
    - 有效 session cookie → request.state.user；
      有效 APP_API_KEY（Bearer / X-API-Key）→ 等价凭证（脚本/curl 通道）。
    - 未认证：/api/* 返回 401 JSON；页面请求 302 → /login。
    """

    _PUBLIC = ("/health", "/login", "/api/auth/login", "/api/auth/logout", "/favicon.ico")

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path in self._PUBLIC or path.startswith("/static/"):
            return await call_next(request)
        if not await auth_svc.users_exist():
            # v0.13.3 fail-closed:用户表为空时不再静默直通。
            # 旧行为的风险:恢复 v0.10.0 之前的备份、误删 app_user、或新机 init_db
            # 建完空表就起服务 → 全站读端点(持仓/成本/逐件PnL/租赁明细)对公网敞开,
            # 且无任何告警。本地开发用 ALLOW_ANONYMOUS=1 显式开启。
            if settings.allow_anonymous:
                return await call_next(request)
            logger.error(
                "门禁未初始化:app_user 表为空且未设 ALLOW_ANONYMOUS → 拒绝所有请求。"
                "请运行 scripts/create_user.py 创建账号(path=%s)", path,
            )
            if path.startswith("/api/"):
                return JSONResponse(status_code=503,
                                    content={"detail": "用户系统未初始化 / Auth not initialized"})
            return RedirectResponse(url="/login", status_code=302)

        token = request.cookies.get(auth_svc.SESSION_COOKIE, "")
        if token:
            user = await auth_svc.verify_session(token)
            if user:
                request.state.user = user
                return await call_next(request)
        if _api_key_ok(request):
            request.state.user = {"id": 0, "username": "api-key", "role": "super_admin",
                                  "via": "api_key"}
            return await call_next(request)

        if path.startswith("/api/"):
            return JSONResponse(status_code=401, content={"detail": "Not authenticated"})
        return RedirectResponse(url="/login", status_code=302)


# 注意顺序：后 add 的先执行 → CORS(最外) → SessionAuth → APIKey(最内)
app.add_middleware(APIKeyMiddleware)
app.add_middleware(SessionAuthMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://cs2.kingke.dev"],
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-API-Key"],
)

app.include_router(auth_routes.router, prefix="/api/auth", tags=["auth"])
app.include_router(prices.router, prefix="/api/prices", tags=["prices"])
app.include_router(items.router, prefix="/api/items", tags=["items"])
app.include_router(inventory.router, prefix="/api/inventory", tags=["inventory"])
app.include_router(youpin.router, prefix="/api/youpin", tags=["youpin"])
app.include_router(listing.router, prefix="/api/listing", tags=["listing"])
app.include_router(dashboard.router, prefix="/api/dashboard", tags=["dashboard"])
app.include_router(analysis.router, prefix="/api/analysis", tags=["analysis"])
app.include_router(monitoring.router, prefix="/api/monitoring", tags=["monitoring"])
app.include_router(tracker.router, prefix="/api/tracker", tags=["tracker"])

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.on_event("startup")
async def startup():
    await init_db()

    # ── Background jobs ──
    _PDT = "America/Los_Angeles"  # 自动处理 PDT/PST 夏令时切换

    # ── 每日任务链：美西时间 00:00 起依次执行 ──
    # 23:55(前夜) 凭证哨兵：任务链开跑前探测悠悠 token,失效立即告警(提案6)
    from app.services.sentinel import run_credential_sentinel
    scheduler.add_job(run_credential_sentinel, "cron", hour=23, minute=55, id="credential_sentinel",
                      timezone=_PDT, misfire_grace_time=600)
    # 00:00  记录每日追踪
    scheduler.add_job(snapshot_daily, "cron", hour=0, minute=0, id="daily_tracker",
                      timezone=_PDT, misfire_grace_time=600)
    # 00:01  单品租赁实绩落库(提案9a:谁在租、租金多少,逐件归因)
    from app.services.lease_income import record_lease_income
    scheduler.add_job(record_lease_income, "cron", hour=0, minute=1, id="lease_income",
                      timezone=_PDT, misfire_grace_time=600, max_instances=1)
    # 00:02  CSQAQ 外部数据同步
    scheduler.add_job(csqaq_daily_sync, "cron", hour=0, minute=2, id="csqaq_sync",
                      timezone=_PDT, misfire_grace_time=600)
    # 00:05  SteamDT 采价（268品/3批，约5分钟完成）
    scheduler.add_job(collect_prices, "cron", hour=0, minute=5, id="price_collect",
                      timezone=_PDT, misfire_grace_time=600, max_instances=1)
    # 00:12  日聚合：将当日 price_snapshot 汇总到 price_history
    scheduler.add_job(aggregate_daily, "cron", hour=0, minute=12, id="daily_aggregate",
                      timezone=_PDT, misfire_grace_time=600)
    # 00:15  持仓快照（基于最新价格）
    scheduler.add_job(snapshot_portfolio, "cron", hour=0, minute=15, id="portfolio_snapshot",
                      timezone=_PDT, misfire_grace_time=600, max_instances=1)
    # 01:00  清理 3 天前的 price_snapshot（日聚合已保存历史）
    scheduler.add_job(cleanup_old_snapshots, "cron", hour=1, minute=0, id="cleanup_snapshots",
                      timezone=_PDT, misfire_grace_time=600, kwargs={"keep_days": 3})
    # Signal computation: DISABLED — kept for manual trigger via API
    # scheduler.add_job(compute_signals, "cron", hour=0, minute=10, id="daily_signals",
    #                   timezone=_PDT, misfire_grace_time=600)

    scheduler.start()
    logger.info("APScheduler started with 6 background jobs (daily_signals disabled)")

    # Take an immediate portfolio snapshot on startup
    try:
        await snapshot_portfolio()
    except Exception as e:
        logger.warning("Initial portfolio snapshot failed: %s", e)

    # 预热悠悠估值缓存（fire-and-forget，不阻塞启动）——
    # 否则重启后首个 overview 请求只能用 snapshot fallback 市值
    from app.api.routes.dashboard import _get_cached_rented_value, _get_cached_steam_value
    asyncio.get_event_loop().create_task(_get_cached_rented_value())
    asyncio.get_event_loop().create_task(_get_cached_steam_value())
    # 启动即跑一次凭证哨兵（部署/重启后第一时间发现 token 失效）
    asyncio.get_event_loop().create_task(run_credential_sentinel())


@app.on_event("shutdown")
async def shutdown():
    scheduler.shutdown(wait=False)


@app.get("/", include_in_schema=False)
async def serve_ui():
    return FileResponse("static/index.html")


@app.get("/login", include_in_schema=False)
async def serve_login():
    return FileResponse("static/login.html")


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.13.4"}


if __name__ == "__main__":
    uvicorn.run("main:app", host=settings.host, port=settings.port, reload=True)
