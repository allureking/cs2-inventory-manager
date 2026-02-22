"""
Dashboard API — 前端所需数据接口

Endpoints:
  GET  /api/dashboard/overview                    — 投资组合汇总统计（含市值/P&L）
  GET  /api/dashboard/items                        — 分页/过滤/排序的持仓列表（含市价/P&L）
  PATCH /api/dashboard/items/{id}/manual-price     — 设置/清除手动购入价
  POST /api/dashboard/refresh-prices               — 触发后台全量市价刷新
  GET  /api/dashboard/refresh-prices/status        — 查询刷新进度
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select, case, not_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal, get_db
from app.models.db_models import InventoryItem, PriceSnapshot
from app.services import steamdt as price_svc

router = APIRouter()

_ACTIVE = ["in_steam", "rented_out", "in_storage"]

# CS2 物品分类（参考悠悠有品筛选）
_CATEGORY_PATTERNS: dict[str, list[str]] = {
    "knife":    [],   # 特殊处理：★ 开头且非手套
    "glove":    [],   # 特殊处理：★ + 含 Gloves/Wraps
    "pistol":   ["Glock-18", "USP-S", "P250", "CZ75-Auto", "Five-SeveN", "Tec-9",
                 "Desert Eagle", "R8 Revolver", "P2000", "Dual Berettas"],
    "rifle":    ["AK-47", "M4A4", "M4A1-S", "FAMAS", "Galil AR", "AUG", "SG 553"],
    "sniper":   ["AWP", "SSG 08", "SCAR-20", "G3SG1"],
    "smg":      ["MP9", "MP5-SD", "MAC-10", "PP-Bizon", "UMP-45", "P90", "MP7"],
    "shotgun":  ["XM1014", "MAG-7", "Nova", "Sawed-Off"],
    "mg":       ["M249", "Negev"],
    "sticker":  ["Sticker |"],
    "patch":    ["Patch |"],
    "graffiti": ["Sealed Graffiti |"],
    "charm":    ["Charm |"],
    "agent":    ["Master Agent", "Distinguished Agent", "Exceptional Agent", "Superior Agent",
                 "Vypa", "Chem-Haz", "Ground Rebel", "Elite Crew", "KSK", "SAS", "SEAL",
                 "SWAT", "FBI", "GIGN", "NSWC"],
    "musickit": ["Music Kit |", "StatTrak™ Music Kit |"],
    "case":     [" Case", "Capsule", "Package"],
    "key":      ["Case Key", "Capsule Key", "eSports Key", "Operation"],
    "tool":     ["Name Tag", "Storage Unit", "Sticker |"],
}

# 磨损等级（从 market_hash_name 末尾括号提取）
_WEAR_PATTERNS = {
    "fn": "(Factory New)",
    "mw": "(Minimal Wear)",
    "ft": "(Field-Tested)",
    "ww": "(Well-Worn)",
    "bs": "(Battle-Scarred)",
}


def _category_filter(category: str):
    """返回对应分类的 SQLAlchemy WHERE 条件"""
    # 特殊品质筛选
    if category == "stattrak":
        return InventoryItem.market_hash_name.like("StatTrak™%")
    if category == "souvenir":
        return InventoryItem.market_hash_name.like("Souvenir%")

    # 磨损等级筛选
    if category in _WEAR_PATTERNS:
        return InventoryItem.market_hash_name.like(f"%{_WEAR_PATTERNS[category]}")

    # 刀具和手套
    if category == "knife":
        return and_(
            InventoryItem.market_hash_name.like("★%"),
            ~InventoryItem.market_hash_name.ilike("%Gloves%"),
            ~InventoryItem.market_hash_name.ilike("%Wraps%"),
        )
    if category == "glove":
        return and_(
            InventoryItem.market_hash_name.like("★%"),
            or_(
                InventoryItem.market_hash_name.ilike("%Gloves%"),
                InventoryItem.market_hash_name.ilike("%Wraps%"),
            ),
        )

    patterns = _CATEGORY_PATTERNS.get(category, [])
    if not patterns:
        return None
    return or_(*[InventoryItem.market_hash_name.ilike(f"{p}%") for p in patterns])

# ── 价格刷新后台任务状态（单进程内共享）────────────────────────────────
_refresh_state: dict = {
    "status": "idle",      # idle | running | done | error
    "progress": 0,         # 0-100
    "total_batches": 0,
    "done_batches": 0,
    "started_at": None,
    "finished_at": None,
    "error": None,
}


# ── 工具函数：从缓存获取最新市价 ────────────────────────────────────────
async def _get_latest_prices(
    market_hash_names: list[str], db: AsyncSession
) -> dict[str, Optional[float]]:
    """
    返回 {market_hash_name: min_sell_price}，基于 price_snapshot 中最新一批快照。
    没有缓存的饰品不出现在返回字典中。
    """
    if not market_hash_names:
        return {}

    # 子查询：每个饰品的最新 snapshot_minute
    latest_subq = (
        select(
            PriceSnapshot.market_hash_name,
            func.max(PriceSnapshot.snapshot_minute).label("latest_minute"),
        )
        .where(PriceSnapshot.market_hash_name.in_(market_hash_names))
        .group_by(PriceSnapshot.market_hash_name)
        .subquery()
    )

    # 在最新快照中取最低卖价（跨平台）
    rows = (
        await db.execute(
            select(
                PriceSnapshot.market_hash_name,
                func.min(PriceSnapshot.sell_price).label("current_price"),
            )
            .join(
                latest_subq,
                and_(
                    PriceSnapshot.market_hash_name == latest_subq.c.market_hash_name,
                    PriceSnapshot.snapshot_minute == latest_subq.c.latest_minute,
                ),
            )
            .where(PriceSnapshot.sell_price.isnot(None), PriceSnapshot.sell_price > 0)
            .group_by(PriceSnapshot.market_hash_name)
        )
    ).all()

    return {row[0]: row[1] for row in rows}


# ── 后台价格刷新任务 ────────────────────────────────────────────────────
async def _run_price_refresh() -> None:
    """
    全量刷新活跃持仓的市价：
    1. 查询所有活跃物品的唯一 market_hash_name
    2. 每批 100 个调用 SteamDT batch API（速率限制 1次/分钟）
    3. 批次间 sleep 62 秒避免触发限速
    """
    global _refresh_state
    _refresh_state.update(status="running", progress=0, done_batches=0, error=None,
                          started_at=datetime.now(timezone.utc).isoformat())

    try:
        async with AsyncSessionLocal() as db:
            rows = (
                await db.execute(
                    select(func.distinct(InventoryItem.market_hash_name))
                    .where(InventoryItem.status.in_(_ACTIVE))
                )
            ).scalars().all()

        all_names = list(rows)
        chunk_size = 100
        chunks = [all_names[i : i + chunk_size] for i in range(0, len(all_names), chunk_size)]

        _refresh_state["total_batches"] = len(chunks)

        for idx, chunk in enumerate(chunks):
            # 非第一批次先等待（速率限制）
            if idx > 0:
                for _ in range(62):
                    await asyncio.sleep(1)
                    # 每秒更新一次进度（等待期间线性内插）
                    wait_pct = idx / len(chunks) * 100
                    ahead_pct = (idx + 1) / len(chunks) * 100
                    _refresh_state["progress"] = int(
                        wait_pct + (ahead_pct - wait_pct) * (_ / 62)
                    )

            async with AsyncSessionLocal() as db:
                await price_svc.fetch_batch_prices(chunk, db)

            _refresh_state["done_batches"] = idx + 1
            _refresh_state["progress"] = int((idx + 1) / len(chunks) * 100)

        _refresh_state.update(
            status="done",
            progress=100,
            finished_at=datetime.now(timezone.utc).isoformat(),
        )

    except Exception as exc:
        _refresh_state.update(
            status="error",
            error=str(exc),
            finished_at=datetime.now(timezone.utc).isoformat(),
        )


# ════════════════════════════════════════════════════════════════════
#  Endpoints
# ════════════════════════════════════════════════════════════════════

@router.post("/refresh-prices")
async def trigger_refresh_prices():
    """
    触发市价全量刷新（优先使用悠悠官方市价 API，fallback SteamDT）。
    前端请改用 /api/youpin/market/refresh（直接调悠悠 API，数据更准确）。
    此接口保留兼容性，内部转发至悠悠市价刷新。
    """
    from app.services.youpin import market_refresh_state, bulk_refresh_market_prices
    if market_refresh_state["status"] == "running":
        return {"started": False, "message": "已有刷新任务正在运行", "state": market_refresh_state}
    asyncio.create_task(bulk_refresh_market_prices(None))
    return {"started": True, "message": "价格刷新已启动（悠悠有品官方价格）", "state": market_refresh_state}


@router.get("/refresh-prices/status")
async def get_refresh_status():
    """查询当前刷新进度（供前端轮询）。"""
    from app.services.youpin import market_refresh_state
    return market_refresh_state


@router.get("/overview")
async def get_overview(db: AsyncSession = Depends(get_db)):
    """投资组合汇总统计：各状态数量、总成本、市值、P&L、定价覆盖率。"""

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

    # --- 活跃持仓中已定价数量 ---
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

    # --- 市值计算：按 (market_hash_name, status) 聚合，乘以最新缓存价格 ---
    name_status_rows = (
        await db.execute(
            select(
                InventoryItem.market_hash_name,
                InventoryItem.status,
                func.count(InventoryItem.id).label("cnt"),
            )
            .where(InventoryItem.status.in_(_ACTIVE))
            .group_by(InventoryItem.market_hash_name, InventoryItem.status)
        )
    ).all()

    # 汇总
    all_active_names = list({r[0] for r in name_status_rows})
    name_to_count: dict = {}
    for n, s, c in name_status_rows:
        name_to_count[n] = name_to_count.get(n, 0) + c

    price_map = await _get_latest_prices(all_active_names, db)

    market_value = 0.0
    market_value_steam = 0.0
    market_value_rented = 0.0
    market_priced_count = 0
    for n, s, c in name_status_rows:
        mp = price_map.get(n)
        if mp is not None:
            val = mp * c
            market_value += val
            market_priced_count += c
            if s == "in_steam":
                market_value_steam += val
            elif s == "rented_out":
                market_value_rented += val

    # P&L：仅对同时有【购入价】AND【市价】的物品精确逐件对比
    # 拉取活跃物品中有购入价的每一件
    item_cost_rows = (
        await db.execute(
            select(
                InventoryItem.market_hash_name,
                func.coalesce(
                    InventoryItem.purchase_price_manual,
                    InventoryItem.purchase_price,
                ).label("cost"),
            )
            .where(
                InventoryItem.status.in_(_ACTIVE),
                or_(
                    InventoryItem.purchase_price.isnot(None),
                    InventoryItem.purchase_price_manual.isnot(None),
                ),
            )
        )
    ).all()

    pnl_market_sum = 0.0
    pnl_cost_sum = 0.0
    pnl_count = 0
    for row in item_cost_rows:
        mp = price_map.get(row[0])
        if mp is not None and row[1] is not None:
            pnl_market_sum += mp
            pnl_cost_sum += float(row[1])
            pnl_count += 1

    if pnl_count > 0 and pnl_cost_sum > 0:
        pnl = round(pnl_market_sum - pnl_cost_sum, 2)
        pnl_pct = round((pnl_market_sum - pnl_cost_sum) / pnl_cost_sum * 100, 2)
    else:
        pnl = None
        pnl_pct = None

    # --- 最新价格快照时间 ---
    latest_snap_minute = (
        await db.execute(
            select(func.max(PriceSnapshot.snapshot_minute))
        )
    ).scalar()

    price_updated_at = None
    if latest_snap_minute:
        try:
            dt = datetime.strptime(latest_snap_minute, "%Y%m%d%H%M")
            price_updated_at = dt.strftime("%Y-%m-%d %H:%M")
        except ValueError:
            pass

    # --- Token 状态（快速检测，不强制等待）---
    from app.services.youpin import market_refresh_state
    price_refresh_status = market_refresh_state["status"]
    price_refresh_progress = market_refresh_state["progress"]

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
        # 市值 & P&L
        "market_value": round(market_value, 2) if market_value else 0,
        "market_value_steam": round(market_value_steam, 2),
        "market_value_rented": round(market_value_rented, 2),
        "market_priced_count": market_priced_count,
        "pnl": round(pnl, 2) if pnl is not None else None,
        "pnl_pct": round(pnl_pct, 2) if pnl_pct is not None else None,
        "pnl_covered_count": pnl_count,   # 同时有购入价+市价的件数
        "price_updated_at": price_updated_at,
        "price_refresh_status": price_refresh_status,
        "price_refresh_progress": price_refresh_progress,
    }


@router.get("/items")
async def list_items(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    search: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    priced_filter: Optional[str] = Query(None),  # "priced" | "unpriced"
    exclude_sold: bool = Query(False),
    category: Optional[str] = Query(None),        # "knife"|"glove"|"pistol"|"rifle"|"sniper"|"smg"|"shotgun"|"mg"|"sticker"|"case"
    sort_by: str = Query("first_seen_at"),
    sort_order: str = Query("desc"),
    db: AsyncSession = Depends(get_db),
):
    """分页/过滤/排序持仓列表（含当前市价和 P&L）。"""

    q = select(InventoryItem)

    if search:
        q = q.where(
            or_(
                InventoryItem.market_hash_name.ilike(f"%{search}%"),
                InventoryItem.name.ilike(f"%{search}%"),
            )
        )

    if status:
        q = q.where(InventoryItem.status == status)
    elif exclude_sold:
        q = q.where(InventoryItem.status != "sold")

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

    if category:
        cat_cond = _category_filter(category)
        if cat_cond is not None:
            q = q.where(cat_cond)

    count_q = select(func.count()).select_from(q.subquery())
    total = (await db.execute(count_q)).scalar() or 0

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

    if sort_by in ("current_price", "pnl"):
        # 按市价/盈亏排序：JOIN price_snapshot 子查询
        latest_sq = (
            select(
                PriceSnapshot.market_hash_name,
                func.max(PriceSnapshot.snapshot_minute).label("lm"),
            )
            .group_by(PriceSnapshot.market_hash_name)
            .subquery()
        )
        price_sq = (
            select(
                PriceSnapshot.market_hash_name.label("mhn"),
                func.min(PriceSnapshot.sell_price).label("cp"),
            )
            .join(
                latest_sq,
                and_(
                    PriceSnapshot.market_hash_name == latest_sq.c.market_hash_name,
                    PriceSnapshot.snapshot_minute == latest_sq.c.lm,
                ),
            )
            .where(PriceSnapshot.sell_price > 0)
            .group_by(PriceSnapshot.market_hash_name)
            .subquery()
        )
        q = q.outerjoin(price_sq, InventoryItem.market_hash_name == price_sq.c.mhn)
        sort_col = price_sq.c.cp if sort_by == "current_price" else (price_sq.c.cp - _effective)
    else:
        sort_col = sortable.get(sort_by, InventoryItem.first_seen_at)

    if sort_order == "asc":
        q = q.order_by(sort_col.asc().nulls_last())
    else:
        q = q.order_by(sort_col.desc().nulls_last())

    q = q.offset((page - 1) * page_size).limit(page_size)
    rows = (await db.execute(q)).scalars().all()

    # 批量获取本页物品的市价
    page_names = list({item.market_hash_name for item in rows})
    price_map = await _get_latest_prices(page_names, db)

    def to_dict(item: InventoryItem) -> dict:
        effective = (
            item.purchase_price_manual
            if item.purchase_price_manual is not None
            else item.purchase_price
        )
        current_price = price_map.get(item.market_hash_name)
        pnl = None
        pnl_pct = None
        if current_price is not None and effective is not None:
            pnl = round(current_price - effective, 2)
            pnl_pct = round(pnl / effective * 100, 1) if effective else None

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
            "current_price": round(current_price, 2) if current_price is not None else None,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
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
