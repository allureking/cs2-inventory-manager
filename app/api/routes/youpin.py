"""
悠悠有品 API 路由

── 数据导入 ──
POST /api/youpin/import/stock     → 在库存（保护期）→ inventory_item(in_steam)
POST /api/youpin/import/lease     → 当前租出订单    → inventory_item(rented_out)
POST /api/youpin/import/buy       → 历史购买记录    → 补充 purchase_price
POST /api/youpin/import/sell      → 出售记录        → 标记 status=sold
POST /api/youpin/import/all       → 全量导入

── 模板ID & 市价 ──
POST /api/youpin/sync/template-ids → 从悠悠完整库存同步 youpin_template_id
POST /api/youpin/market/refresh    → 触发后台全量悠悠市价刷新
GET  /api/youpin/market/status     → 查询刷新进度

── Token 管理 ──
GET  /api/youpin/token/status      → 验证 Token 是否有效

── 调试预览 ──
GET  /api/youpin/preview/buy       → 预览购买记录（不写库）
GET  /api/youpin/preview/sell      → 预览出售记录（不写库）
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.services import youpin as youpin_svc

router = APIRouter()


def _require_token():
    if not settings.youpin_token:
        raise HTTPException(status_code=503, detail="YOUPIN_TOKEN 未配置，请先在 .env 中填写")


# ── Token 状态 ──────────────────────────────────────────────────────────────

@router.get("/token/status")
async def token_status():
    """验证当前悠悠 Token 是否有效，返回用户信息"""
    return await youpin_svc.check_token_status()


# ── 模板ID同步 ──────────────────────────────────────────────────────────────

@router.post("/sync/template-ids")
async def sync_template_ids(db: AsyncSession = Depends(get_db)):
    """
    从悠悠完整库存（GetUserInventoryDataListV3）同步 youpin_template_id。
    同步后可使用悠悠市场价格接口刷新市价（替代 SteamDT）。
    """
    _require_token()
    try:
        result = await youpin_svc.sync_template_ids(db)
    except youpin_svc.TokenExpiredError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
    return result


# ── 市价刷新 ────────────────────────────────────────────────────────────────

@router.post("/market/refresh")
async def refresh_market_prices():
    """
    触发后台全量悠悠市价刷新（异步，约 2-5 分钟）。
    需要先运行 sync/template-ids 获取 templateId。
    """
    _require_token()
    state = youpin_svc.market_refresh_state
    if state["status"] == "running":
        return {"started": False, "message": "已有刷新任务正在运行", "state": state}

    asyncio.create_task(youpin_svc.bulk_refresh_market_prices(None))
    return {"started": True, "message": "市价刷新已启动（使用悠悠有品官方价格）", "state": state}


@router.get("/market/status")
async def market_refresh_status():
    """查询市价刷新进度（供前端轮询）"""
    return youpin_svc.market_refresh_state


# ── 数据导入 ────────────────────────────────────────────────────────────────

@router.get("/preview/buy")
async def preview_buy(page: int = 1):
    _require_token()
    try:
        records = await youpin_svc.fetch_buy_records(page=page, page_size=20)
    except youpin_svc.TokenExpiredError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"page": page, "count": len(records), "data": records}


@router.get("/preview/sell")
async def preview_sell(page: int = 1):
    _require_token()
    try:
        records = await youpin_svc.fetch_sell_records(page=page, page_size=20)
    except youpin_svc.TokenExpiredError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"page": page, "count": len(records), "data": records}


@router.post("/import/stock")
async def import_stock(db: AsyncSession = Depends(get_db)):
    _require_token()
    try:
        return await youpin_svc.import_stock_records(db)
    except youpin_svc.TokenExpiredError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/import/lease")
async def import_lease(db: AsyncSession = Depends(get_db)):
    _require_token()
    try:
        return await youpin_svc.import_lease_records(db)
    except youpin_svc.TokenExpiredError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/import/buy")
async def import_buy(db: AsyncSession = Depends(get_db)):
    _require_token()
    try:
        return await youpin_svc.import_buy_records(db)
    except youpin_svc.TokenExpiredError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/import/sell")
async def import_sell(db: AsyncSession = Depends(get_db)):
    _require_token()
    try:
        return await youpin_svc.import_sell_records(db)
    except youpin_svc.TokenExpiredError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/import/all")
async def import_all(db: AsyncSession = Depends(get_db)):
    """全量导入：stock → lease → buy → sell"""
    _require_token()
    results = {}
    for name, fn in [
        ("stock", youpin_svc.import_stock_records),
        ("lease", youpin_svc.import_lease_records),
        ("buy",   youpin_svc.import_buy_records),
        ("sell",  youpin_svc.import_sell_records),
    ]:
        try:
            results[name] = await fn(db)
        except youpin_svc.TokenExpiredError as e:
            results[name] = {"error": str(e), "token_expired": True}
            break  # Token 过期后续全部跳过
        except Exception as e:
            results[name] = {"error": str(e)}
    return results
