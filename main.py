import logging
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.core.database import init_db
from app.api.routes import prices, items, inventory, youpin, listing
from app.api.routes import dashboard, analysis, monitoring

# ── 定时任务 ────────────────────────────────────────────────────────────────
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.services.collector import (
    collect_prices,
    aggregate_daily,
    compute_signals,
    cleanup_old_snapshots,
    snapshot_portfolio,
)

scheduler = AsyncIOScheduler()
logger = logging.getLogger(__name__)
# ────────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="CS2 Inventory Manager",
    description="CS2 饰品量化交易监控系统",
    version="0.3.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.on_event("startup")
async def startup():
    await init_db()

    # ── Background jobs ──
    # Price collection: every 30 min
    scheduler.add_job(collect_prices, "interval", minutes=30, id="price_collect",
                      misfire_grace_time=300)
    # Daily aggregation: 00:05 UTC
    scheduler.add_job(aggregate_daily, "cron", hour=0, minute=5, id="daily_aggregate",
                      misfire_grace_time=600)
    # Signal computation: 00:10 UTC
    scheduler.add_job(compute_signals, "cron", hour=0, minute=10, id="daily_signals",
                      misfire_grace_time=600)
    # Portfolio snapshot: every 30 min (offset +5 from price collect for fresh data)
    scheduler.add_job(snapshot_portfolio, "interval", minutes=30, id="portfolio_snapshot",
                      misfire_grace_time=300)
    # Cleanup old snapshots: 01:00 UTC
    scheduler.add_job(cleanup_old_snapshots, "cron", hour=1, minute=0, id="cleanup_snapshots",
                      misfire_grace_time=600)

    scheduler.start()
    logger.info("APScheduler started with 5 background jobs")

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
    return {"status": "ok", "version": "0.3.0"}


if __name__ == "__main__":
    uvicorn.run("main:app", host=settings.host, port=settings.port, reload=True)
