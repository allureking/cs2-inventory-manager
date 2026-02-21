"""
价格相关接口

GET  /api/prices/single?market_hash_name=...       单品实时价格（调 API + 写库）
POST /api/prices/batch                              批量实时价格（调 API + 写库）
GET  /api/prices/avg?market_hash_name=...&days=7   近 N 天均价（调 API + 写库）
GET  /api/prices/cached?market_hash_name=...       读库中最新价格快照（不调 API）
"""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.db_models import PriceSnapshot
from app.schemas.steamdt import AveragePriceVO, BatchPlatformPriceVO, PlatformPriceVO
from app.services import steamdt as svc

router = APIRouter()


class BatchPriceRequest(BaseModel):
    market_hash_names: List[str]


@router.get("/single", response_model=List[PlatformPriceVO])
async def get_single_price(
    market_hash_name: str = Query(..., description="Steam market hash name，如 'AK-47 | Redline (Field-Tested)'"),
    db: AsyncSession = Depends(get_db),
):
    """查询单个饰品在所有平台的实时价格，结果自动写入数据库"""
    return await svc.fetch_single_price(market_hash_name, db)


@router.post("/batch", response_model=List[BatchPlatformPriceVO])
async def get_batch_prices(
    body: BatchPriceRequest,
    db: AsyncSession = Depends(get_db),
):
    """批量查询价格（最多 100 个）。注意 API 限制 1 次/分钟。"""
    return await svc.fetch_batch_prices(body.market_hash_names, db)


@router.get("/avg", response_model=AveragePriceVO)
async def get_avg_price(
    market_hash_name: str = Query(...),
    days: int = Query(7, ge=1, le=90, description="统计天数，默认 7"),
    db: AsyncSession = Depends(get_db),
):
    """查询近 N 天均价，结果写入数据库"""
    return await svc.fetch_avg_price(market_hash_name, db, days)


@router.get("/cached")
async def get_cached_price(
    market_hash_name: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """从数据库读取最新价格快照（不消耗 API 配额）"""
    rows: List[PriceSnapshot] = await svc.get_latest_snapshots(market_hash_name, db)
    if not rows:
        return {"market_hash_name": market_hash_name, "data": [], "message": "暂无缓存，请先调用 /single 或 /batch"}
    return {
        "market_hash_name": market_hash_name,
        "snapshot_minute": rows[0].snapshot_minute,
        "data": [
            {
                "platform": r.platform,
                "sell_price": r.sell_price,
                "sell_count": r.sell_count,
                "bidding_price": r.bidding_price,
                "bidding_count": r.bidding_count,
            }
            for r in rows
        ],
    }
