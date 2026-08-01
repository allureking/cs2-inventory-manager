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
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.db_models import (InventoryItem, LeaseIncomeDaily,
                                  ListingSnapshot, ListingSnapshotItem)
from app.services import price_guard
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

# 入参约束（v0.13.3）：这一组端点会把价格**直接推到悠悠线上**，是全应用后果最重的
# 输入。此前全部是裸 float/int，0、负数、NaN、1e308 都能穿过去。上限取得很宽松，
# 只用于拦截"单位搞错 / 前端算歪 / 手滑多打几个零"这类明显错误，不干预正常定价。
_MAX_PRICE = 2_000_000.0      # 元；CS2 最贵的刀/手套也远低于此
_MAX_RENT = 100_000.0         # 元/天


class SmartListRequest(BaseModel):
    asset_id: str = Field(min_length=1)
    template_id: int = Field(gt=0)
    abrade: Optional[float] = Field(default=None, ge=0, le=1)
    mode: Literal["sell", "lease", "both"] = "sell"
    buy_price: float = Field(default=0.0, ge=0, le=_MAX_PRICE)
    take_profit_ratio: float = Field(default=0.0, ge=-0.9, le=10)
    fix_lease_ratio: float = Field(default=0.0, ge=-0.9, le=10)
    use_undercut: bool = True
    member_level: int = Field(default=3, ge=1, le=3)  # → max_days 8/30/90


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
    commodity_id: int = Field(gt=0)
    template_id: int = Field(gt=0)
    abrade: Optional[float] = Field(default=None, ge=0, le=1)
    is_can_lease: bool = False


class BatchSmartRepriceRequest(BaseModel):
    # max_length 与下面那句 len>30 的 400 双保险：前者挡住超大 body 被解析，
    # 后者保留原有中文报错
    items: list[BatchSmartRepriceItem] = Field(max_length=30)
    use_undercut: bool = True
    take_profit_ratio: float = Field(default=0.0, ge=-0.9, le=10)


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


# ── 手滑低价防线（v0.13.4）──────────────────────────────────────────────────
#
# 人工输入的价格若明显低于该件当前市价，回 409 + 结构化 detail，由前端弹二次确认、
# 用户确认后带 confirm_below_market=true 重发。设计取舍（为何是确认而非拦截、为何
# 查不到基准时放行）见 app/services/price_guard.py 顶部。
#
# 这层必须在服务端：前端弹窗只管体验，带 X-API-Key 的脚本会直接绕过它。


async def _guard_low_price(
    *,
    confirmed: bool,
    sell_price: Optional[float] = None,
    lease_unit: Optional[float] = None,
    long_lease_unit: Optional[float] = None,
    deposit: Optional[float] = None,
    market_hash_name: Optional[str] = None,
    template_id: Optional[int] = None,
    commodity_id: Optional[int] = None,
    asset_id: Optional[str] = None,
) -> None:
    """触发即 raise 409（列全所有越线字段）；确认过、或查不到基准、或价格不低 → 通过。

    标识符能自己查就自己查：调用方漏传 market_hash_name / template_id 时，防线绝不能
    静默变成空转——那比没有防线更糟（用户以为有保护）。
    """
    if confirmed:
        return

    violations: list[dict] = []

    # ── 售价侧 ──
    if sell_price is not None:
        name = market_hash_name or await _resolve_hash_name(
            commodity_id=commodity_id, asset_id=asset_id)
        basis = await _sell_basis_for(name)
        if price_guard.is_below_market(sell_price, basis):
            violations.append(price_guard.violation("sell_price", sell_price, basis))

    # ── 出租侧：三个字段挨在一起、同一次提交，一次 fetch 全查 ──
    lease_inputs = {"lease_unit": lease_unit, "long_lease_unit": long_lease_unit,
                    "deposit": deposit}
    if any(v is not None for v in lease_inputs.values()):
        tid = template_id or await _resolve_template_id(
            commodity_id=commodity_id, asset_id=asset_id,
            market_hash_name=market_hash_name)
        bases = await price_guard.lease_bases(tid)
        for key, val in lease_inputs.items():
            if val is None:
                continue
            b = getattr(bases, key)
            if price_guard.is_below_market(val, b):
                violations.append(price_guard.violation(key, val, b))

    if violations:
        raise HTTPException(status_code=409,
                            detail=price_guard.below_market_detail(violations))


