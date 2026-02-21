import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import init_db
from app.api.routes import prices, items, inventory, youpin

# ── 定时任务（部署到服务器后取消注释）──────────────────────────────────────────
# 依赖：pip install apscheduler
#
# from apscheduler.schedulers.asyncio import AsyncIOScheduler
# from app.core.database import AsyncSessionLocal
# from app.services import steamdt as steamdt_svc
# from app.services import youpin as youpin_svc
# from app.models.db_models import InventoryItem
# from sqlalchemy import select
#
# scheduler = AsyncIOScheduler()
#
# async def _scheduled_price_refresh():
#     """每小时自动拉取持仓物品最新价格（写入 price_snapshot）"""
#     async with AsyncSessionLocal() as db:
#         result = await db.execute(
#             select(InventoryItem.market_hash_name)
#             .where(InventoryItem.status.in_(["in_steam", "rented_out"]))
#             .distinct()
#         )
#         hash_names = [row[0] for row in result.all()]
#         if not hash_names:
#             return
#         chunks = [hash_names[i:i+100] for i in range(0, len(hash_names), 100)]
#         for chunk in chunks:
#             await steamdt_svc.fetch_batch_prices(chunk, db)
#             await asyncio.sleep(61)  # 批量接口 1 次/分钟
#
# async def _scheduled_lease_sync():
#     """每天同步一次悠悠租出持仓（更新 rented_out 物品列表）"""
#     async with AsyncSessionLocal() as db:
#         await youpin_svc.import_lease_records(db)
#
# # 部署时在 startup 里添加：
# # scheduler.add_job(_scheduled_price_refresh, "interval", hours=1, id="price_refresh")
# # scheduler.add_job(_scheduled_lease_sync,    "cron",     hour=4,  id="lease_sync")
# # scheduler.start()
# ──────────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="CS2 Inventory Manager",
    description="CS2 饰品量化交易监控系统",
    version="0.1.0",
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


@app.on_event("startup")
async def startup():
    await init_db()


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run("main:app", host=settings.host, port=settings.port, reload=True)
