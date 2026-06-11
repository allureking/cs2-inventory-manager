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
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select, case, not_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal, get_db
from app.models.db_models import InventoryItem, PriceSnapshot
from app.core.constants import ACTIVE_STATUSES
from app.services import steamdt as price_svc
from app.services.pricing import get_latest_prices as _get_latest_prices

router = APIRouter()

# 悠悠 API 估值缓存（避免 overview 每次请求都调外部 API）
# v0.12.0 stale-while-revalidate：过期时立即返回旧值并后台刷新，请求永不阻塞在外部 API 上
# （此前缓存未命中会同步等悠悠 1-3s+，即「偶尔刷新很慢」的根因）。
_rented_value_cache: dict = {"value": 0.0, "ts": 0.0, "refreshing": False}
_steam_value_cache: dict = {"value": 0.0, "ts": 0.0, "refreshing": False}
_CACHE_TTL = 300  # 5 分钟


async def _fetch_rented_value() -> float:
    """实际拉取悠悠租赁估值（外部 API）。失败抛异常由调用方处理。"""
    from app.services.youpin import fetch_lease_records
    from app.services.tracker import _parse_stats_desc

    _, _, stats_desc = await fetch_lease_records(page=1, page_size=1)
    return _parse_stats_desc(stats_desc)["value"]


async def _fetch_steam_value() -> float:
    """实际拉取悠悠库存估值（外部 API）。"""
    from app.core.utils import parse_money
    from app.services.youpin import fetch_stock_records

    _, _, valuation = await fetch_stock_records(page=1, page_size=1)
    return parse_money(valuation)


async def _refresh_now(cache: dict, fetcher) -> None:
    """实际刷新一个估值缓存(可直接 await,便于测试与复用)。
    成功后失效 overview 缓存,让下一个请求用上新估值;失败保留旧值。"""
    try:
        val = await fetcher()
        if val > 0:
            cache["value"] = val
            cache["ts"] = time.monotonic()
            invalidate_overview_cache()
    except Exception:
        pass  # 外部失败保留旧值,下次再试
    finally:
        cache["refreshing"] = False


def _kick_refresh(cache: dict, fetcher) -> None:
    """后台刷新缓存（防并发：同一缓存同时只有一个刷新任务）。"""
    if cache["refreshing"]:
        return
    from app.services.youpin import get_active_token
    if not get_active_token():
        return
    cache["refreshing"] = True
    asyncio.create_task(_refresh_now(cache, fetcher))


async def _get_cached_rented_value() -> float:
    """租赁估值（SWR）：新鲜→直接返回；过期→返回旧值+后台刷新；无旧值→返回 0（走 snapshot fallback）。"""
    now = time.monotonic()
    c = _rented_value_cache
    if now - c["ts"] < _CACHE_TTL and c["value"] > 0:
        return c["value"]
    _kick_refresh(c, _fetch_rented_value)
    return c["value"]


async def _get_cached_steam_value() -> float:
    """库存估值（SWR），解析用 parse_money（修复：此前未剥 ¥ 符号导致解析失败吞错）。"""
    now = time.monotonic()
    c = _steam_value_cache
    if now - c["ts"] < _CACHE_TTL and c["value"] > 0:
        return c["value"]
    _kick_refresh(c, _fetch_steam_value)
    return c["value"]

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



# _get_latest_prices 已提取到 app/services/pricing.py，通过 import 引入


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
                    .where(InventoryItem.status.in_(ACTIVE_STATUSES))
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


_overview_cache: dict = {"data": None, "ts": 0.0}
_OVERVIEW_TTL = 4 * 3600  # 4 hours — price data only changes once/day


def invalidate_overview_cache() -> None:
    """Called after daily price collection / portfolio snapshot to force refresh on next request."""
    _overview_cache["ts"] = 0.0
    _chart_cache["ts"] = 0.0


# chart-data 聚合缓存（全表 group-by ~0.2s/次；价格一天一更,5 分钟新鲜度足够）
_chart_cache: dict = {"data": None, "ts": 0.0}
_CHART_TTL = 300


