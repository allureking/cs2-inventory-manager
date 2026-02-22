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
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.services import youpin as youpin_svc

# 转租中记录格式化（复用）
def _fmt_lease_record(rec: dict) -> dict:
    info = rec.get("commodityInfo") or {}
    return {
        "orderId":         rec.get("orderId"),
        "orderStatus":     rec.get("orderStatus"),
        "orderSubStatus":  rec.get("orderSubStatus"),
        "orderStatusDesc": rec.get("orderStatusDesc"),
        "isSublet":        rec.get("orderSubStatus") == 1064,
        "onShelfFlag":     rec.get("onShelfFlag"),
        "leaseDaysDesc":   rec.get("leaseDaysDesc"),
        "leaseAmountDesc": rec.get("leaseAmountDesc"),
        "leaseExpireTime": rec.get("leaseExpireTime"),
        "hasRenewal":      rec.get("hasRenewal"),
        "commodityId":     info.get("commodityId"),
        "name":            info.get("name"),
        "hashName":        info.get("commodityHashName"),
        "abrade":          info.get("abrade"),
        "imgUrl":          info.get("imgUrl") or info.get("iconUrl"),
        "shortLeasePrice": info.get("shortLeasePrice"),
        "longLeasePrice":  info.get("longLeasePrice"),
    }

router = APIRouter()


def _require_token():
    if not youpin_svc.get_active_token():
        raise HTTPException(status_code=503, detail="Token 未配置，请先通过手机号登录或在 .env 中填写 YOUPIN_TOKEN")


# ── 认证 ──────────────────────────────────────────────────────────────────

@router.get("/token/status")
async def token_status():
    """验证当前悠悠 Token 是否有效，返回用户信息"""
    return await youpin_svc.check_token_status()


@router.get("/auth/state")
async def auth_state():
    """获取当前登录状态（昵称、Token 来源等）"""
    return youpin_svc.get_login_state()


@router.post("/auth/send-sms")
async def auth_send_sms(body: dict):
    """发送短信验证码"""
    phone = body.get("phone", "").strip()
    if not phone:
        raise HTTPException(status_code=400, detail="请输入手机号")
    try:
        return await youpin_svc.send_sms_code(phone)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/auth/login")
async def auth_login(body: dict):
    """短信验证码登录，获取 App 端 Token"""
    phone = body.get("phone", "").strip()
    code = body.get("code", "").strip()
    session_id = body.get("session_id", "").strip()
    if not phone or not code or not session_id:
        raise HTTPException(status_code=400, detail="缺少必填字段")
    try:
        return await youpin_svc.sms_login(phone, code, session_id)
    except youpin_svc.TokenExpiredError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/auth/apply-token")
async def auth_apply_token(body: dict):
    """手动设置 Token（从浏览器/App 获取后粘贴）"""
    token = body.get("token", "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="请输入 Token")
    # 设置运行时 token
    youpin_svc._runtime_token = token
    # 验证是否有效
    try:
        info = await youpin_svc.check_token_status()
        youpin_svc._runtime_nickname = info.get("nickname")
        return {"ok": True, "nickname": info.get("nickname"), "token_source": "manual"}
    except Exception as e:
        youpin_svc._runtime_token = None
        raise HTTPException(status_code=401, detail=f"Token 无效: {e}")


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


@router.get("/market/price-info")
async def market_price_info(
    template_id: int = Query(...),
    abrade: Optional[float] = Query(None),
):
    """
    查询指定模板的市场挂单价 + 出租价 + 建议定价（供货架改价/上架参考）。
    返回前10条卖价、前10条租价、计算好的建议出售价和出租价。
    """
    _require_token()
    try:
        sell_list, lease_list = await asyncio.gather(
            youpin_svc.fetch_market_sell_price(template_id, abrade),
            youpin_svc.fetch_market_lease_price(template_id),
        )
    except youpin_svc.TokenExpiredError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))

    from app.services.youpin_listing import calc_sell_price, calc_lease_price
    suggested_sell = calc_sell_price(sell_list)
    suggested_lease = calc_lease_price(lease_list, sell_price=suggested_sell or 0.0)

    def _extract_sell(item: dict) -> dict:
        return {
            "price": item.get("price") or item.get("Price") or item.get("sellPrice"),
            "abrade": item.get("abrade"),
        }

    def _extract_lease(item: dict) -> dict:
        return {
            "leaseUnit": item.get("leaseUnitPrice") or item.get("LeaseUnitPrice"),
            "longLeaseUnit": item.get("longLeaseUnitPrice") or item.get("LongLeaseUnitPrice"),
            "deposit": item.get("leaseDeposit") or item.get("LeaseDeposit"),
        }

    return {
        "template_id": template_id,
        "sell_list": [_extract_sell(i) for i in sell_list[:10]],
        "lease_list": [_extract_lease(i) for i in lease_list[:10]],
        "suggested_sell": suggested_sell,
        "suggested_lease": suggested_lease,
    }


# ── 租出订单实时列表 ─────────────────────────────────────────────────────────

@router.get("/lease/live-list")
async def lease_live_list(
    page: int = 1,
    page_size: int = 50,
):
    """实时拉取当前租出订单列表（直接从悠悠API，不走DB）"""
    _require_token()
    try:
        records, total_count, stats_desc = await youpin_svc.fetch_lease_records(
            page=page, page_size=page_size
        )
    except youpin_svc.TokenExpiredError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))

    return {
        "items": [_fmt_lease_record(r) for r in records],
        "total": total_count,
        "stats": stats_desc,
        "page": page,
        "page_size": page_size,
    }


@router.get("/lease/sublet-list")
async def lease_sublet_list(
    page: int = 1,
    page_size: int = 50,
):
    """
    获取当前 0CD 转租货架列表（zeroCDLease 端点，精确数据）。
    """
    _require_token()
    try:
        result = await youpin_svc.fetch_zero_cd_shelf(page=page, page_size=page_size)
    except youpin_svc.TokenExpiredError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))

    from app.services.youpin_listing import _normalize_shelf_item
    data = youpin_svc._data(result)
    if isinstance(data, dict):
        raw = (data.get("commodityInfoList") or data.get("list") or [])
        stats = data.get("statisticalData") or {}
        total = stats.get("quantity") or data.get("totalCount") or len(raw)
        items = [_normalize_shelf_item(i) for i in raw]
    else:
        items, total = [], 0

    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.post("/lease/enable-zero-cd")
async def enable_zero_cd_api(body: dict):
    """批量开启 0CD 转租"""
    _require_token()
    order_ids = body.get("order_ids", [])
    if not order_ids:
        raise HTTPException(status_code=400, detail="至少选择一个订单")
    try:
        return await youpin_svc.enable_zero_cd(order_ids)
    except youpin_svc.TokenExpiredError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/lease/disable-zero-cd")
async def disable_zero_cd_api(body: dict):
    """批量取消 0CD 转租"""
    _require_token()
    order_ids = body.get("order_ids", [])
    if not order_ids:
        raise HTTPException(status_code=400, detail="至少选择一个订单")
    try:
        return await youpin_svc.disable_zero_cd(order_ids)
    except youpin_svc.TokenExpiredError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


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
