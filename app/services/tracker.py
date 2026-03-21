"""
每日收益追踪服务

功能：
  snapshot_daily()       — 自动抓取当日数据并写入 daily_tracker
  get_daily_records()    — 查询日期范围记录
  get_monthly_summary()  — 月度汇总（动态聚合）
  update_record()        — 手动编辑某天数据
  import_from_excel()    — 从 xlsx 导入历史数据
  export_to_excel()      — 导出 xlsx
"""

from __future__ import annotations

import io
import logging
import re
from calendar import monthrange
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import select, func, or_
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db_models import DailyTracker, InventoryItem, PriceSnapshot

logger = logging.getLogger(__name__)

# 悠悠平台服务费 20%
_FEE_RATE = 0.20
_NET_RATE = 1 - _FEE_RATE  # 0.8

# 年化计算参数（与 Excel 公式一致）
_SHORT_DAYS = 182.5   # 短租年化天数
_LONG_DAYS = 267.0    # 长租年化天数
_SHORT_WEIGHT = 0.7   # 综合年化中短租权重
_LONG_WEIGHT = 0.3    # 综合年化中长租权重

_ACTIVE = ["in_steam", "rented_out", "in_storage"]


# ══════════════════════════════════════════════════════════════
#  解析 & 计算
# ══════════════════════════════════════════════════════════════

def _parse_stats_desc(text: str) -> dict:
    """
    解析悠悠租出统计摘要。
    输入: "件数：3,320｜价值：¥3612634.69｜总租金：¥2466.82/天"
    输出: {"count": 3320, "value": 3612634.69, "income": 2466.82}
    """
    result = {"count": 0, "value": 0.0, "income": 0.0}
    if not text:
        return result

    # 件数
    m = re.search(r"件数[：:]\s*([\d,]+)", text)
    if m:
        result["count"] = int(m.group(1).replace(",", ""))

    # 价值
    m = re.search(r"价值[：:]\s*¥?([\d,.]+)", text)
    if m:
        result["value"] = float(m.group(1).replace(",", ""))

    # 总租金
    m = re.search(r"总租金[：:]\s*¥?([\d,.]+)", text)
    if m:
        result["income"] = float(m.group(1).replace(",", ""))

    return result


def _calc_annuals(daily_income: float, rented_value: float) -> dict:
    """计算短租/长租/综合年化收益率"""
    if not rented_value or rented_value <= 0:
        return {"short": None, "long": None, "combined": None}

    net = daily_income * _NET_RATE
    short = net * _SHORT_DAYS / rented_value
    long = net * _LONG_DAYS / rented_value
    combined = short * _SHORT_WEIGHT + long * _LONG_WEIGHT

    return {
        "short": round(short, 8),
        "long": round(long, 8),
        "combined": round(combined, 8),
    }


# ══════════════════════════════════════════════════════════════
#  自动快照
# ══════════════════════════════════════════════════════════════

async def snapshot_daily() -> dict:
    """
    抓取当日数据并写入 daily_tracker。
    1. 调用悠悠 API 获取租赁统计（几秒内完成）
    2. DB 查询库存件数和总市值
    3. 计算年化、涨跌
    4. 写入 daily_tracker（upsert）
    """
    from app.core.database import AsyncSessionLocal
    from app.services.youpin import fetch_lease_records, get_active_token

    today = date.today().isoformat()

    # 1) 租赁统计
    rental = {"count": 0, "value": 0.0, "income": 0.0}
    token = get_active_token()
    if token:
        try:
            _, _, stats_desc = await fetch_lease_records(page=1, page_size=1)
            rental = _parse_stats_desc(stats_desc)
        except Exception as e:
            logger.warning("tracker snapshot_daily: 获取租赁统计失败: %s", e)
    else:
        logger.warning("tracker snapshot_daily: 无悠悠 Token，跳过租赁数据")

    # 2) 库存数据
    async with AsyncSessionLocal() as db:
        # 总活跃件数
        total_inv = (await db.execute(
            select(func.count(InventoryItem.id))
            .where(InventoryItem.status.in_(_ACTIVE))
        )).scalar() or 0

        # 库存市值：按 market_hash_name 聚合 × 最新价格
        name_count_rows = (await db.execute(
            select(
                InventoryItem.market_hash_name,
                func.count(InventoryItem.id).label("cnt"),
            )
            .where(InventoryItem.status.in_(_ACTIVE))
            .group_by(InventoryItem.market_hash_name)
        )).all()

        # 获取每个饰品的最新价格（取 YOUPIN 平台优先，其次 STEAMDT）
        all_names = [r[0] for r in name_count_rows]
        price_map = await _get_latest_prices(all_names, db)

        inv_value = 0.0
        for name, cnt in name_count_rows:
            p = price_map.get(name)
            if p:
                inv_value += p * cnt

        # 3) 涨跌：(当日市值 - 基准值) / 基准值
        # 基准值取最早一条记录的 inventory_value，若无则用当前值
        base_val_row = (await db.execute(
            select(DailyTracker.inventory_value)
            .where(DailyTracker.inventory_value.isnot(None), DailyTracker.inventory_value > 0)
            .order_by(DailyTracker.date.asc())
            .limit(1)
        )).scalar()
        base_val = base_val_row if base_val_row else inv_value
        price_change = (inv_value - base_val) / base_val if base_val > 0 else 0.0

        # 4) 计算年化
        annuals = _calc_annuals(rental["income"], rental["value"])

        income_per_item = (
            round(rental["income"] / rental["count"], 8)
            if rental["count"] > 0 else None
        )

        # 5) 写入（upsert）
        row = {
            "date": today,
            "rented_count": rental["count"],
            "rented_value": round(rental["value"], 2),
            "daily_income": round(rental["income"], 2),
            "short_lease_annual": annuals["short"],
            "long_lease_annual": annuals["long"],
            "combined_annual": annuals["combined"],
            "income_per_item": income_per_item,
            "total_inventory": total_inv,
            "inventory_value": round(inv_value, 2),
            "price_change": round(price_change, 8),
        }

        stmt = sqlite_insert(DailyTracker).values([row])
        stmt = stmt.on_conflict_do_update(
            index_elements=["date"],
            set_={k: stmt.excluded[k] for k in row if k != "date"},
        )
        await db.execute(stmt)
        await db.commit()

    logger.info("tracker snapshot_daily: %s 写入成功", today)
    return row


