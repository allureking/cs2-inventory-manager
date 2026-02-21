"""
饰品基础信息接口

POST /api/items/sync-base    全量同步 CS2 饰品基础信息（1 次/天）
GET  /api/items              列出数据库中的饰品（支持搜索）
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.db_models import Item
from app.services import steamdt as svc

router = APIRouter()


@router.post("/sync-base")
async def sync_base(db: AsyncSession = Depends(get_db)):
    """
    从 SteamDT /base 接口全量拉取饰品信息，upsert 到本地数据库。
    注意：API 限制每天只能调用 1 次，请勿频繁触发。
    """
    count = await svc.sync_base_info(db)
    return {"synced": count, "message": f"成功同步 {count} 条饰品基础信息"}


@router.get("/")
async def list_items(
    q: Optional[str] = Query(None, description="按中文名或 marketHashName 模糊搜索"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """列出数据库中的饰品，支持关键词搜索"""
    stmt = select(Item)
    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(
            Item.name.like(pattern) | Item.market_hash_name.like(pattern)
        )
    total_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(total_stmt)).scalar_one()

    stmt = stmt.offset(offset).limit(limit).order_by(Item.market_hash_name)
    rows = (await db.execute(stmt)).scalars().all()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "data": [
            {
                "id": r.id,
                "market_hash_name": r.market_hash_name,
                "name": r.name,
                "updated_at": r.updated_at,
            }
            for r in rows
        ],
    }
