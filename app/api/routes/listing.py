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

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.services.youpin import TokenExpiredError
from app.services.youpin_listing import (
    calc_lease_price,
    calc_sell_price,
    cancel_sublet,
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


class CancelSubletRequest(BaseModel):
    order_id: str


@router.post("/cancel-sublet")
async def cancel_sublet_api(body: CancelSubletRequest):
    """取消0CD转租（将白玩中订单改回普通租出状态）"""
    try:
        return await cancel_sublet(body.order_id)
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
        )
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
        return await delist_item(commodity_id)
    except Exception as e:
        _handle_token_error(e)
