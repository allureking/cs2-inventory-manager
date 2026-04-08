import logging
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

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

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://cs2.kingke.dev",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
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

    # Price collection: every 30 min, on :00/:30 (UTC, 不受时区影响)
    scheduler.add_job(collect_prices, "cron", minute="0,30", id="price_collect",
                      misfire_grace_time=300, max_instances=1)
    # Portfolio snapshot: every 30 min, on :15/:45 (UTC, 不受时区影响)
    scheduler.add_job(snapshot_portfolio, "cron", minute="15,45", id="portfolio_snapshot",
                      misfire_grace_time=300, max_instances=1)
    # Cleanup old snapshots: 01:00 PDT
    scheduler.add_job(cleanup_old_snapshots, "cron", hour=1, minute=0, id="cleanup_snapshots",
                      timezone=_PDT, misfire_grace_time=600)

    # ── 每日任务：美西时间 00:00 起依次执行 ──
    # Daily tracker snapshot: 00:00 PDT
    scheduler.add_job(snapshot_daily, "cron", hour=0, minute=0, id="daily_tracker",
                      timezone=_PDT, misfire_grace_time=600)
    # CSQAQ data sync: 00:02 PDT
    scheduler.add_job(csqaq_daily_sync, "cron", hour=0, minute=2, id="csqaq_sync",
                      timezone=_PDT, misfire_grace_time=600)
    # Daily aggregation: 00:05 PDT
    scheduler.add_job(aggregate_daily, "cron", hour=0, minute=5, id="daily_aggregate",
                      timezone=_PDT, misfire_grace_time=600)
    # Signal computation: 00:10 PDT
    scheduler.add_job(compute_signals, "cron", hour=0, minute=10, id="daily_signals",
                      timezone=_PDT, misfire_grace_time=600)

    scheduler.start()
    logger.info("APScheduler started with 7 background jobs")

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
