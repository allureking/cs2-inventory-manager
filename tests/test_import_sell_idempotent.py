"""
出售记录导入的幂等性测试（v0.13.3 高危修复）。内存库 + mock,无网络。

背景:悠悠出售记录接口每次返回**全量历史**,记录里没有能定位到具体某一件的标识
(无 assetId、无本地 item id),只能按 market_hash_name 匹配。旧实现是「每条记录随手挑
一件在库的同名物品标 sold」,且不留"这条处理过了"的记号 —— 而 /import/sell 与
/import/all 都是用户可以反复点的按钮,于是每点一次全量导入,就再吞掉一批还在库的同名
物品标成 sold,持仓被逐轮蚕食且不可逆(sold 不会被任何流程标回来)。

本文件锁住:
  A. 同一份出售记录跑两次,第二次不得再标任何一件（核心幂等）
  B. 记录条数 > 已 sold 件数时,只补齐差额,不多标
  C. 在库件数不够时不报错,差额记入 not_found
  D. sold 名额只从 ACTIVE_STATUSES 里取,且不碰 YOUPIN/STEAM_PROTECTED 占位件
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from sqlalchemy import select

import app.services.youpin as yp
from app.models.db_models import InventoryItem
from tests.conftest import memory_db

NAME = "AK-47 | Redline (Field-Tested)"
_seq = {"n": 0}


def _run(coro):
    return asyncio.run(coro)


def inv(name=NAME, status="in_steam", class_id="STEAM"):
    _seq["n"] += 1
    return InventoryItem(
        steam_id="", class_id=class_id, instance_id=f"si{_seq['n']}",
        market_hash_name=name, name=name, status=status,
    )


def sell_rec(name=NAME):
    return {"productDetail": {"commodityHashName": name, "name": name}}


def _patch_sell(monkeypatch, records, page_size=30):
    """一次性返回全部记录(不足一页即终止分页)。"""
    async def fake(page=1, page_size=30):
        return records if page == 1 else []
    monkeypatch.setattr(yp, "fetch_sell_records", fake)


async def _seed(Session, items):
    async with Session() as db:
        for it in items:
            db.add(it)
        await db.commit()


async def _statuses(Session, name=NAME):
    async with Session() as db:
        rows = (await db.execute(
            select(InventoryItem.status).where(InventoryItem.market_hash_name == name)
        )).scalars().all()
    out = {}
    for s in rows:
        out[s] = out.get(s, 0) + 1
    return out


# ── A. 核心幂等 ─────────────────────────────────────────────────────────────


def test_rerun_does_not_mark_more_items(monkeypatch):
    """同一份出售记录跑两次 → 第二次 updated=0,在库件数不变。

    旧实现第二次会再吞掉 2 件在库物品。这是本次修复的核心。
    """
    _patch_sell(monkeypatch, [sell_rec(), sell_rec()])   # 历史上卖过 2 件

    async def body():
        async with memory_db() as Session:
            await _seed(Session, [inv() for _ in range(5)])   # 在库 5 件同名

            async with Session() as db:
                r1 = await yp.import_sell_records(db)
            assert r1["updated"] == 2
            assert await _statuses(Session) == {"sold": 2, "in_steam": 3}

            async with Session() as db:
                r2 = await yp.import_sell_records(db)
            assert r2["updated"] == 0, "重复导入不得再标 sold"
            assert r2["already_sold"] == 2
            assert await _statuses(Session) == {"sold": 2, "in_steam": 3}

            # 第三次也一样（收敛,不是"隔一次才稳"）
            async with Session() as db:
                await yp.import_sell_records(db)
            assert await _statuses(Session) == {"sold": 2, "in_steam": 3}
    _run(body())


def test_new_sale_appended_marks_only_the_gap(monkeypatch):
    """已对上 2 条,新增第 3 条出售记录 → 只再标 1 件。"""
    async def body():
        async with memory_db() as Session:
            await _seed(Session, [inv() for _ in range(5)])

            _patch_sell(monkeypatch, [sell_rec(), sell_rec()])
            async with Session() as db:
                await yp.import_sell_records(db)

            _patch_sell(monkeypatch, [sell_rec(), sell_rec(), sell_rec()])
            async with Session() as db:
                r = await yp.import_sell_records(db)
            assert r["updated"] == 1
            assert await _statuses(Session) == {"sold": 3, "in_steam": 2}
    _run(body())


# ── B/C. 边界 ───────────────────────────────────────────────────────────────


def test_more_records_than_items_records_shortfall(monkeypatch):
    """出售记录 3 条但在库只有 1 件 → 标 1 件,差额 2 记 not_found,不抛错。"""
    _patch_sell(monkeypatch, [sell_rec()] * 3)

    async def body():
        async with memory_db() as Session:
            await _seed(Session, [inv()])
            async with Session() as db:
                r = await yp.import_sell_records(db)
            assert r["updated"] == 1
            assert r["not_found_in_db"] == 2
            assert await _statuses(Session) == {"sold": 1}
    _run(body())


def test_independent_per_name(monkeypatch):
    """按名各自对账,一个名字的差额不得挪用到另一个名字。"""
    OTHER = "AWP | Asiimov (Field-Tested)"
    _patch_sell(monkeypatch, [sell_rec(), sell_rec(OTHER)])

    async def body():
        async with memory_db() as Session:
            await _seed(Session, [inv(), inv(), inv(name=OTHER)])
            async with Session() as db:
                await yp.import_sell_records(db)
            assert await _statuses(Session) == {"sold": 1, "in_steam": 1}
            assert await _statuses(Session, OTHER) == {"sold": 1}
    _run(body())


# ── D. 只从 ACTIVE 取名额,不碰占位件 ────────────────────────────────────────


def test_skips_placeholder_and_non_active(monkeypatch):
    """YOUPIN/STEAM_PROTECTED 占位件与 in_storage 不参与标 sold。"""
    _patch_sell(monkeypatch, [sell_rec()] * 3)

    async def body():
        async with memory_db() as Session:
            await _seed(Session, [
                inv(class_id="YOUPIN"),            # 占位:排除
                inv(class_id="STEAM_PROTECTED"),   # 占位:排除
                inv(status="in_storage"),          # 非 ACTIVE:排除
                inv(status="rented_out"),          # 可标
            ])
            async with Session() as db:
                r = await yp.import_sell_records(db)
            assert r["updated"] == 1
            st = await _statuses(Session)
            assert st.get("sold") == 1
            assert st.get("in_storage") == 1
            assert st.get("in_steam") == 2         # 两个占位件原样保留
    _run(body())


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