async def _sell_basis_for(market_hash_name: Optional[str]):
    if not market_hash_name:
        return price_guard.NO_BASIS
    async with AsyncSessionLocal() as db:
        return await price_guard.sell_basis(db, market_hash_name)


async def _resolve_hash_name(
    *, commodity_id: Optional[int] = None, asset_id: Optional[str] = None
) -> Optional[str]:
    """commodity_id / asset_id → market_hash_name。查不到返回 None（放行）。

    逐级兜底：inventory_item 只有租赁导入会写 youpin_commodity_id，出售货架上的件
    多半是 NULL，所以还要落到货架快照与租赁实绩表。
    """
    async with AsyncSessionLocal() as db:
        if commodity_id:
            name = (await db.execute(
                select(InventoryItem.market_hash_name)
                .where(InventoryItem.youpin_commodity_id == commodity_id)
                .limit(1)
            )).scalars().first()
            if name:
                return name
            name = (await db.execute(
                select(ListingSnapshotItem.commodity_hash_name)
                .where(ListingSnapshotItem.commodity_id == commodity_id)
                .order_by(ListingSnapshotItem.id.desc())
                .limit(1)
            )).scalars().first()
            if name:
                return name
            name = (await db.execute(
                select(LeaseIncomeDaily.market_hash_name)
                .where(LeaseIncomeDaily.commodity_id == commodity_id)
                .order_by(LeaseIncomeDaily.date.desc())
                .limit(1)
            )).scalars().first()
            if name:
                return name
        if asset_id:
            # asset_id 无 unique 约束（租赁导入甚至往里写 order_id）→ 只取一行
            return (await db.execute(
                select(InventoryItem.market_hash_name)
                .where(InventoryItem.asset_id == str(asset_id))
                .limit(1)
            )).scalars().first()
    return None


async def _resolve_template_id(
    *, commodity_id: Optional[int] = None, asset_id: Optional[str] = None,
    market_hash_name: Optional[str] = None,
) -> Optional[int]:
    """→ youpin_template_id。template_id 是"按名字"的属性，所以名字也能查到。"""
    async with AsyncSessionLocal() as db:
        if commodity_id:
            tid = (await db.execute(
                select(ListingSnapshotItem.template_id)
                .where(ListingSnapshotItem.commodity_id == commodity_id,
                       ListingSnapshotItem.template_id.isnot(None))
                .order_by(ListingSnapshotItem.id.desc()).limit(1)
            )).scalars().first()
            if tid:
                return tid
            tid = (await db.execute(
                select(InventoryItem.youpin_template_id)
                .where(InventoryItem.youpin_commodity_id == commodity_id,
                       InventoryItem.youpin_template_id.isnot(None)).limit(1)
            )).scalars().first()
            if tid:
                return tid
        if asset_id:
            tid = (await db.execute(
                select(InventoryItem.youpin_template_id)
                .where(InventoryItem.asset_id == str(asset_id),
                       InventoryItem.youpin_template_id.isnot(None)).limit(1)
            )).scalars().first()
            if tid:
                return tid
        if market_hash_name:
            return (await db.execute(
                select(InventoryItem.youpin_template_id)
                .where(InventoryItem.market_hash_name == market_hash_name,
                       InventoryItem.youpin_template_id.isnot(None)).limit(1)
            )).scalars().first()
    return None


# ── 手动上架 ────────────────────────────────────────────────────────────────

class SellRequest(BaseModel):
    asset_id: str = Field(min_length=1)
    price: float = Field(gt=0, le=_MAX_PRICE)
    confirm_below_market: bool = False


class LeaseRequest(BaseModel):
    asset_id: str = Field(min_length=1)
    lease_unit: float = Field(gt=0, le=_MAX_RENT)
    long_lease_unit: float = Field(gt=0, le=_MAX_RENT)
    deposit: float = Field(ge=0, le=_MAX_PRICE)
    max_days: int = Field(default=30, ge=1, le=90)
    template_id: Optional[int] = Field(default=None, gt=0)  # 有则启用租金侧防线
    confirm_below_market: bool = False


