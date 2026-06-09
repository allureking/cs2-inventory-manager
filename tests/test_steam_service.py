"""
steam.py 服务的 DB 部分测试（内存库，无网络）。
（Steam Web API 抓取/解析部分依赖真实 Steam，见 REPORT §2 故意不覆盖。）

  - _batch_latest_prices：最新分钟 / 平台白名单(BUFF/YOUPIN/STEAM) / 0·null 排除
  - get_inventory_with_prices：**盈亏只用 BUFF 价**（characterization 锁定观察3）
  - get_portfolio_summary：in_steam+rented_out 分组、in_storage 仅计数不计值、空库存
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from app.services.steam import (
    _batch_latest_prices,
    get_inventory_with_prices,
    get_portfolio_summary,
)
from app.models.db_models import InventoryItem, PriceSnapshot
from tests.conftest import memory_db

_seq = {"n": 0}


def _run(coro):
    return asyncio.run(coro)


def item(name, status="in_steam", purchase_price=None):
    _seq["n"] += 1
    return InventoryItem(steam_id="", class_id="c", instance_id=f"i{_seq['n']}",
                         market_hash_name=name, name=name, status=status, purchase_price=purchase_price)


def snap(name, platform, sell_price, minute="202606080100"):
    return PriceSnapshot(market_hash_name=name, platform=platform, sell_price=sell_price, snapshot_minute=minute)


async def _seed(Session, objs):
    async with Session() as db:
        for o in objs:
            db.add(o)
        await db.commit()


# ── _batch_latest_prices ───────────────────────────────────────────────────


def test_batch_prices_empty():
    async def body():
        async with memory_db() as Session:
            async with Session() as db:
                assert await _batch_latest_prices([], db) == {}
    _run(body())


def test_batch_prices_latest_minute_and_platforms():
    async def body():
        async with memory_db() as Session:
            await _seed(Session, [
                snap("A", "BUFF", 50.0, "202606080000"),     # 旧分钟,忽略
                snap("A", "BUFF", 100.0, "202606080100"),    # 新分钟
                snap("A", "YOUPIN", 110.0, "202606080100"),
                snap("A", "C5", 90.0, "202606080100"),       # 平台白名单外 → 不收
            ])
            async with Session() as db:
                m = await _batch_latest_prices(["A"], db)
                assert m["A"]["BUFF"] == 100.0
                assert m["A"]["YOUPIN"] == 110.0
                assert "C5" not in m["A"]
                assert m["A"]["_minute"] == "202606080100"
    _run(body())


def test_batch_prices_zero_excluded():
    async def body():
        async with memory_db() as Session:
            await _seed(Session, [snap("A", "BUFF", 0.0, "202606080100"),
                                  snap("A", "YOUPIN", 5.0, "202606080100")])
            async with Session() as db:
                m = await _batch_latest_prices(["A"], db)
                assert "BUFF" not in m["A"]    # sell_price 0 → falsy,不收
                assert m["A"]["YOUPIN"] == 5.0
    _run(body())


# ── get_inventory_with_prices：BUFF-only 盈亏（观察3 characterization）────────


def test_profit_uses_buff_price():
    async def body():
        async with memory_db() as Session:
            await _seed(Session, [item("A", purchase_price=100.0), snap("A", "BUFF", 150.0)])
            async with Session() as db:
                rows = await get_inventory_with_prices(db, steam_id="", status_filter=["in_steam"])
                assert len(rows) == 1
                assert rows[0]["profit_loss"] == 50.0
                assert rows[0]["profit_pct"] == 50.0
                assert rows[0]["buff_sell_price"] == 150.0
    _run(body())


def test_profit_none_without_buff_even_if_youpin_present():
    # 观察3：盈亏只看 BUFF；仅有悠悠价时 profit_loss=None
    async def body():
        async with memory_db() as Session:
            await _seed(Session, [item("A", purchase_price=100.0), snap("A", "YOUPIN", 150.0)])
            async with Session() as db:
                rows = await get_inventory_with_prices(db, steam_id="", status_filter=["in_steam"])
                assert rows[0]["youpin_sell_price"] == 150.0
                assert rows[0]["buff_sell_price"] is None
                assert rows[0]["profit_loss"] is None   # 锁定当前行为
    _run(body())


def test_inventory_steam_id_scope():
    async def body():
        async with memory_db() as Session:
            await _seed(Session, [item("A")])  # steam_id=""
            async with Session() as db:
                # 不同 steam_id → 过滤为空
                assert await get_inventory_with_prices(db, steam_id="other", status_filter=["in_steam"]) == []
                assert len(await get_inventory_with_prices(db, steam_id="", status_filter=["in_steam"])) == 1
    _run(body())


# ── get_portfolio_summary ──────────────────────────────────────────────────


def test_summary_empty():
    async def body():
        async with memory_db() as Session:
            async with Session() as db:
                s = await get_portfolio_summary(db, steam_id="")
                assert s["portfolio"]["count"] == 0
                assert s["portfolio"]["profit_loss"] is None
                assert s["in_storage_count"] == 0
    _run(body())


def test_summary_groups_and_excludes_storage():
    async def body():
        async with memory_db() as Session:
            await _seed(Session, [
                item("A", status="in_steam", purchase_price=100.0),
                item("B", status="rented_out", purchase_price=200.0),
                item("C", status="in_storage", purchase_price=999.0),  # 收藏,不计入持仓
                snap("A", "BUFF", 150.0), snap("B", "BUFF", 250.0),
            ])
            async with Session() as db:
                s = await get_portfolio_summary(db, steam_id="")
                assert s["portfolio"]["count"] == 2            # in_steam+rented_out
                assert s["portfolio"]["buff_value"] == 400.0   # 150+250
                assert s["portfolio"]["total_cost"] == 300.0   # 100+200
                assert s["portfolio"]["profit_loss"] == 100.0
                assert s["in_storage_count"] == 1
                assert s["in_steam"]["count"] == 1 and s["rented_out"]["count"] == 1
    _run(body())


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
