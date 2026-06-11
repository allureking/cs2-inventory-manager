"""
成本继承迁移（v0.13.0,提案5①）

背景:import_lease_records 每个租赁周期为同一物理饰品生成新 commodity_id → 新行,
旧行连同 purchase_price 滞留为 unknown。结果 ¥30M+ 成本挂在死行上,
活跃持仓 PnL 覆盖率仅 ~51%。

策略(零歧义才动):abrade(磨损值)是物理指纹。
  - 受赠方:active(in_steam/rented_out)且无任何成本(purchase_price 与 manual 均空)
  - 捐赠方:unknown 且有 purchase_price
  - 仅当同 (market_hash_name, abrade) 下 受赠方恰 1 行 且 捐赠方恰 1 行 时配对
  - abrade 为空的不参与(无指纹,歧义不可控)

apply 幂等:受赠方获得成本后不再满足"无成本"条件,重跑自然跳过。
"""

from __future__ import annotations

import logging
from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import ACTIVE_STATUSES
from app.models.db_models import InventoryItem

logger = logging.getLogger(__name__)


class InheritancePair(NamedTuple):
    active_id: int
    donor_id: int
    market_hash_name: str
    abrade: float
    purchase_price: float
    purchase_date: str | None
    purchase_platform: str | None


async def find_inheritance_pairs(db: AsyncSession) -> list[InheritancePair]:
    """扫描并返回零歧义配对(只读,供 dry-run 与执行共用)。"""
    actives = (await db.execute(
        select(InventoryItem.id, InventoryItem.market_hash_name, InventoryItem.abrade)
        .where(
            InventoryItem.status.in_(ACTIVE_STATUSES),
            InventoryItem.purchase_price.is_(None),
            InventoryItem.purchase_price_manual.is_(None),
            InventoryItem.abrade.isnot(None),
        )
    )).all()

    donors = (await db.execute(
        select(InventoryItem.id, InventoryItem.market_hash_name, InventoryItem.abrade,
               InventoryItem.purchase_price, InventoryItem.purchase_date,
               InventoryItem.purchase_platform)
        .where(
            InventoryItem.status == "unknown",
            InventoryItem.purchase_price.isnot(None),
            InventoryItem.abrade.isnot(None),
        )
    )).all()

    def key(name: str, ab: float) -> tuple:
        return (name, round(ab, 6))

    a_map: dict[tuple, list] = {}
    for r in actives:
        a_map.setdefault(key(r[1], r[2]), []).append(r)
    d_map: dict[tuple, list] = {}
    for r in donors:
        d_map.setdefault(key(r[1], r[2]), []).append(r)

    pairs: list[InheritancePair] = []
    for k, a_rows in a_map.items():
        d_rows = d_map.get(k)
        if not d_rows or len(a_rows) != 1 or len(d_rows) != 1:
            continue  # 任一侧不唯一 → 歧义,跳过
        a, d = a_rows[0], d_rows[0]
        pairs.append(InheritancePair(
            active_id=a[0], donor_id=d[0],
            market_hash_name=k[0], abrade=k[1],
            purchase_price=d[3], purchase_date=d[4], purchase_platform=d[5],
        ))
    return pairs


async def apply_inheritance(db: AsyncSession, pairs: list[InheritancePair]) -> int:
    """把捐赠方成本写到受赠方(不动捐赠行,留作审计;归档由提案8处理)。"""
    applied = 0
    for p in pairs:
        item = await db.get(InventoryItem, p.active_id)
        if item is None or item.purchase_price is not None or item.purchase_price_manual is not None:
            continue  # 并发/重跑保护
        item.purchase_price = p.purchase_price
        if p.purchase_date:
            item.purchase_date = p.purchase_date
        item.purchase_platform = p.purchase_platform or "INHERITED"
        applied += 1
    await db.commit()
    logger.info("cost_inheritance: applied %d / %d pairs", applied, len(pairs))
    return applied
