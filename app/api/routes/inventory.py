"""
库存 + 成本管理接口

── 库存同步 ──────────────────────────────────────────────────────────
POST /api/inventory/sync                  从 Steam 同步库存

── 查询 ──────────────────────────────────────────────────────────────
GET  /api/inventory                       持仓列表（附价格 + 盈亏）
GET  /api/inventory/summary               总持仓价值汇总
GET  /api/inventory/missing-cost          列出尚未录入购入价的物品

── 成本录入（Phase 3）────────────────────────────────────────────────
PATCH /api/inventory/{asset_id}/cost      单件录入购入价
POST  /api/inventory/bulk-cost            批量录入购入价（推荐：一次提交全部）

── 价格刷新 ──────────────────────────────────────────────────────────
POST /api/inventory/refresh-prices        批量拉取最新价格

── 状态管理 ──────────────────────────────────────────────────────────
PATCH /api/inventory/{asset_id}/status    手动修正状态（如确认出售）
"""

from __future__ import annotations

import asyncio
import logging
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.db_models import InventoryItem
from app.services import steam as steam_svc
from app.services import steamdt as steamdt_svc

logger = logging.getLogger(__name__)
router = APIRouter()

VALID_STATUSES = {"in_steam", "in_storage", "rented_out", "sold"}


# ──────────────────────────────────────────────────────────────────── #
#  库存同步                                                              #
# ──────────────────────────────────────────────────────────────────── #

@router.post("/sync")
async def sync_inventory(db: AsyncSession = Depends(get_db)):
    """
    从 Steam 拉取 CS2 库存并同步。
    自动通过储物柜 instance_id 变化推断物品是存入储物柜还是租出/交易走了。
    """
    try:
        return await steam_svc.sync_inventory(db)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))


# ──────────────────────────────────────────────────────────────────── #
#  查询                                                                  #
# ──────────────────────────────────────────────────────────────────── #

@router.get("/summary")
async def portfolio_summary(db: AsyncSession = Depends(get_db)):
    """
    总持仓价值汇总（in_steam + rented_out，不含 in_storage 收藏品）。
    """
    return await steam_svc.get_portfolio_summary(db)


@router.get("/missing-cost")
async def missing_cost(db: AsyncSession = Depends(get_db)):
    """
    列出尚未录入购入价的持仓物品，方便按此列表逐一补录。
    """
    result = await db.execute(
        select(InventoryItem)
        .where(
            InventoryItem.status.in_(["in_steam", "rented_out"]),
            InventoryItem.purchase_price.is_(None),
        )
        .order_by(InventoryItem.market_hash_name)
    )
    items = result.scalars().all()
    return {
        "total": len(items),
        "data": [
            {
                "asset_id": i.asset_id,
                "market_hash_name": i.market_hash_name,
                "name": i.name,
                "status": i.status,
            }
            for i in items
        ],
    }


@router.get("/")
async def list_inventory(
    status: Optional[str] = Query(
        None,
        description=(
            "状态筛选：in_steam | rented_out | in_storage | sold | all\n"
            "默认返回全持仓（in_steam + rented_out，不含收藏品）"
        ),
    ),
    db: AsyncSession = Depends(get_db),
):
    """
    持仓列表，附带 BUFF/悠悠/Steam 最新快照价格和盈亏。
    """
    if status == "all":
        status_filter = list(VALID_STATUSES)
    elif status in VALID_STATUSES:
        status_filter = [status]
    else:
        status_filter = ["in_steam", "rented_out"]

    items = await steam_svc.get_inventory_with_prices(db, status_filter=status_filter)
    return {"total": len(items), "status_filter": status_filter, "data": items}


# ──────────────────────────────────────────────────────────────────── #
#  成本录入                                                              #
# ──────────────────────────────────────────────────────────────────── #

class CostPatch(BaseModel):
    purchase_price: float
    purchase_date: Optional[str] = None       # YYYY-MM-DD，可选
    purchase_platform: Optional[str] = None   # BUFF / YOUPIN / 手动 等，可选


@router.patch("/{asset_id}/cost")
async def patch_cost(
    asset_id: str,
    body: CostPatch,
    db: AsyncSession = Depends(get_db),
):
    """
    单件录入购入价。asset_id 来自 GET /api/inventory 返回的列表。

    示例：
    PATCH /api/inventory/49590018150/cost
    { "purchase_price": 3200, "purchase_date": "2024-11-20", "purchase_platform": "BUFF" }
    """
    result = await db.execute(
        select(InventoryItem).where(InventoryItem.asset_id == asset_id)
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail=f"找不到 asset_id={asset_id} 的物品")

    item.purchase_price = body.purchase_price
    if body.purchase_date:
        item.purchase_date = body.purchase_date
    if body.purchase_platform:
        item.purchase_platform = body.purchase_platform
    await db.commit()

    return {
        "asset_id": asset_id,
        "market_hash_name": item.market_hash_name,
        "purchase_price": item.purchase_price,
        "purchase_date": item.purchase_date,
        "purchase_platform": item.purchase_platform,
    }


