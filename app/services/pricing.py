"""
共享定价查询函数

提供统一的 get_latest_prices()，供 dashboard、tracker、collector、quant_engine 共用。

口径（v0.13.3 修正）
--------------------
"当前市价" = **每个平台各取其最新报价，再跨平台取最低价**。

修正前是「先取该饰品全局最新的 snapshot_minute，再只在那一分钟内取 MIN」，问题在于
写入侧有两条节奏完全不同的通路：

  - collector 日批：BUFF / STEAM / YOUPIN 三行写在同一个 snapshot_minute
    → "最新一分钟"含三平台，MIN 是真·跨平台最低价。
  - youpin.bulk_refresh_market_prices（用户点「刷新市价」）：只写 platform='YOUPIN'，
    且逐件请求、每件各自 stamp 当前分钟
    → 此后该件"最新一分钟"里只剩悠悠一行，BUFF/STEAM 被整体排除出 MIN。

于是同一张 overview 上两种口径混用，全站持仓市值与 PnL 会随「这件有没有被手动刷新过」
静默跳档——而这正是最容易被当成"行情波动"而看不出来的一类错。改成按平台各取最新后，
两条写入通路给出同一口径。

陈旧报价：用**相对**新鲜度窗口（某平台的最新报价落后于该饰品全平台最新报价超过
PRICE_STALE_HOURS 即剔除），而不是绝对时间窗。理由是绝对窗在采集中断时会让所有价格
一起消失（持仓市值瞬间归零，比价格偏旧危险得多）；相对窗在整体中断时三平台一起变旧、
一起保留，只有"单个平台掉队"才会被剔除，正好对应真实的失效模式。

另注：quant_engine._calc_spread_map 与 analysis /spreads 早已用
`MAX(snapshot_minute) GROUP BY name, platform`，本次把主口径统一到同一逻辑。
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db_models import PriceSnapshot

# 某平台最新报价比"该饰品全平台最新报价"落后超过此小时数 → 视为掉队，不参与取最低价。
# 日批是每天一次，留出 72h 可容忍两次连续采集失败而不误伤。
PRICE_STALE_HOURS = 72

_MINUTE_FMT = "%Y%m%d%H%M"


def _parse_minute(minute: str) -> Optional[datetime]:
    try:
        return datetime.strptime(minute, _MINUTE_FMT)
    except (TypeError, ValueError):
        return None


async def _query_min_prices(
    db: AsyncSession, names: Optional[list[str]], stale_hours: int = PRICE_STALE_HOURS
) -> dict[str, float]:
    """每平台各取最新报价 → 剔除掉队平台 → 跨平台取最低价。"""
    # 子查询：每个 (饰品, 平台) 各自的最新 snapshot_minute
    latest_q = select(
        PriceSnapshot.market_hash_name.label("mhn"),
        PriceSnapshot.platform.label("plat"),
        func.max(PriceSnapshot.snapshot_minute).label("latest_minute"),
    )
    if names is not None:
        latest_q = latest_q.where(PriceSnapshot.market_hash_name.in_(names))
    latest = latest_q.group_by(
        PriceSnapshot.market_hash_name, PriceSnapshot.platform
    ).subquery()

    rows = (
        await db.execute(
            select(
                PriceSnapshot.market_hash_name,
                PriceSnapshot.snapshot_minute,
                func.min(PriceSnapshot.sell_price).label("price"),
            )
            .join(
                latest,
                and_(
                    PriceSnapshot.market_hash_name == latest.c.mhn,
                    PriceSnapshot.platform == latest.c.plat,
                    PriceSnapshot.snapshot_minute == latest.c.latest_minute,
                ),
            )
            .where(PriceSnapshot.sell_price.isnot(None), PriceSnapshot.sell_price > 0)
            .group_by(
                PriceSnapshot.market_hash_name,
                PriceSnapshot.platform,
                PriceSnapshot.snapshot_minute,
            )
        )
    ).all()

    # 每件的各平台候选价（此时行数 = 饰品数 × 平台数，量级很小）
    per_item: dict[str, list[tuple[str, float]]] = {}
    for name, minute, price in rows:
        per_item.setdefault(name, []).append((minute, float(price)))

    out: dict[str, float] = {}
    for name, quotes in per_item.items():
        newest = max(q[0] for q in quotes)
        newest_dt = _parse_minute(newest)
        fresh = []
        for minute, price in quotes:
            dt = _parse_minute(minute)
            # 分钟串解析不了（脏数据）就不做新鲜度判断，保留该报价，宁松勿误杀
            if newest_dt is None or dt is None:
                fresh.append(price)
            elif (newest_dt - dt).total_seconds() <= stale_hours * 3600:
                fresh.append(price)
        if fresh:
            out[name] = min(fresh)

    return out


async def get_latest_prices(
    market_hash_names: list[str], db: AsyncSession
) -> dict[str, float]:
    """
    返回 {market_hash_name: 跨平台最低价}。
    每个平台取其各自最新报价，掉队平台（落后 >PRICE_STALE_HOURS）剔除后取 min。
    没有任何有效报价的饰品不出现在返回字典中。
    """
    if not market_hash_names:
        return {}
    return await _query_min_prices(db, market_hash_names)


async def get_all_latest_prices(db: AsyncSession) -> dict[str, float]:
    """同 get_latest_prices，但不限定名称列表。"""
    return await _query_min_prices(db, None)
