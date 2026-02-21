"""
悠悠有品记录导入接口

POST /api/youpin/import/stock  拉取在库存（Steam 保护期）→ status=in_steam + purchase_price
POST /api/youpin/import/lease  拉取当前租出订单 → 写入 rented_out 持仓（主力数据源）
POST /api/youpin/import/buy    拉取历史购买记录 → 补充 purchase_price
POST /api/youpin/import/sell   拉取出售记录    → 标记 status=sold
POST /api/youpin/import/all    全量导入（stock + lease + buy + sell）

GET  /api/youpin/preview/buy   预览购买记录（不写库，用于核对）
GET  /api/youpin/preview/sell  预览出售记录（不写库）
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.services import youpin as youpin_svc

router = APIRouter()


def _check_token():
    if not settings.youpin_token:
        raise HTTPException(status_code=503, detail="YOUPIN_TOKEN 未配置，请先在 .env 中填写")


# ── 预览（只拉不写）────────────────────────────────────────────────────────

@router.get("/preview/buy")
async def preview_buy(page: int = 1):
    """预览悠悠购买记录（第一页），用于确认 API 连通性和字段格式。"""
    _check_token()
    try:
        records = await youpin_svc.fetch_buy_records(page=page, page_size=20)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"page": page, "count": len(records), "data": records}


@router.get("/preview/sell")
async def preview_sell(page: int = 1):
    """预览悠悠出售记录（第一页）。"""
    _check_token()
    try:
        records = await youpin_svc.fetch_sell_records(page=page, page_size=20)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"page": page, "count": len(records), "data": records}


# ── 正式导入 ───────────────────────────────────────────────────────────────

@router.post("/import/stock")
async def import_stock(db: AsyncSession = Depends(get_db)):
    """
    拉取悠悠在库存物品（Steam 7天保护期），写入 inventory_item（status=in_steam）。
    同时写入 purchase_price（来自 assetBuyPrice 字段）。
    """
    _check_token()
    try:
        result = await youpin_svc.import_stock_records(db)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
    return result


@router.post("/import/lease")
async def import_lease(db: AsyncSession = Depends(get_db)):
    """
    拉取悠悠当前全部租出订单，按 commodity_id upsert 到 inventory_item（status=rented_out）。
    这是最主要的持仓数据来源，应首先执行。
    """
    _check_token()
    try:
        result = await youpin_svc.import_lease_records(db)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
    return result


@router.post("/import/buy")
async def import_buy(db: AsyncSession = Depends(get_db)):
    """
    拉取全部悠悠购买记录，按 market_hash_name 匹配持仓物品，
    自动填入 purchase_price / purchase_date（仅补充空缺，不覆盖已有）。
    """
    _check_token()
    try:
        result = await youpin_svc.import_buy_records(db)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
    return result


@router.post("/import/sell")
async def import_sell(db: AsyncSession = Depends(get_db)):
    """
    拉取全部悠悠出售记录，将匹配到的持仓物品标记为 status=sold。
    """
    _check_token()
    try:
        result = await youpin_svc.import_sell_records(db)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
    return result


@router.post("/import/all")
async def import_all(db: AsyncSession = Depends(get_db)):
    """
    全量导入：
      1. stock  → 同步在库存物品（Steam 保护期，~443 件）+ 写入 purchase_price
      2. lease  → 同步当前租出持仓（主力，3000+ 件）
      3. buy    → 补充购买成本价（匹配未录入的）
      4. sell   → 标记已出售物品
    """
    _check_token()
    results = {}
    for name, fn in [
        ("stock", youpin_svc.import_stock_records),
        ("lease", youpin_svc.import_lease_records),
        ("buy", youpin_svc.import_buy_records),
        ("sell", youpin_svc.import_sell_records),
    ]:
        try:
            results[name] = await fn(db)
        except Exception as e:
            results[name] = {"error": str(e)}
    return results