@router.get("/overview")
async def get_overview(db: AsyncSession = Depends(get_db)):
    """投资组合汇总统计：各状态数量、总成本、市值、P&L、定价覆盖率。"""
    now = time.monotonic()
    if _overview_cache["data"] and now - _overview_cache["ts"] < _OVERVIEW_TTL:
        return _overview_cache["data"]

    cost_expr = func.coalesce(InventoryItem.purchase_price_manual, InventoryItem.purchase_price)
    is_active = InventoryItem.status.in_(ACTIVE_STATUSES)
    has_price = or_(InventoryItem.purchase_price.isnot(None), InventoryItem.purchase_price_manual.isnot(None))

    combined_q = select(
        InventoryItem.status,
        func.count(InventoryItem.id).label("cnt"),
        func.sum(cost_expr).label("cost"),
        func.sum(case((has_price, 1), else_=0)).label("priced"),
        func.sum(case((InventoryItem.purchase_price_manual.isnot(None), 1), else_=0)).label("manual"),
    ).group_by(InventoryItem.status)

    combined_rows, (market_value_rented, market_value_steam) = await asyncio.gather(
        db.execute(combined_q),
        asyncio.gather(_get_cached_rented_value(), _get_cached_steam_value()),
    )
    combined_rows = combined_rows.all()

    status_counts = {}
    total_cost = 0.0
    rented_cost = 0.0
    steam_cost = 0.0
    priced_count = 0
    manual_count = 0
    for s, cnt, cost, priced, manual in combined_rows:
        status_counts[s] = cnt
        if s in ACTIVE_STATUSES:
            total_cost += cost or 0
            priced_count += priced or 0
            manual_count += manual or 0
        if s == "rented_out":
            rented_cost = cost or 0
        elif s == "in_steam":
            steam_cost = cost or 0
    active_count = sum(status_counts.get(s, 0) for s in ACTIVE_STATUSES)

    # P&L 计算仍需 price_snapshot 的逐件价格
    all_active_names = (await db.execute(
        select(InventoryItem.market_hash_name)
        .where(InventoryItem.status.in_(ACTIVE_STATUSES))
        .distinct()
    )).scalars().all()
    full_price_map = await _get_latest_prices(list(all_active_names), db)

    market_priced_count = active_count  # 悠悠 API 覆盖所有物品

    # 如果悠悠 API 不可用，fallback 到 price_snapshot
    if market_value_steam == 0.0 or market_value_rented == 0.0:
        name_status_rows = (await db.execute(
            select(InventoryItem.market_hash_name, InventoryItem.status, func.count(InventoryItem.id).label("cnt"))
            .where(InventoryItem.status.in_(ACTIVE_STATUSES))
            .group_by(InventoryItem.market_hash_name, InventoryItem.status)
        )).all()
        if market_value_steam == 0.0:
            for n, s, c in name_status_rows:
                if s == "in_steam":
                    mp = full_price_map.get(n)
                    if mp: market_value_steam += mp * c
        if market_value_rented == 0.0:
            for n, s, c in name_status_rows:
                if s == "rented_out":
                    mp = full_price_map.get(n)
                    if mp: market_value_rented += mp * c

    market_value = market_value_steam + market_value_rented

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
                InventoryItem.status.in_(ACTIVE_STATUSES),
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
        mp = full_price_map.get(row[0])
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

    result = {
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
        "market_value": round(market_value, 2) if market_value else 0,
        "market_value_steam": round(market_value_steam, 2),
        "market_value_rented": round(market_value_rented, 2),
        "market_priced_count": market_priced_count,
        "pnl": round(pnl, 2) if pnl is not None else None,
        "pnl_pct": round(pnl_pct, 2) if pnl_pct is not None else None,
        "pnl_covered_count": pnl_count,
        "price_updated_at": price_updated_at,
        "price_refresh_status": price_refresh_status,
        "price_refresh_progress": price_refresh_progress,
    }
    _overview_cache["data"] = result
    _overview_cache["ts"] = time.monotonic()
    return result


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

    # 始终排除 unknown 状态（未确认物品不参与显示）
    q = q.where(InventoryItem.status != "unknown")

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

    if sort_by in ("current_price", "pnl", "pnl_pct"):
        # 按市价/盈亏/盈亏%排序：JOIN price_snapshot 子查询
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
        if sort_by == "current_price":
            sort_col = price_sq.c.cp
        elif sort_by == "pnl_pct":
            # PnL% = (price - cost) / cost, use case to avoid div-by-zero
            sort_col = case(
                (_effective > 0, (price_sq.c.cp - _effective) / _effective),
                else_=None,
            )
        else:
            sort_col = price_sq.c.cp - _effective
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
            "item_type": item.item_type,
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


