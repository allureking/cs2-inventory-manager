"""
共享定价查询函数

提供统一的 get_latest_prices()，供 dashboard、tracker、collector 共用。
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db_models import PriceSnapshot


async def get_latest_prices(
    market_hash_names: list[str], db: AsyncSession
) -> dict[str, float]:
    """
    返回 {market_hash_name: min_sell_price}，基于 price_snapshot 中最新一批快照。
    在最新 snapshot_minute 内取跨平台最低卖价。
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

    return {row[0]: float(row[1]) for row in rows}
