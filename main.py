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
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings
from app.core.database import init_db
from app.api.routes import prices, items, inventory, youpin, listing
from app.api.routes import dashboard, analysis, monitoring, tracker

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
    version="0.6.0",
)

class APIKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not settings.app_api_key:
            return await call_next(request)
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return await call_next(request)
        if not request.url.path.startswith("/api/"):
            return await call_next(request)
        auth = request.headers.get("Authorization", "")
        if auth == f"Bearer {settings.app_api_key}":
            return await call_next(request)
        return JSONResponse(status_code=401, content={"detail": "Unauthorized"})


app.add_middleware(APIKeyMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://cs2.kingke.dev"],
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

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
    # 00:00  记录每日追踪
    scheduler.add_job(snapshot_daily, "cron", hour=0, minute=0, id="daily_tracker",
                      timezone=_PDT, misfire_grace_time=600)
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


@app.on_event("shutdown")
async def shutdown():
    scheduler.shutdown(wait=False)


@app.get("/", include_in_schema=False)
async def serve_ui():
    return FileResponse("static/index.html")


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.6.0"}


if __name__ == "__main__":
    uvicorn.run("main:app", host=settings.host, port=settings.port, reload=True)