class BulkCostEntry(BaseModel):
    asset_id: str
    purchase_price: float
    purchase_date: Optional[str] = None
    purchase_platform: Optional[str] = None


class BulkCostRequest(BaseModel):
    items: List[BulkCostEntry]


@router.post("/bulk-cost")
async def bulk_cost(
    body: BulkCostRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    批量录入购入价，一次提交多件。推荐首次录入时使用。

    示例 Body：
    {
      "items": [
        { "asset_id": "49590018150", "purchase_price": 3200, "purchase_date": "2024-11-20", "purchase_platform": "BUFF" },
        { "asset_id": "49578625318", "purchase_price": 6800, "purchase_date": "2024-10-05", "purchase_platform": "YOUPIN" }
      ]
    }
    """
    asset_ids = [e.asset_id for e in body.items]
    result = await db.execute(
        select(InventoryItem).where(InventoryItem.asset_id.in_(asset_ids))
    )
    db_map: Dict[str, InventoryItem] = {i.asset_id: i for i in result.scalars().all()}

    updated = []
    not_found = []

    for entry in body.items:
        item = db_map.get(entry.asset_id)
        if not item:
            not_found.append(entry.asset_id)
            continue
        item.purchase_price = entry.purchase_price
        if entry.purchase_date:
            item.purchase_date = entry.purchase_date
        if entry.purchase_platform:
            item.purchase_platform = entry.purchase_platform
        updated.append({
            "asset_id": entry.asset_id,
            "market_hash_name": item.market_hash_name,
            "purchase_price": item.purchase_price,
        })

    await db.commit()
    return {
        "updated": len(updated),
        "not_found": not_found,
        "items": updated,
    }


# ──────────────────────────────────────────────────────────────────── #
#  价格刷新                                                              #
# ──────────────────────────────────────────────────────────────────── #

@router.post("/refresh-prices")
async def refresh_prices(
    status: str = Query(
        "in_steam,rented_out",
        description="刷新哪些状态的物品，逗号分隔（in_steam | rented_out | in_storage | all）",
    ),
    db: AsyncSession = Depends(get_db),
):
    """
    对持仓物品批量拉取最新价格（写入 price_snapshot）。
    批量接口限速 1 次/分钟，超 100 件自动分批等待。
    """
    if status == "all":
        status_list = list(VALID_STATUSES)
    else:
        status_list = [s.strip() for s in status.split(",") if s.strip() in VALID_STATUSES]

    if not status_list:
        raise HTTPException(status_code=400, detail=f"无效 status，可选: {VALID_STATUSES}")

    result = await db.execute(
        select(InventoryItem.market_hash_name)
        .where(InventoryItem.status.in_(status_list))
        .distinct()
    )
    hash_names = [row[0] for row in result.all()]
    if not hash_names:
        return {"message": "无符合条件的物品", "total": 0}

    chunks = [hash_names[i : i + 100] for i in range(0, len(hash_names), 100)]
    total_fetched = 0

    for idx, chunk in enumerate(chunks):
        if idx > 0:
            logger.info("refresh-prices: 等待 61s（批量接口限速 1/min）%d/%d", idx + 1, len(chunks))
            await asyncio.sleep(61)
        try:
            results = await steamdt_svc.fetch_batch_prices(chunk, db)
            total_fetched += sum(len(r.data_list) for r in results)
        except Exception as e:
            logger.error("refresh-prices batch %d 失败: %s", idx, e)

    return {"status_filter": status_list, "total_items": len(hash_names), "platform_rows": total_fetched}


# ──────────────────────────────────────────────────────────────────── #
#  状态管理                                                              #
# ──────────────────────────────────────────────────────────────────── #

class StatusPatch(BaseModel):
    status: str


@router.patch("/{asset_id}/status")
async def patch_status(
    asset_id: str,
    body: StatusPatch,
    db: AsyncSession = Depends(get_db),
):
    """
    手动修正物品状态。例如：将 rented_out 改为 sold，或将 in_storage 改为 in_steam。
    """
    if body.status not in VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"无效 status，可选: {VALID_STATUSES}")

    result = await db.execute(
        select(InventoryItem).where(InventoryItem.asset_id == asset_id)
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail=f"找不到 asset_id={asset_id}")

    old = item.status
    item.status = body.status
    await db.commit()
    return {"asset_id": asset_id, "market_hash_name": item.market_hash_name, "old_status": old, "new_status": body.status}