@router.get("/chart-data")
async def chart_data(db: AsyncSession = Depends(get_db)):
    """Read-only aggregation for visualization charts (type composition, PnL distribution, top items)."""
    from app.services.pricing import get_all_latest_prices

    if _chart_cache["data"] is not None and time.monotonic() - _chart_cache["ts"] < _CHART_TTL:
        return _chart_cache["data"]

    cost_expr = func.coalesce(InventoryItem.purchase_price_manual, InventoryItem.purchase_price)
    has_price = or_(InventoryItem.purchase_price.isnot(None), InventoryItem.purchase_price_manual.isnot(None))

    rows = (await db.execute(
        select(
            InventoryItem.market_hash_name,
            InventoryItem.name,
            InventoryItem.item_type,
            func.count().label("qty"),
            func.sum(cost_expr).label("total_cost"),
            func.sum(case((has_price, 1), else_=0)).label("costed_qty"),
            func.min(InventoryItem.icon_url).label("icon_url"),
        )
        .where(InventoryItem.status.in_(ACTIVE_STATUSES))
        .group_by(InventoryItem.market_hash_name, InventoryItem.name, InventoryItem.item_type)
    )).all()

    prices = await get_all_latest_prices(db)

    items = []
    type_agg = {}
    pnl_buckets = {"<-50": 0, "-50~-30": 0, "-30~-10": 0, "-10~0": 0,
                   "0~10": 0, "10~30": 0, "30~50": 0, "50~100": 0, ">100": 0}
    for hash_name, cn_name, item_type, qty, total_cost, costed_qty, icon_url in rows:
        price = prices.get(hash_name, 0)
        mv = round(price * qty, 2)
        cost = round(total_cost or 0, 2)
        pnl = None
        pnl_pct = None
        if costed_qty and total_cost:
            avg_cost = total_cost / costed_qty
            if price > 0:
                pnl_pct = round((price - avg_cost) / avg_cost * 100, 1)
                pnl = round((price - avg_cost) * costed_qty, 2)
                if pnl_pct < -50: pnl_buckets["<-50"] += 1
                elif pnl_pct < -30: pnl_buckets["-50~-30"] += 1
                elif pnl_pct < -10: pnl_buckets["-30~-10"] += 1
                elif pnl_pct < 0: pnl_buckets["-10~0"] += 1
                elif pnl_pct < 10: pnl_buckets["0~10"] += 1
                elif pnl_pct < 30: pnl_buckets["10~30"] += 1
                elif pnl_pct < 50: pnl_buckets["30~50"] += 1
                elif pnl_pct < 100: pnl_buckets["50~100"] += 1
                else: pnl_buckets[">100"] += 1

        t = item_type or "其他"
        if t not in type_agg:
            type_agg[t] = {"type": t, "qty": 0, "market_value": 0, "cost": 0}
        type_agg[t]["qty"] += qty
        type_agg[t]["market_value"] += mv
        type_agg[t]["cost"] += cost

        items.append({"name": hash_name, "cn_name": cn_name or hash_name, "type": t,
                       "qty": qty, "market_value": mv, "cost": cost, "pnl": pnl, "pnl_pct": pnl_pct,
                       "icon_url": icon_url})

    items.sort(key=lambda x: x["market_value"], reverse=True)
    top_value = items[:20]
    gainers = sorted([i for i in items if i["pnl"] is not None and i["pnl"] > 0], key=lambda x: -x["pnl"])[:10]
    losers = sorted([i for i in items if i["pnl"] is not None and i["pnl"] < 0], key=lambda x: x["pnl"])[:10]
    type_list = sorted(type_agg.values(), key=lambda x: -x["market_value"])

    result = {
        "type_composition": type_list,
        "pnl_distribution": pnl_buckets,
        "top_value": top_value,
        "top_gainers": gainers,
        "top_losers": losers,
    }
    _chart_cache["data"] = result
    _chart_cache["ts"] = time.monotonic()
    return result
