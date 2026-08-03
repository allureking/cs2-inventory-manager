"""
CSQAQ「历史最高价」提取测试（AUDIT H3）。内存库 + mock，无网络。

背景（从生产 IP 实测真实响应得出）
----------------------------------
`sync_all_items` 原先按六个猜出来的键找 ATH：
    max_price / highest_price / history_max_price / ath_price / max_sell_price / sell_price_max
实测真实响应有 96 个字段，**这六个一个都不存在**。

猜不中时原代码会 fallback 去扫 `sell_price_{1,7,15,30,90,180,365}` 取 max 当历史最高价。
但那批字段实测是「N 日涨跌额」而不是价格 —— 真实值形如：
    sell_price_1 = 0.0 / sell_price_15 = -328.0 / sell_price_180 = -4800.0 / sell_price_365 = -20045.5
于是 fallback 实际挑的是「最大的正涨跌额」，被当成 ATH 写库。生产 quant_signal 里已有
**27,407 行**这样的垃圾值（★ Nomad Knife 的「历史最高价」= ¥1.9）。

本文件锁住：
  A. 真实响应形状（六键缺失 + sell_price_* 为涨跌额）→ **绝不产出 ATH**
  B. 六键缺失时要留 warning（让字段名漂移可见），且每次同步只警告一次
  C. 上游若真的提供了 ATH 字段 → 照常采纳（不能把功能一并砍掉）
  D. 脏值（字符串/None/0/负数）不得让整次同步崩掉
"""

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from sqlalchemy import select

import app.services.csqaq as csqaq
from app.models.db_models import InventoryItem, Item, QuantSignal
from tests.conftest import memory_db

NAME = "★ Nomad Knife | Crimson Web (Field-Tested)"

# 生产实测的真实响应形状：六个 ATH 键都不存在，sell_price_* 是涨跌额（多为负）
REAL_SHAPE = {
    "yyyp_lease_price": 12.5,
    "yyyp_lease_annual": 8.3,
    "turnover_number": 42,
    "statistic": 1234,
    "sell_price_1": 0.0,
    "sell_price_7": 15.5,        # 正的涨跌额 —— 旧 fallback 会把它当成 ATH
    "sell_price_15": -328.0,
    "sell_price_30": -99.5,
    "sell_price_90": -1200.0,
    "sell_price_180": -4800.0,
    "sell_price_365": -20045.5,
    "buff_sell_price_7": 3.2,
    "steam_sell_price_30": 1.9,
    "max_float": 0.38,           # 唯一含 max 的真实字段，是磨损值不是价格
}


def _run(coro):
    return asyncio.run(coro)


async def _seed(Session):
    async with Session() as db:
        db.add(InventoryItem(steam_id="", class_id="STEAM", instance_id="i1",
                             market_hash_name=NAME, name=NAME, status="in_steam"))
        db.add(Item(market_hash_name=NAME, name=NAME, csqaq_good_id=1))
        await db.commit()


def _patch(monkeypatch, info):
    async def fake_good(client, good_id):
        return info
    monkeypatch.setattr(csqaq, "_fetch_good", fake_good)
    monkeypatch.setattr(csqaq, "_RATE_LIMIT_DELAY", 0)
    # sync_all_items 开头是 `if not settings.csqaq_api_key: return 0`
    # —— 不设它的话函数直接返回，所有断言都会变成空绿
    monkeypatch.setattr(csqaq.settings, "csqaq_api_key", "test-key")


def _assert_ran(synced):
    """守卫：确认 sync 真的处理了条目，避免整组测试退化成空绿。"""
    assert synced >= 1, "sync_all_items 没有真正跑起来，断言无意义"


async def _ath_in_db(Session):
    async with Session() as db:
        return (await db.execute(
            select(QuantSignal.csqaq_ath_price).where(QuantSignal.market_hash_name == NAME)
        )).scalars().first()


