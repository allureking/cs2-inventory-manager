"""
单品租赁实绩归因（v0.13.0,提案9a）

record_lease_income()  — 每日 00:01 PT 全分页拉取「当前在租清单」,
                          逐件 upsert (date, commodity_id, daily_rent) 到 lease_income_daily。
                          幂等:同日重跑只覆盖,不重复。

聚合查询(供 analysis API):
  get_item_lease_income(db, name, days)   — 单品近 N 天逐日租金 + 汇总
  get_lease_income_rankings(db, days)     — 按品聚合:在租天数/总租金/实际年化排行
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.utils import parse_money
from app.models.db_models import LeaseIncomeDaily

logger = logging.getLogger(__name__)

_PAGE_SIZE = 100
_MAX_PAGES = 200


def _today_pt() -> str:
    return datetime.now(ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d")


def _rent_yuan(info: dict) -> float:
    """shortLeasePrice 单位为分;个别字段历史上出现过字符串/带符号,统一走 parse_money 兜底。"""
    raw = info.get("shortLeasePrice")
    if raw is None:
        return 0.0
    try:
        return round(int(raw) / 100, 2)
    except (TypeError, ValueError):
        return round(parse_money(raw) / 100, 2)


async def record_lease_income(date_str: Optional[str] = None) -> dict:
    """全分页拉当前在租清单,落库当日实绩。返回统计供日志/测试。"""
    from app.core.database import AsyncSessionLocal
    from app.services.youpin import fetch_lease_records, get_active_token

    if not get_active_token():
        logger.warning("lease_income: 无悠悠 Token,跳过当日落库")
        return {"recorded": 0, "skipped_no_token": True}

    date_str = date_str or _today_pt()

    rows: dict[int, dict] = {}
    page = 1
    while page <= _MAX_PAGES:
        try:
            batch, _, _ = await fetch_lease_records(page=page, page_size=_PAGE_SIZE)
        except Exception as e:
            logger.error("lease_income: 拉取第 %d 页失败: %s", page, e)
            break
        if not batch:
            break
        for rec in batch:
            info = rec.get("commodityInfo") or {}
            cid = info.get("commodityId")
            hash_name = info.get("commodityHashName")
            if not cid or not hash_name:
                continue
            rows[int(cid)] = {
                "date": date_str,
                "commodity_id": int(cid),
                "market_hash_name": hash_name,
                "daily_rent": _rent_yuan(info),
            }
        if len(batch) < _PAGE_SIZE:
            break
        page += 1

    if not rows:
        logger.info("lease_income: %s 无在租记录", date_str)
        return {"recorded": 0, "date": date_str}

    async with AsyncSessionLocal() as db:
        await upsert_lease_income(db, list(rows.values()))
        await db.commit()

    total = round(sum(r["daily_rent"] for r in rows.values()), 2)
    logger.info("lease_income: DONE — %s 落库 %d 件,合计 ¥%.2f/天", date_str, len(rows), total)
    return {"recorded": len(rows), "date": date_str, "total_rent": total}


async def upsert_lease_income(db: AsyncSession, rows: list[dict]) -> None:
    """批量 upsert(同日同 commodity 覆盖)。供每日 job 与租赁导入复用。"""
    if not rows:
        return
    stmt = sqlite_insert(LeaseIncomeDaily).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["date", "commodity_id"],
        set_={
            "market_hash_name": stmt.excluded.market_hash_name,
            "daily_rent": stmt.excluded.daily_rent,
        },
    )
    await db.execute(stmt)


async def get_item_lease_income(db: AsyncSession, market_hash_name: str, days: int = 30) -> dict:
    """单品近 N 天逐日实绩 + 汇总(实际年化由调用方结合市价计算)。"""
    rows = (await db.execute(
        select(LeaseIncomeDaily.date,
               func.count(LeaseIncomeDaily.id),
               func.sum(LeaseIncomeDaily.daily_rent))
        .where(LeaseIncomeDaily.market_hash_name == market_hash_name)
        .group_by(LeaseIncomeDaily.date)
        .order_by(LeaseIncomeDaily.date.desc())
        .limit(days)
    )).all()
    rows = list(reversed(rows))
    total_rent = round(sum(r[2] or 0 for r in rows), 2)
    return {
        "market_hash_name": market_hash_name,
        "days_window": days,
        "days_recorded": len(rows),
        "series": [{"date": r[0], "rented_count": r[1], "rent": round(r[2] or 0, 2)} for r in rows],
        "total_rent": total_rent,
        "avg_daily_rent": round(total_rent / len(rows), 2) if rows else 0.0,
    }


async def get_lease_income_rankings(db: AsyncSession, days: int = 30, limit: int = 50) -> list[dict]:
    """按品聚合近 N 天实绩:件均在租天数、总租金、件均日租。"""
    cutoff = (await db.execute(
        select(LeaseIncomeDaily.date).distinct().order_by(LeaseIncomeDaily.date.desc()).limit(days)
    )).scalars().all()
    if not cutoff:
        return []
    min_date = min(cutoff)

    # v0.13.3 修正：units 曾用 COUNT(DISTINCT commodity_id)，但**同一物理饰品每个
    # 租赁周期都会拿到新的 commodity_id**（见 youpin.py 身份复用改造的说明）。
    # 30 天里周转 5 次的一件饰品会被算成 5 件 → avg_rent_per_unit_day 及其
    # 驱动的"实际年化"低估约 5 倍，且**周转越快（越优质的租赁资产）低估越狠**，
    # 与单品弹窗给出的数字自相矛盾。
    # 正确口径：件数 = 单日在租件数的峰值（典型持有量），逐日单件租金再平均。
    per_day = (await db.execute(
        select(
            LeaseIncomeDaily.market_hash_name.label("name"),
            LeaseIncomeDaily.date.label("d"),
            func.count(LeaseIncomeDaily.commodity_id).label("cnt"),
            func.sum(LeaseIncomeDaily.daily_rent).label("rent"),
        )
        .where(LeaseIncomeDaily.date >= min_date)
        .group_by(LeaseIncomeDaily.market_hash_name, LeaseIncomeDaily.date)
    )).all()

    agg: dict[str, dict] = {}
    for name, _d, cnt, rent in per_day:
        a = agg.setdefault(name, {"days": 0, "total": 0.0, "peak_units": 0, "unit_daily": []})
        a["days"] += 1
        a["total"] += rent or 0.0
        a["peak_units"] = max(a["peak_units"], cnt or 0)
        if cnt:
            a["unit_daily"].append((rent or 0.0) / cnt)

    out = [
        {
            "market_hash_name": name,
            "days_rented": a["days"],
            "units": a["peak_units"],                       # 峰值同时在租件数
            "total_rent": round(a["total"], 2),
            # 逐日单件租金取平均（件数波动时不会被除歪）
            "avg_rent_per_unit_day": round(
                sum(a["unit_daily"]) / len(a["unit_daily"]), 4) if a["unit_daily"] else 0.0,
        }
        for name, a in agg.items()
    ]
    out.sort(key=lambda x: -x["total_rent"])
    return out[:limit]
