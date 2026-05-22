"""
上架管理 API

GET  /api/listing/shelf/sell       — 出售货架列表
GET  /api/listing/shelf/lease      — 出租货架列表
POST /api/listing/smart            — 一键智能上架（查价+定价+上架）
POST /api/listing/sell             — 手动出售上架
POST /api/listing/lease            — 手动出租上架
POST /api/listing/both             — 可租可售上架
PUT  /api/listing/reprice          — 改价
DELETE /api/listing/{commodity_id} — 下架
GET  /api/listing/preview          — 预览定价（仅查价不上架）
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.db_models import ListingSnapshot, ListingSnapshotItem, InventoryItem
from app.services.youpin import TokenExpiredError
from app.services.youpin_listing import (
    calc_lease_price,
    calc_sell_price,
    change_price,
    delist_item,
    fetch_market_lease_price,
    fetch_market_sell_price,
    get_lease_shelf,
    get_sell_shelf,
    get_unlisted_items,
    list_for_both,
    list_for_lease,
    list_for_sell,
    smart_list,
    _MEMBER_MAX_DAYS,
)

router = APIRouter()


def _handle_token_error(e: Exception):
    if isinstance(e, TokenExpiredError):
        raise HTTPException(status_code=401, detail=str(e))
    raise HTTPException(status_code=500, detail=str(e))


# ── 货架查询 ────────────────────────────────────────────────────────────────

@router.get("/shelf/sell")
async def get_sell_shelf_api(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    """获取当前悠悠出售货架列表"""
    try:
        return await get_sell_shelf(page=page, page_size=page_size)
    except Exception as e:
        _handle_token_error(e)


@router.get("/shelf/lease")
async def get_lease_shelf_api(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    """获取当前悠悠出租货架列表"""
    try:
        return await get_lease_shelf(page=page, page_size=page_size)
    except Exception as e:
        _handle_token_error(e)


@router.get("/shelf/unlisted")
async def get_unlisted_api(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    """获取完整库存中尚未上架的饰品（可快速上架）"""
    try:
        return await get_unlisted_items(page=page, page_size=page_size)
    except Exception as e:
        _handle_token_error(e)


class BatchDelistRequest(BaseModel):
    commodity_ids: list


@router.post("/batch-delist")
async def batch_delist_api(body: BatchDelistRequest):
    """批量下架物品"""
    if not body.commodity_ids:
        raise HTTPException(status_code=400, detail="至少选择一件物品")
    try:
        return await delist_item(body.commodity_ids)
    except Exception as e:
        _handle_token_error(e)


# ── 价格预览 ────────────────────────────────────────────────────────────────

@router.get("/preview")
async def preview_price(
    template_id: int = Query(...),
    abrade: Optional[float] = Query(None),
    buy_price: float = Query(0.0),
    take_profit_ratio: float = Query(0.0),
    fix_lease_ratio: float = Query(0.0),
):
    """查询市场价并计算建议定价（不执行上架）"""
    try:
        market_sell = await fetch_market_sell_price(template_id, abrade)
        market_lease = await fetch_market_lease_price(template_id)

        suggested_sell = calc_sell_price(
            market_sell,
            buy_price=buy_price,
            take_profit_ratio=take_profit_ratio,
        )
        suggested_lease = calc_lease_price(
            market_lease,
            sell_price=suggested_sell or 0.0,
            fix_lease_ratio=fix_lease_ratio,
        )

        return {
            "template_id": template_id,
            "market_sell_top5": [
                {"price": item.get("price") or item.get("Price"),
                 "abrade": item.get("abrade")}
                for item in market_sell[:5]
            ],
            "suggested_sell": suggested_sell,
            "suggested_lease": suggested_lease,
        }
    except Exception as e:
        _handle_token_error(e)


# ── 智能上架 ────────────────────────────────────────────────────────────────

class SmartListRequest(BaseModel):
    asset_id: str
    template_id: int
    abrade: Optional[float] = None
    mode: str = "sell"              # "sell" | "lease" | "both"
    buy_price: float = 0.0
    take_profit_ratio: float = 0.0
    fix_lease_ratio: float = 0.0
    use_undercut: bool = True
    member_level: int = 3           # 出租大会员等级 1/2/3 → max_days 8/30/90


@router.post("/smart")
async def smart_list_api(body: SmartListRequest):
    """一键智能上架：自动查价 → 定价 → 上架"""
    try:
        return await smart_list(
            asset_id=body.asset_id,
            template_id=body.template_id,
            abrade=body.abrade,
            mode=body.mode,
            buy_price=body.buy_price,
            take_profit_ratio=body.take_profit_ratio,
            fix_lease_ratio=body.fix_lease_ratio,
            use_undercut=body.use_undercut,
            member_level=body.member_level,
        )
    except Exception as e:
        _handle_token_error(e)


class BatchSmartRepriceItem(BaseModel):
    commodity_id: int
    template_id: int
    abrade: Optional[float] = None
    is_can_lease: bool = False


class BatchSmartRepriceRequest(BaseModel):
    items: list[BatchSmartRepriceItem]
    use_undercut: bool = True
    take_profit_ratio: float = 0.0


@router.post("/batch-smart-reprice")
async def batch_smart_reprice_api(body: BatchSmartRepriceRequest):
    """
    批量智能改价：查询市场价 → 计算建议价 → 逐件改价。
    每件间隔 0.3s 避免限速，最多支持 30 件/批次。
    """
    import asyncio
    if not body.items:
        raise HTTPException(status_code=400, detail="至少选择一件物品")
    if len(body.items) > 30:
        raise HTTPException(status_code=400, detail="单次批量最多 30 件")

    results = []
    try:
        for item in body.items:
            try:
                if item.is_can_lease:
                    market_data = await fetch_market_lease_price(item.template_id)
                    lease_info = calc_lease_price(market_data)
                    if lease_info is None:
                        results.append({"ok": False, "commodity_id": item.commodity_id, "error": "无法获取市场租价"})
                        continue
                    await change_price(
                        commodity_id=item.commodity_id,
                        lease_unit=lease_info["lease_unit"],
                        long_lease_unit=lease_info["long_lease_unit"],
                        deposit=lease_info["deposit"],
                        is_can_sold=False,
                        is_can_lease=True,
                    )
                    results.append({
                        "ok": True, "commodity_id": item.commodity_id,
                        "lease_unit": lease_info["lease_unit"],
                        "deposit": lease_info["deposit"],
                    })
                else:
                    market_data = await fetch_market_sell_price(item.template_id, item.abrade)
                    sell_price = calc_sell_price(
                        market_data,
                        take_profit_ratio=body.take_profit_ratio,
                        use_undercut=body.use_undercut,
                    )
                    if sell_price is None:
                        results.append({"ok": False, "commodity_id": item.commodity_id, "error": "无法获取市场售价"})
                        continue
                    await change_price(
                        commodity_id=item.commodity_id,
                        sell_price=sell_price,
                        is_can_sold=True,
                        is_can_lease=False,
                    )
                    results.append({"ok": True, "commodity_id": item.commodity_id, "sell_price": sell_price})
            except Exception as e:
                results.append({"ok": False, "commodity_id": item.commodity_id, "error": str(e)})
            await asyncio.sleep(0.3)

        ok_count = sum(1 for r in results if r.get("ok"))
        return {"ok_count": ok_count, "total": len(results), "results": results}
    except Exception as e:
        _handle_token_error(e)


# ── 手动上架 ────────────────────────────────────────────────────────────────

class SellRequest(BaseModel):
    asset_id: str
    price: float


class LeaseRequest(BaseModel):
    asset_id: str
    lease_unit: float
    long_lease_unit: float
    deposit: float
    max_days: int = 30


class BothRequest(BaseModel):
    asset_id: str
    sell_price: float
    lease_unit: float
    long_lease_unit: float
    deposit: float
    max_days: int = 30


@router.post("/sell")
async def list_sell_api(body: SellRequest):
    """手动出售上架"""
    try:
        return await list_for_sell(body.asset_id, body.price)
    except Exception as e:
        _handle_token_error(e)


@router.post("/lease")
async def list_lease_api(body: LeaseRequest):
    """手动出租上架"""
    try:
        return await list_for_lease(
            body.asset_id, body.lease_unit, body.long_lease_unit,
            body.deposit, body.max_days,
        )
    except Exception as e:
        _handle_token_error(e)


@router.post("/both")
async def list_both_api(body: BothRequest):
    """可租可售同时上架"""
    try:
        return await list_for_both(
            body.asset_id, body.sell_price,
            body.lease_unit, body.long_lease_unit,
            body.deposit, body.max_days,
        )
    except Exception as e:
        _handle_token_error(e)


# ── 改价 ────────────────────────────────────────────────────────────────────

class RepriceRequest(BaseModel):
    commodity_id: int
    sell_price: Optional[float] = None
    lease_unit: Optional[float] = None
    long_lease_unit: Optional[float] = None
    deposit: Optional[float] = None
    is_can_sold: bool = True
    is_can_lease: bool = False


@router.put("/reprice")
async def reprice_api(body: RepriceRequest):
    """修改已上架物品价格（使用 CommodityId）"""
    try:
        return await change_price(
            commodity_id=body.commodity_id,
            sell_price=body.sell_price,
            lease_unit=body.lease_unit,
            long_lease_unit=body.long_lease_unit,
            deposit=body.deposit,
            is_can_sold=body.is_can_sold,
            is_can_lease=body.is_can_lease,
        )
    except Exception as e:
        _handle_token_error(e)


# ── 下架 ────────────────────────────────────────────────────────────────────

@router.delete("/{commodity_id}")
async def delist_api(commodity_id: int):
    """下架物品"""
    try:
        return await delist_item([commodity_id])
    except Exception as e:
        _handle_token_error(e)


# ── 挂售快照 ──────────────────────────────────────────────────────────────────

log = logging.getLogger(__name__)


class SnapshotCreate(BaseModel):
    name: str = ""
    shelf_type: str = "sell"
    notes: Optional[str] = None


@router.post("/snapshot")
async def create_snapshot(body: SnapshotCreate):
    """拉取当前货架数据并保存为快照"""
    try:
        shelf_type = body.shelf_type
        all_items: list[dict] = []
        page = 1
        while True:
            if shelf_type == "lease":
                result = await get_lease_shelf(page=page, page_size=100)
            else:
                result = await get_sell_shelf(page=page, page_size=100)
            items = result.get("items", [])
            all_items.extend(items)
            if len(all_items) >= result.get("total", 0) or not items:
                break
            page += 1

        if not all_items:
            raise HTTPException(400, "货架为空，无数据可快照")

        total_value = sum(float(i.get("price") or 0) for i in all_items)
        snap_name = body.name or f"{'出售' if shelf_type == 'sell' else '出租'}快照 ({len(all_items)}件)"

        async with AsyncSessionLocal() as sess:
            # 查询本地成本数据用于关联
            cost_map: dict[str, float] = {}
            inv_rows = (await sess.execute(
                select(InventoryItem.asset_id, InventoryItem.purchase_price, InventoryItem.purchase_price_manual)
            )).all()
            for row in inv_rows:
                cost = row.purchase_price_manual or row.purchase_price
                if cost and row.asset_id:
                    cost_map[str(row.asset_id)] = cost

            snapshot = ListingSnapshot(
                name=snap_name,
                shelf_type=shelf_type,
                item_count=len(all_items),
                total_value=round(total_value, 2),
                notes=body.notes,
            )
            sess.add(snapshot)
            await sess.flush()

            for item in all_items:
                asset_id = str(item.get("steamAssetId") or "")
                sess.add(ListingSnapshotItem(
                    snapshot_id=snapshot.id,
                    commodity_hash_name=item.get("commodityHashName") or "",
                    name=item.get("name") or "",
                    img_url=item.get("imgUrl"),
                    abrade=item.get("abrade"),
                    template_id=item.get("templateId"),
                    commodity_id=item.get("commodityId"),
                    steam_asset_id=asset_id or None,
                    sell_price=item.get("price"),
                    lease_unit_price=item.get("leaseUnitPrice"),
                    long_lease_price=item.get("longLeasePrice"),
                    lease_deposit=item.get("leaseDeposit"),
                    lease_max_days=item.get("leaseMaxDays"),
                    open_sublet=item.get("openSublet"),
                    purchase_price=cost_map.get(asset_id),
                ))
            await sess.commit()

        return {"id": snapshot.id, "name": snap_name, "item_count": len(all_items), "total_value": round(total_value, 2)}
    except HTTPException:
        raise
    except Exception as e:
        _handle_token_error(e)
        raise HTTPException(500, str(e))


@router.get("/snapshots")
async def list_snapshots():
    """列出所有快照"""
    async with AsyncSessionLocal() as sess:
        rows = (await sess.execute(
            select(ListingSnapshot).order_by(ListingSnapshot.created_at.desc())
        )).scalars().all()
        return [
            {
                "id": s.id, "name": s.name, "shelf_type": s.shelf_type,
                "item_count": s.item_count, "total_value": s.total_value,
                "notes": s.notes,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in rows
        ]


@router.get("/snapshot/{snapshot_id}")
async def get_snapshot(snapshot_id: int):
    """获取快照详情（含所有饰品）"""
    async with AsyncSessionLocal() as sess:
        snap = await sess.get(ListingSnapshot, snapshot_id)
        if not snap:
            raise HTTPException(404, "快照不存在")
        items = (await sess.execute(
            select(ListingSnapshotItem)
            .where(ListingSnapshotItem.snapshot_id == snapshot_id)
            .order_by(ListingSnapshotItem.sell_price.desc())
        )).scalars().all()
        return {
            "id": snap.id, "name": snap.name, "shelf_type": snap.shelf_type,
            "item_count": snap.item_count, "total_value": snap.total_value,
            "notes": snap.notes,
            "created_at": snap.created_at.isoformat() if snap.created_at else None,
            "items": [
                {
                    "id": i.id,
                    "commodity_hash_name": i.commodity_hash_name,
                    "name": i.name,
                    "img_url": i.img_url,
                    "abrade": i.abrade,
                    "template_id": i.template_id,
                    "commodity_id": i.commodity_id,
                    "steam_asset_id": i.steam_asset_id,
                    "sell_price": i.sell_price,
                    "lease_unit_price": i.lease_unit_price,
                    "long_lease_price": i.long_lease_price,
                    "lease_deposit": i.lease_deposit,
                    "lease_max_days": i.lease_max_days,
                    "open_sublet": i.open_sublet,
                    "purchase_price": i.purchase_price,
                }
                for i in items
            ],
        }


@router.delete("/snapshot/{snapshot_id}")
async def delete_snapshot(snapshot_id: int):
    """删除快照"""
    async with AsyncSessionLocal() as sess:
        snap = await sess.get(ListingSnapshot, snapshot_id)
        if not snap:
            raise HTTPException(404, "快照不存在")
        await sess.execute(delete(ListingSnapshotItem).where(ListingSnapshotItem.snapshot_id == snapshot_id))
        await sess.delete(snap)
        await sess.commit()
    return {"ok": True}