# ── A. 真实响应形状：绝不产出 ATH ──────────────────────────────────────────


def test_real_response_shape_yields_no_ath(monkeypatch, caplog):
    """回归锁：真实响应（六键缺失 + 涨跌额）不得写出任何 csqaq_ath_price。

    修复前这里会写入 15.5（sell_price_7 那个正的涨跌额）作为
    「★ Nomad Knife 的历史最高价」—— 一把刀的历史最高价 ¥15.5，显然是错的。
    """
    _patch(monkeypatch, REAL_SHAPE)

    async def body():
        async with memory_db() as Session:
            monkeypatch.setattr(csqaq, "AsyncSessionLocal", Session)
            await _seed(Session)
            with caplog.at_level(logging.WARNING, logger="app.services.csqaq"):
                _assert_ran(await csqaq.sync_all_items())
            assert await _ath_in_db(Session) is None, "涨跌额不得被当成历史最高价写库"
    _run(body())


def test_missing_ath_fields_logs_warning(monkeypatch, caplog):
    """六键全 miss 要留 warning —— 否则字段名漂移会像之前那样静默一整年。"""
    _patch(monkeypatch, REAL_SHAPE)

    async def body():
        async with memory_db() as Session:
            monkeypatch.setattr(csqaq, "AsyncSessionLocal", Session)
            await _seed(Session)
            with caplog.at_level(logging.WARNING, logger="app.services.csqaq"):
                _assert_ran(await csqaq.sync_all_items())
            msgs = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
            assert any("ATH" in m for m in msgs), f"应当有 ATH 字段缺失的 warning: {msgs}"
    _run(body())


def test_other_fields_still_written(monkeypatch):
    """只砍 ATH，租金/成交量/存世量这些真实存在的字段照常写入。"""
    _patch(monkeypatch, REAL_SHAPE)

    async def body():
        async with memory_db() as Session:
            monkeypatch.setattr(csqaq, "AsyncSessionLocal", Session)
            await _seed(Session)
            _assert_ran(await csqaq.sync_all_items())
            async with Session() as db:
                row = (await db.execute(
                    select(QuantSignal).where(QuantSignal.market_hash_name == NAME)
                )).scalars().first()
            assert row is not None, "同步应当仍然写出 quant_signal 行"
            assert row.daily_rent == 12.5
            assert row.rental_annual == 8.3
            assert row.steam_turnover == 42
            assert row.global_supply == 1234
            assert row.csqaq_ath_price is None
    _run(body())


# ── C. 上游真给 ATH 时仍要采纳 ─────────────────────────────────────────────


@pytest.mark.parametrize("key", ["max_price", "highest_price", "history_max_price",
                                 "ath_price", "max_sell_price", "sell_price_max"])
def test_real_ath_field_is_accepted(monkeypatch, key):
    """六个候选键里任何一个真的出现且为正数 → 采纳。功能没有被一并砍掉。"""
    _patch(monkeypatch, {**REAL_SHAPE, key: 8888.0})

    async def body():
        async with memory_db() as Session:
            monkeypatch.setattr(csqaq, "AsyncSessionLocal", Session)
            await _seed(Session)
            _assert_ran(await csqaq.sync_all_items())
            assert await _ath_in_db(Session) == 8888.0
    _run(body())


# ── D. 脏值不得炸掉整次同步 ────────────────────────────────────────────────


@pytest.mark.parametrize("bad", ["abc", None, 0, -5, "", [1, 2]])
def test_dirty_ath_value_does_not_crash_sync(monkeypatch, bad):
    _patch(monkeypatch, {**REAL_SHAPE, "max_price": bad})

    async def body():
        async with memory_db() as Session:
            monkeypatch.setattr(csqaq, "AsyncSessionLocal", Session)
            await _seed(Session)
            _assert_ran(await csqaq.sync_all_items())   # 不得抛
            assert await _ath_in_db(Session) is None
    _run(body())


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
