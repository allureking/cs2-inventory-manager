"""
Dashboard API — 前端所需数据接口

Endpoints:
  GET  /api/dashboard/overview          — 投资组合汇总统计
  GET  /api/dashboard/items             — 分页/过滤/排序的持仓列表
  PATCH /api/dashboard/items/{id}/manual-price — 设置/清除手动购入价
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, or_, and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.db_models import InventoryItem

router = APIRouter()

_ACTIVE = ["in_steam", "rented_out", "in_storage"]


@router.get("/overview")
async def get_overview(db: AsyncSession = Depends(get_db)):
    """投资组合汇总统计：各状态数量、总成本、定价覆盖率。"""

    # --- 各状态数量 ---
    status_rows = (
        await db.execute(
            select(InventoryItem.status, func.count(InventoryItem.id)).group_by(
                InventoryItem.status
            )
        )
    ).all()
    status_counts: dict = dict(status_rows)
    active_count = sum(status_counts.get(s, 0) for s in _ACTIVE)

    # --- 活跃持仓中已定价数量（auto 或 manual 任一非空） ---
    priced_count = (
        await db.execute(
            select(func.count(InventoryItem.id)).where(
                InventoryItem.status.in_(_ACTIVE),
                or_(
                    InventoryItem.purchase_price.isnot(None),
                    InventoryItem.purchase_price_manual.isnot(None),
                ),
            )
        )
    ).scalar() or 0

    # --- 手动定价数量 ---
    manual_count = (
        await db.execute(
            select(func.count(InventoryItem.id)).where(
                InventoryItem.status.in_(_ACTIVE),
                InventoryItem.purchase_price_manual.isnot(None),
            )
        )
    ).scalar() or 0

    # --- 总成本：COALESCE(manual, auto) ---
    total_cost = (
        await db.execute(
            select(
                func.sum(
                    func.coalesce(
                        InventoryItem.purchase_price_manual,
                        InventoryItem.purchase_price,
                    )
                )
            ).where(InventoryItem.status.in_(_ACTIVE))
        )
    ).scalar() or 0

    # --- 各状态成本分解 ---
    rented_cost = (
        await db.execute(
            select(
                func.sum(
                    func.coalesce(
                        InventoryItem.purchase_price_manual,
                        InventoryItem.purchase_price,
                    )
                )
            ).where(InventoryItem.status == "rented_out")
        )
    ).scalar() or 0

    steam_cost = (
        await db.execute(
            select(
                func.sum(
                    func.coalesce(
                        InventoryItem.purchase_price_manual,
                        InventoryItem.purchase_price,
                    )
                )
            ).where(InventoryItem.status == "in_steam")
        )
    ).scalar() or 0

    return {
        "total_active": active_count,
        "status_breakdown": {
            "in_steam": status_counts.get("in_steam", 0),
            "rented_out": status_counts.get("rented_out", 0),
            "in_storage": status_counts.get("in_storage", 0),
            "sold": status_counts.get("sold", 0),
        },
        "cost_breakdown": {
            "rented_out": round(rented_cost, 2),
            "in_steam": round(steam_cost, 2),
        },
        "priced_count": priced_count,
        "unpriced_count": active_count - priced_count,
        "manual_price_count": manual_count,
        "total_cost": round(total_cost, 2),
        "coverage_pct": round(priced_count / active_count * 100, 1) if active_count > 0 else 0,
    }


@router.get("/items")
async def list_items(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    search: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    priced_filter: Optional[str] = Query(None),  # "priced" | "unpriced"
    sort_by: str = Query("first_seen_at"),
    sort_order: str = Query("desc"),
    db: AsyncSession = Depends(get_db),
):
    """分页/过滤/排序持仓列表。"""

    q = select(InventoryItem)

    # 搜索（饰品英文名）
    if search:
        q = q.where(
            or_(
                InventoryItem.market_hash_name.ilike(f"%{search}%"),
                InventoryItem.name.ilike(f"%{search}%"),
            )
        )

    # 状态过滤
    if status:
        q = q.where(InventoryItem.status == status)

    # 定价过滤
    if priced_filter == "priced":
        q = q.where(
            or_(
                InventoryItem.purchase_price.isnot(None),
                InventoryItem.purchase_price_manual.isnot(None),
            )
        )
    elif priced_filter == "unpriced":
        q = q.where(
            and_(
                InventoryItem.purchase_price.is_(None),
                InventoryItem.purchase_price_manual.is_(None),
            )
        )

    # 总数
    count_q = select(func.count()).select_from(q.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    # 排序
    _effective = func.coalesce(
        InventoryItem.purchase_price_manual, InventoryItem.purchase_price
    )
    sortable = {
        "market_hash_name": InventoryItem.market_hash_name,
        "status": InventoryItem.status,
        "purchase_price": InventoryItem.purchase_price,
        "effective_price": _effective,
        "purchase_date": InventoryItem.purchase_date,
        "abrade": InventoryItem.abrade,
        "first_seen_at": InventoryItem.first_seen_at,
    }
    col = sortable.get(sort_by, InventoryItem.first_seen_at)
    if sort_order == "asc":
        q = q.order_by(col.asc().nulls_last())
    else:
        q = q.order_by(col.desc().nulls_last())

    q = q.offset((page - 1) * page_size).limit(page_size)
    rows = (await db.execute(q)).scalars().all()

    def to_dict(item: InventoryItem) -> dict:
        effective = (
            item.purchase_price_manual
            if item.purchase_price_manual is not None
            else item.purchase_price
        )
        return {
            "id": item.id,
            "market_hash_name": item.market_hash_name,
            "name": item.name,
            "status": item.status,
            "class_id": item.class_id,
            "abrade": item.abrade,
            "icon_url": item.icon_url,
            "purchase_price": item.purchase_price,
            "purchase_price_manual": item.purchase_price_manual,
            "effective_price": effective,
            "purchase_date": item.purchase_date,
            "purchase_platform": item.purchase_platform,
            "youpin_commodity_id": item.youpin_commodity_id,
            "first_seen_at": item.first_seen_at.isoformat() if item.first_seen_at else None,
            "last_seen_in_steam_at": (
                item.last_seen_in_steam_at.isoformat()
                if item.last_seen_in_steam_at
                else None
            ),
        }

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [to_dict(r) for r in rows],
    }


class ManualPriceBody(BaseModel):
    price: Optional[float] = None


@router.patch("/items/{item_id}/manual-price")
async def set_manual_price(
    item_id: int,
    body: ManualPriceBody,
    db: AsyncSession = Depends(get_db),
):
    """设置或清除手动购入价（price=null 表示清除）。"""
    result = await db.execute(
        select(InventoryItem).where(InventoryItem.id == item_id)
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    item.purchase_price_manual = body.price
    await db.commit()

    effective = (
        item.purchase_price_manual
        if item.purchase_price_manual is not None
        else item.purchase_price
    )
    return {
        "id": item.id,
        "purchase_price_manual": item.purchase_price_manual,
        "effective_price": effective,
    }