async def _get_latest_prices(names: list[str], db: AsyncSession) -> dict[str, float]:
    """获取一批饰品的最新价格（优先 YOUPIN，其次其他平台）"""
    if not names:
        return {}

    # 取每个 market_hash_name 最新的 sell_price
    rows = (await db.execute(
        select(
            PriceSnapshot.market_hash_name,
            PriceSnapshot.sell_price,
        )
        .where(
            PriceSnapshot.market_hash_name.in_(names),
            PriceSnapshot.sell_price.isnot(None),
            PriceSnapshot.sell_price > 0,
        )
        .order_by(PriceSnapshot.snapshot_minute.desc())
        .distinct(PriceSnapshot.market_hash_name)
    )).all()

    # SQLite 不支持 DISTINCT ON，用 Python 去重取最新
    price_map: dict[str, float] = {}
    for name, price in rows:
        if name not in price_map:
            price_map[name] = float(price)

    return price_map


# ══════════════════════════════════════════════════════════════
#  CRUD
# ══════════════════════════════════════════════════════════════

async def get_daily_records(
    db: AsyncSession,
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> list[dict]:
    """查询日期范围内的每日记录"""
    q = select(DailyTracker).order_by(DailyTracker.date.desc())
    if start:
        q = q.where(DailyTracker.date >= start)
    if end:
        q = q.where(DailyTracker.date <= end)

    rows = (await db.execute(q)).scalars().all()
    return [_row_to_dict(r) for r in rows]


async def get_monthly_summary(db: AsyncSession, year: int, month: int) -> dict:
    """动态聚合月度汇总"""
    days_in_month = monthrange(year, month)[1]
    start = f"{year:04d}-{month:02d}-01"
    end = f"{year:04d}-{month:02d}-{days_in_month:02d}"

    rows = (await db.execute(
        select(DailyTracker)
        .where(DailyTracker.date >= start, DailyTracker.date <= end)
        .order_by(DailyTracker.date.asc())
    )).scalars().all()

    if not rows:
        return {"year": year, "month": month, "days": 0}

    incomes = [r.daily_income for r in rows if r.daily_income is not None]
    total_income = sum(incomes)
    service_fee = round(total_income * _FEE_RATE, 2)
    net_rental = round(total_income * _NET_RATE, 2)

    # 月末库存价值（取最后一天有值的记录）
    last_val = None
    for r in reversed(rows):
        if r.inventory_value and r.inventory_value > 0:
            last_val = r.inventory_value
            break

    net_annual = round(net_rental * 12 / last_val, 6) if last_val else None

    # 综合年化平均值
    annuals = [r.combined_annual for r in rows if r.combined_annual is not None]
    avg_annual = round(sum(annuals) / len(annuals), 6) if annuals else None

    return {
        "year": year,
        "month": month,
        "days": len(rows),
        "total_income": round(total_income, 2),
        "service_fee": service_fee,
        "net_rental": net_rental,
        "net_rental_annual": net_annual,
        "avg_combined_annual": avg_annual,
        "last_inventory_value": last_val,
    }


async def update_record(db: AsyncSession, date_str: str, fields: dict) -> dict | None:
    """手动编辑某天的数据"""
    row = (await db.execute(
        select(DailyTracker).where(DailyTracker.date == date_str)
    )).scalar_one_or_none()

    if not row:
        return None

    allowed = {"steamdt_index", "notes", "rented_count", "rented_value",
               "daily_income", "total_inventory", "inventory_value"}
    for k, v in fields.items():
        if k in allowed:
            setattr(row, k, v)

    # 如果修改了核心字段，重新计算年化
    if any(k in fields for k in ("daily_income", "rented_value", "rented_count")):
        annuals = _calc_annuals(row.daily_income or 0, row.rented_value or 0)
        row.short_lease_annual = annuals["short"]
        row.long_lease_annual = annuals["long"]
        row.combined_annual = annuals["combined"]
        if row.rented_count and row.daily_income:
            row.income_per_item = round(row.daily_income / row.rented_count, 8)

    await db.commit()
    return _row_to_dict(row)


# ══════════════════════════════════════════════════════════════
#  Excel 导入 / 导出
# ══════════════════════════════════════════════════════════════

async def import_from_excel(db: AsyncSession, file_bytes: bytes) -> dict:
    """
    从 xlsx 导入每日数据。
    期望列顺序与 Excel KHH sheet 一致：
      A=日期, B=出租件数, C=总价值, D=总收益/天,
      E=短租年化, F=长租年化, G=综合年化, H=单件收益/天,
      I=总库存, J=库存总价值, K=涨跌, L=SteamDT指数
    """
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
    ws = wb.active

    imported = 0
    skipped = 0

    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row or len(row) < 4:
            skipped += 1
            continue

        raw_date = row[0]
        if raw_date is None:
            skipped += 1
            continue

        # 解析日期
        if isinstance(raw_date, datetime):
            d = raw_date.strftime("%Y-%m-%d")
        elif isinstance(raw_date, date):
            d = raw_date.isoformat()
        elif isinstance(raw_date, (int, float)):
            # Excel serial date
            from datetime import timedelta
            d = (datetime(1899, 12, 30) + timedelta(days=int(raw_date))).strftime("%Y-%m-%d")
        else:
            d = str(raw_date).strip()[:10]

        rented_count = _safe_int(row[1]) if len(row) > 1 else None
        rented_value = _safe_float(row[2]) if len(row) > 2 else None
        daily_income = _safe_float(row[3]) if len(row) > 3 else None

        if rented_count is None and daily_income is None:
            skipped += 1
            continue

        rec = {
            "date": d,
            "rented_count": rented_count,
            "rented_value": rented_value,
            "daily_income": daily_income,
            "short_lease_annual": _safe_float(row[4]) if len(row) > 4 else None,
            "long_lease_annual": _safe_float(row[5]) if len(row) > 5 else None,
            "combined_annual": _safe_float(row[6]) if len(row) > 6 else None,
            "income_per_item": _safe_float(row[7]) if len(row) > 7 else None,
            "total_inventory": _safe_int(row[8]) if len(row) > 8 else None,
            "inventory_value": _safe_float(row[9]) if len(row) > 9 else None,
            "price_change": _safe_float(row[10]) if len(row) > 10 else None,
            "steamdt_index": _safe_float(row[11]) if len(row) > 11 else None,
        }

        stmt = sqlite_insert(DailyTracker).values([rec])
        stmt = stmt.on_conflict_do_update(
            index_elements=["date"],
            set_={k: stmt.excluded[k] for k in rec if k != "date" and rec[k] is not None},
        )
        await db.execute(stmt)
        imported += 1

    await db.commit()
    return {"imported": imported, "skipped": skipped}


async def export_to_excel(db: AsyncSession, start: Optional[str] = None, end: Optional[str] = None) -> bytes:
    """导出每日数据为 xlsx"""
    import openpyxl

    records = await get_daily_records(db, start, end)
    # 按日期正序
    records.sort(key=lambda r: r["date"])

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Daily Tracker"

    headers = [
        "日期", "出租总件数", "总价值", "总收益/天",
        "短租年化", "长租年化", "综合年化", "单件收益/天",
        "总库存", "库存总价值", "涨跌", "SteamDT指数", "备注",
    ]
    ws.append(headers)

    fields = [
        "date", "rented_count", "rented_value", "daily_income",
        "short_lease_annual", "long_lease_annual", "combined_annual", "income_per_item",
        "total_inventory", "inventory_value", "price_change", "steamdt_index", "notes",
    ]
    for rec in records:
        ws.append([rec.get(f) for f in fields])

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ══════════════════════════════════════════════════════════════
#  工具函数
# ══════════════════════════════════════════════════════════════

def _row_to_dict(r: DailyTracker) -> dict:
    return {
        "date": r.date,
        "rented_count": r.rented_count,
        "rented_value": r.rented_value,
        "daily_income": r.daily_income,
        "short_lease_annual": r.short_lease_annual,
        "long_lease_annual": r.long_lease_annual,
        "combined_annual": r.combined_annual,
        "income_per_item": r.income_per_item,
        "total_inventory": r.total_inventory,
        "inventory_value": r.inventory_value,
        "price_change": r.price_change,
        "steamdt_index": r.steamdt_index,
        "notes": r.notes,
    }


def _safe_float(v) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
        return f if not (f != f) else None  # NaN check
    except (TypeError, ValueError):
        return None


def _safe_int(v) -> Optional[int]:
    if v is None:
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None
