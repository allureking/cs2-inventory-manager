"""
大盘指数自动填入（v0.13.5）

此前「收益追踪」日表的大盘指数只能每天手动敲，漏一天就是一个永久空洞
（生产上 2026-07-22 起已连空 10 天）。改为每天自动从 SteamDT 开放平台取。

口径是怎么定的（不是拍脑袋，是反推出来的）
------------------------------------------
拿生产库里 78 天手工值，对 SteamDT 小时线做全组合比对（时区 × open/close × 24 小时）：

    平均绝对误差  时区      字段    小时
        1.527    PT(-7)   close     0     ← 最优
        1.838    PT(-7)   close     1

其中 6 天完全精确匹配（差 0.00），其余多在 1 点以内，偏差中位数 -0.06、无系统性偏移
——说明这就是同一条序列，不需要任何换算或日期平移。剩下那点噪声来自手工抄录时刻的
分钟级差异。

于是口径定为 **PT 00:00 那根小时线的收盘价**，恰好与 snapshot_daily 写库存价值是同一
时刻，天然满足「两者同步对应」。

为什么用 kline 而不是 /broad/v1/index
--------------------------------------
kline type=1 一次返回 90 天小时线，所以同一次调用既填当天、也补上此前所有空缺——
任务哪天挂了、服务停了几天，下次跑自动追平，不需要人工补录。/index 只给当下值，
补不了历史，仅在 kline 失败时兜底当天。

安全边界
--------
- **只填空，不覆盖**：默认只写 steamdt_index IS NULL 的行。手工填过的 235 天原样保留
  （其中 2025-10 有 600/1600 两个疑似录入笔误，要改由用户自己决定，程序不擅自动手）。
- **不新建行**：只更新 daily_tracker 里已存在的日期。行由 snapshot_daily 创建，
  指数依附于「那天有库存数据」这个前提，否则就成了孤立的指数行。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select, update

from app.models.db_models import DailyTracker

logger = logging.getLogger(__name__)

PT = ZoneInfo("America/Los_Angeles")

# 取哪一根小时线：PT 当日 0 点（与 snapshot_daily 同刻）
INDEX_PT_HOUR = 0
# K 线各列：[时间戳, 开盘, 收盘, 最高, 最低]
_CLOSE_IDX = 2


def _pt_day_and_hour(ts) -> tuple[str, int]:
    """秒级时间戳 → (PT 日期字符串, PT 小时)。"""
    t = datetime.fromtimestamp(int(ts), timezone.utc).astimezone(PT)
    return t.strftime("%Y-%m-%d"), t.hour


def extract_daily_index(kline: list[list]) -> dict[str, float]:
    """从小时线里挑出每个 PT 日 0 点那根的收盘价 → {date: index}。

    脏数据（列数不足/非数值/非正数）跳过而不是抛错——一根坏 K 线不该让整天的
    自动填入失败。
    """
    out: dict[str, float] = {}
    for row in kline or []:
        if not isinstance(row, (list, tuple)) or len(row) <= _CLOSE_IDX:
            continue
        try:
            day, hour = _pt_day_and_hour(row[0])
            if hour != INDEX_PT_HOUR:
                continue
            val = float(row[_CLOSE_IDX])
        except (TypeError, ValueError, OSError, OverflowError):
            continue
        if val > 0:
            out[day] = val
    return out


async def sync_market_index(
    days: int = 90,
    overwrite: bool = False,
    kline: Optional[list[list]] = None,
) -> dict:
    """
    拉大盘指数并填入 daily_tracker。

    days      —— 只处理最近 N 天（默认 90，即 kline 能给的全部）
    overwrite —— True 时连已有值一起覆盖（默认 False：只填空，不动手工值）
    kline     —— 传入则跳过网络请求（供测试与复用同一份数据）
    """
    from app.core.database import AsyncSessionLocal
    from app.services.steamdt import fetch_broad_kline

    if kline is None:
        try:
            kline = await fetch_broad_kline()
        except Exception as e:
            logger.error("market_index: 拉取大盘 K 线失败: %s", e)
            return {"ok": False, "error": str(e), "filled": 0}

    by_day = extract_daily_index(kline)
    if not by_day:
        logger.warning("market_index: K 线里没解析出任何 PT %d 点的收盘价", INDEX_PT_HOUR)
        return {"ok": False, "error": "no usable kline rows", "filled": 0}

    cutoff = (datetime.now(PT) - timedelta(days=days)).strftime("%Y-%m-%d")

    filled: list[str] = []
    skipped_existing = 0
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(DailyTracker.date, DailyTracker.steamdt_index)
            .where(DailyTracker.date >= cutoff)
        )).all()

        for date_str, current in rows:
            val = by_day.get(date_str)
            if val is None:
                continue
            if current is not None and not overwrite:
                skipped_existing += 1
                continue
            if current is not None and abs(float(current) - val) < 1e-9:
                continue
            await db.execute(
                update(DailyTracker)
                .where(DailyTracker.date == date_str)
                .values(steamdt_index=val)
            )
            filled.append(date_str)
        await db.commit()

    logger.info("market_index: DONE — 填入 %d 天%s，跳过已有 %d 天",
                len(filled), f"({filled[0]}~{filled[-1]})" if filled else "", skipped_existing)
    return {
        "ok": True,
        "filled": len(filled),
        "dates": filled,
        "skipped_existing": skipped_existing,
        "available_days": len(by_day),
    }


async def run_market_index_sync() -> None:
    """调度器入口：每日跑一次，顺带把此前所有空缺一并补上。"""
    await sync_market_index()
