"""
pricing.py 查询函数测试（内存库）。

get_latest_prices / get_all_latest_prices 的语义：
  - 每个 (饰品, 平台) 各取其最新 snapshot_minute（v0.13.3 修正：不是全局最新那一分钟）
  - 掉队平台（落后该饰品全平台最新报价 >PRICE_STALE_HOURS）剔除后，跨平台取 **最低** sell_price
  - 仅计 sell_price 非空且 > 0
  - 没有有效最新报价的饰品不出现在结果里

覆盖边界：空名单 / 缺价 / 跨平台取 min / 多分钟只认最新分钟 / null·0·负价排除 /
         最新分钟全为无效价 → 即便旧分钟有有效价也排除。
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from app.services.pricing import get_all_latest_prices, get_latest_prices
from app.models.db_models import PriceSnapshot
from tests.conftest import memory_db

NAME = "AK-47 | Redline (Field-Tested)"
NAME2 = "★ Karambit | Doppler (Factory New)"


def _run(coro):
    return asyncio.run(coro)


async def _seed(Session, rows):
    async with Session() as db:
        for r in rows:
            db.add(PriceSnapshot(**r))
        await db.commit()


def snap(name=NAME, platform="YOUPIN", sell_price=100.0, minute="202606080000"):
    return dict(market_hash_name=name, platform=platform, sell_price=sell_price, snapshot_minute=minute)


# ── get_latest_prices ──────────────────────────────────────────────────────


def test_empty_names_returns_empty():
    async def body():
        async with memory_db() as Session:
            async with Session() as db:
                assert await get_latest_prices([], db) == {}
    _run(body())


def test_name_with_no_snapshot_absent():
    async def body():
        async with memory_db() as Session:
            await _seed(Session, [snap()])
            async with Session() as db:
                r = await get_latest_prices(["不存在的饰品"], db)
                assert r == {}
    _run(body())


def test_single_price():
    async def body():
        async with memory_db() as Session:
            await _seed(Session, [snap(sell_price=123.45)])
            async with Session() as db:
                r = await get_latest_prices([NAME], db)
                assert r == {NAME: 123.45}
    _run(body())


def test_cross_platform_takes_min():
    async def body():
        async with memory_db() as Session:
            await _seed(Session, [
                snap(platform="YOUPIN", sell_price=110.0),
                snap(platform="BUFF", sell_price=99.0),
                snap(platform="STEAM", sell_price=130.0),
            ])
            async with Session() as db:
                r = await get_latest_prices([NAME], db)
                assert r[NAME] == 99.0  # 跨平台最低
    _run(body())


def test_only_latest_minute_counts_even_if_higher():
    # 旧分钟 50（更低），新分钟 200 —— 应取新分钟的 200（最新分钟优先,不是全局最低）
    async def body():
        async with memory_db() as Session:
            await _seed(Session, [
                snap(sell_price=50.0, minute="202606080000"),
                snap(sell_price=200.0, minute="202606080100"),
            ])
            async with Session() as db:
                r = await get_latest_prices([NAME], db)
                assert r[NAME] == 200.0
    _run(body())


def test_latest_minute_min_across_platforms():
    async def body():
        async with memory_db() as Session:
            await _seed(Session, [
                snap(platform="YOUPIN", sell_price=80.0, minute="202606080000"),   # 旧
                snap(platform="YOUPIN", sell_price=210.0, minute="202606080100"),  # 新
                snap(platform="BUFF",   sell_price=190.0, minute="202606080100"),  # 新,更低
            ])
            async with Session() as db:
                r = await get_latest_prices([NAME], db)
                assert r[NAME] == 190.0
    _run(body())


def test_null_price_excluded_but_valid_kept():
    async def body():
        async with memory_db() as Session:
            await _seed(Session, [
                snap(platform="YOUPIN", sell_price=None, minute="202606080100"),
                snap(platform="BUFF",   sell_price=150.0, minute="202606080100"),
            ])
            async with Session() as db:
                r = await get_latest_prices([NAME], db)
                assert r[NAME] == 150.0
    _run(body())


def test_zero_and_negative_excluded():
    async def body():
        async with memory_db() as Session:
            await _seed(Session, [
                snap(platform="YOUPIN", sell_price=0.0, minute="202606080100"),
                snap(platform="BUFF",   sell_price=-5.0, minute="202606080100"),
                snap(platform="STEAM",  sell_price=77.0, minute="202606080100"),
            ])
            async with Session() as db:
                r = await get_latest_prices([NAME], db)
                assert r[NAME] == 77.0
    _run(body())


def test_latest_minute_all_invalid_excludes_name():
    # 最新分钟全是 0/null（即便旧分钟有有效价）→ 该饰品不出现
    async def body():
        async with memory_db() as Session:
            await _seed(Session, [
                snap(sell_price=100.0, minute="202606080000"),          # 旧分钟有效
                snap(sell_price=0.0,   minute="202606080100"),          # 最新分钟无效
                snap(platform="BUFF", sell_price=None, minute="202606080100"),
            ])
            async with Session() as db:
                r = await get_latest_prices([NAME], db)
                assert NAME not in r
    _run(body())


def test_manual_youpin_refresh_does_not_drop_other_platforms():
    """回归锁（v0.13.3）：手动「刷新市价」只写 YOUPIN 一行，不得把 BUFF/STEAM 挤出取价。

    bulk_refresh_market_prices 逐件请求悠悠、每件 stamp 当前分钟且只写 platform='YOUPIN'。
    旧实现按"全局最新分钟"取价 → 刷新后该件最新分钟里只有悠悠 → 跨平台最低价
    静默退化成悠悠单价，全站市值/PnL 随"这件刷没刷过"跳档。
    """
    async def body():
        async with memory_db() as Session:
            await _seed(Session, [
                # 日批：三平台同一分钟
                snap(platform="YOUPIN", sell_price=110.0, minute="202606080005"),
                snap(platform="BUFF",   sell_price=99.0,  minute="202606080005"),
                snap(platform="STEAM",  sell_price=130.0, minute="202606080005"),
                # 用户点刷新：只有悠悠，且分钟更新、价格更高
                snap(platform="YOUPIN", sell_price=115.0, minute="202606081432"),
            ])
            async with Session() as db:
                r = await get_latest_prices([NAME], db)
                # 悠悠用刷新后的 115（各平台取各自最新），但 BUFF 的 99 仍参与比较
                assert r[NAME] == 99.0   # 旧实现会返回 115.0
    _run(body())


def test_stale_platform_dropped_out_of_min():
    """单个平台掉队（停更 >72h）→ 其陈旧低价不得继续压住当前市价。"""
    async def body():
        async with memory_db() as Session:
            await _seed(Session, [
                snap(platform="BUFF",   sell_price=60.0,  minute="202606010000"),  # 7 天前，早已停更
                snap(platform="YOUPIN", sell_price=120.0, minute="202606080000"),
                snap(platform="STEAM",  sell_price=125.0, minute="202606080000"),
            ])
            async with Session() as db:
                r = await get_latest_prices([NAME], db)
                assert r[NAME] == 120.0   # 不是 60.0
    _run(body())


def test_all_platforms_equally_stale_still_priced():
    """采集整体中断时三平台一起变旧 → 必须仍然出价（相对窗而非绝对窗）。

    绝对时间窗会在采集连挂几天后让全站持仓市值瞬间归零，比价格偏旧危险得多。
    """
    async def body():
        async with memory_db() as Session:
            await _seed(Session, [
                snap(platform="YOUPIN", sell_price=120.0, minute="202601010000"),
                snap(platform="BUFF",   sell_price=99.0,  minute="202601010000"),
            ])
            async with Session() as db:
                r = await get_latest_prices([NAME], db)
                assert r[NAME] == 99.0
    _run(body())


def test_multiple_names_independent_latest_minute():
    async def body():
        async with memory_db() as Session:
            await _seed(Session, [
                snap(name=NAME, sell_price=100.0, minute="202606080100"),
                snap(name=NAME2, sell_price=8000.0, minute="202606070000"),  # 不同饰品各自最新分钟
            ])
            async with Session() as db:
                r = await get_latest_prices([NAME, NAME2], db)
                assert r == {NAME: 100.0, NAME2: 8000.0}
    _run(body())


def test_returns_float_type():
    async def body():
        async with memory_db() as Session:
            await _seed(Session, [snap(sell_price=42)])
            async with Session() as db:
                r = await get_latest_prices([NAME], db)
                assert isinstance(r[NAME], float)
    _run(body())


# ── get_all_latest_prices ──────────────────────────────────────────────────


def test_all_latest_empty_db():
    async def body():
        async with memory_db() as Session:
            async with Session() as db:
                assert await get_all_latest_prices(db) == {}
    _run(body())


def test_all_latest_covers_all_names():
    async def body():
        async with memory_db() as Session:
            await _seed(Session, [
                snap(name=NAME, sell_price=100.0),
                snap(name=NAME2, sell_price=9000.0),
            ])
            async with Session() as db:
                r = await get_all_latest_prices(db)
                assert r == {NAME: 100.0, NAME2: 9000.0}
    _run(body())


def test_all_latest_same_semantics_as_named():
    # all 与 named 在同数据上应给出一致结果
    async def body():
        async with memory_db() as Session:
            rows = [
                snap(name=NAME, platform="YOUPIN", sell_price=120.0, minute="202606080100"),
                snap(name=NAME, platform="BUFF", sell_price=110.0, minute="202606080100"),
                snap(name=NAME2, sell_price=5000.0, minute="202606080100"),
            ]
            await _seed(Session, rows)
            async with Session() as db:
                all_r = await get_all_latest_prices(db)
                named_r = await get_latest_prices([NAME, NAME2], db)
                assert all_r == named_r == {NAME: 110.0, NAME2: 5000.0}
    _run(body())


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