class BothRequest(BaseModel):
    asset_id: str = Field(min_length=1)
    sell_price: float = Field(gt=0, le=_MAX_PRICE)
    lease_unit: float = Field(gt=0, le=_MAX_RENT)
    long_lease_unit: float = Field(gt=0, le=_MAX_RENT)
    deposit: float = Field(ge=0, le=_MAX_PRICE)
    max_days: int = Field(default=30, ge=1, le=90)
    template_id: Optional[int] = Field(default=None, gt=0)  # 有则启用租金侧防线
    confirm_below_market: bool = False


@router.post("/sell")
async def list_sell_api(body: SellRequest):
    """手动出售上架"""
    await _guard_low_price(confirmed=body.confirm_below_market,
                           sell_price=body.price, asset_id=body.asset_id)
    try:
        return await list_for_sell(body.asset_id, body.price)
    except Exception as e:
        _handle_token_error(e)


@router.post("/lease")
async def list_lease_api(body: LeaseRequest):
    """手动出租上架"""
    await _guard_low_price(confirmed=body.confirm_below_market,
                           lease_unit=body.lease_unit,
                           long_lease_unit=body.long_lease_unit, deposit=body.deposit,
                           template_id=body.template_id, asset_id=body.asset_id)
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
    await _guard_low_price(confirmed=body.confirm_below_market,
                           sell_price=body.sell_price, lease_unit=body.lease_unit,
                           long_lease_unit=body.long_lease_unit, deposit=body.deposit,
                           asset_id=body.asset_id, template_id=body.template_id)
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
    commodity_id: int = Field(gt=0)
    sell_price: Optional[float] = Field(default=None, gt=0, le=_MAX_PRICE)
    lease_unit: Optional[float] = Field(default=None, gt=0, le=_MAX_RENT)
    long_lease_unit: Optional[float] = Field(default=None, gt=0, le=_MAX_RENT)
    deposit: Optional[float] = Field(default=None, ge=0, le=_MAX_PRICE)
    is_can_sold: bool = True
    is_can_lease: bool = False
    # 低价防线用：拿基准需要名字（售价）/ 模板（租金）。都是货架条目上现成有的字段，
    # 缺失时对应那一侧的防线自动降级为放行。
    market_hash_name: Optional[str] = None
    template_id: Optional[int] = Field(default=None, gt=0)
    confirm_below_market: bool = False


@router.put("/reprice")
async def reprice_api(body: RepriceRequest):
    """修改已上架物品价格（使用 CommodityId）"""
    await _guard_low_price(
        confirmed=body.confirm_below_market,
        sell_price=body.sell_price,
        lease_unit=body.lease_unit,
        long_lease_unit=body.long_lease_unit,
        deposit=body.deposit,
        market_hash_name=body.market_hash_name,
        template_id=body.template_id,
        commodity_id=body.commodity_id,
    )
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

        total_value = sum(float(i.get("price") or 0) for i in all_items if i.get("price") not in (None, ""))
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

            def _float(v):
                if v is None or v == "":
                    return None
                try:
                    return float(v)
                except (ValueError, TypeError):
                    return None

            def _int(v):
                if v is None or v == "":
                    return None
                try:
                    return int(v)
                except (ValueError, TypeError):
                    return None

            for item in all_items:
                asset_id = str(item.get("steamAssetId") or "")
                sess.add(ListingSnapshotItem(
                    snapshot_id=snapshot.id,
                    commodity_hash_name=item.get("commodityHashName") or "",
                    name=item.get("name") or "",
                    img_url=item.get("imgUrl"),
                    abrade=_float(item.get("abrade")),
                    template_id=_int(item.get("templateId")),
                    commodity_id=_int(item.get("commodityId")),
                    steam_asset_id=asset_id or None,
                    sell_price=_float(item.get("price")),
                    lease_unit_price=_float(item.get("leaseUnitPrice")),
                    long_lease_price=_float(item.get("longLeasePrice")),
                    lease_deposit=_float(item.get("leaseDeposit")),
                    lease_max_days=_int(item.get("leaseMaxDays")),
                    open_sublet=item.get("openSublet") if item.get("openSublet") not in (None, "") else None,
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
