"""
成本继承迁移(提案5①)+ 导入身份复用(提案5②)测试。内存库,无网络。

继承配对:
  - 唯一↔唯一 → 配对;任一侧 ≥2 或 0 → 跳过;abrade None 不参与
  - apply 幂等;manual 已有成本的不收
身份复用(import_lease_records):
  - unknown 同 hash+abrade 唯一 → 复用旧行(成本保留,行数不增)
  - 歧义(2 行) → 建新行;无 abrade → 建新行
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from sqlalchemy import select, func

import app.services.youpin as yp
from app.services.cost_inheritance import find_inheritance_pairs, apply_inheritance
from app.models.db_models import InventoryItem
from tests.conftest import memory_db

_seq = {"n": 0}


def _run(coro):
    return asyncio.run(coro)


def inv(name, status, abrade=None, price=None, manual=None, class_id="YOUPIN", cid=None):
    _seq["n"] += 1
    return InventoryItem(
        steam_id="", class_id=class_id, instance_id=f"i{_seq['n']}",
        market_hash_name=name, name=name, status=status, abrade=abrade,
        purchase_price=price, purchase_price_manual=manual, youpin_commodity_id=cid,
    )


async def _seed(Session, objs):
    async with Session() as db:
        for o in objs:
            db.add(o)
        await db.commit()


# ── find_inheritance_pairs / apply ─────────────────────────────────────────


def test_unique_pair_found_and_applied():
    async def body():
        async with memory_db() as Session:
            await _seed(Session, [
                inv("AK", "in_steam", abrade=0.123456),                       # 受赠:无成本
                inv("AK", "unknown", abrade=0.123456, price=100.0),           # 捐赠
            ])
            async with Session() as db:
                pairs = await find_inheritance_pairs(db)
                assert len(pairs) == 1
                assert pairs[0].purchase_price == 100.0
                applied = await apply_inheritance(db, pairs)
                assert applied == 1
                active = (await db.execute(select(InventoryItem).where(
                    InventoryItem.status == "in_steam"))).scalars().one()
                assert active.purchase_price == 100.0
                assert active.purchase_platform == "INHERITED"
    _run(body())


def test_ambiguous_donor_skipped():
    async def body():
        async with memory_db() as Session:
            await _seed(Session, [
                inv("AK", "in_steam", abrade=0.5),
                inv("AK", "unknown", abrade=0.5, price=100.0),
                inv("AK", "unknown", abrade=0.5, price=200.0),  # 两个捐赠方 → 歧义
            ])
            async with Session() as db:
                assert await find_inheritance_pairs(db) == []
    _run(body())


def test_ambiguous_recipient_skipped():
    async def body():
        async with memory_db() as Session:
            await _seed(Session, [
                inv("AK", "in_steam", abrade=0.5),
                inv("AK", "rented_out", abrade=0.5),            # 两个受赠方 → 歧义
                inv("AK", "unknown", abrade=0.5, price=100.0),
            ])
            async with Session() as db:
                assert await find_inheritance_pairs(db) == []
    _run(body())


def test_null_abrade_not_matched():
    async def body():
        async with memory_db() as Session:
            await _seed(Session, [
                inv("AK", "in_steam", abrade=None),
                inv("AK", "unknown", abrade=None, price=100.0),
            ])
            async with Session() as db:
                assert await find_inheritance_pairs(db) == []
    _run(body())


def test_manual_priced_recipient_excluded():
    async def body():
        async with memory_db() as Session:
            await _seed(Session, [
                inv("AK", "in_steam", abrade=0.5, manual=80.0),  # 已有 manual → 非受赠方
                inv("AK", "unknown", abrade=0.5, price=100.0),
            ])
            async with Session() as db:
                assert await find_inheritance_pairs(db) == []
    _run(body())


def test_apply_idempotent_rerun():
    async def body():
        async with memory_db() as Session:
            await _seed(Session, [
                inv("AK", "in_steam", abrade=0.5),
                inv("AK", "unknown", abrade=0.5, price=100.0),
            ])
            async with Session() as db:
                pairs = await find_inheritance_pairs(db)
                await apply_inheritance(db, pairs)
                # 重跑:受赠方已有成本 → 无配对
                assert await find_inheritance_pairs(db) == []
    _run(body())


# ── import_lease_records 身份复用 ───────────────────────────────────────────


def _lease_rec(cid, name, abrade=None, order="o1"):
    info = {"commodityId": cid, "commodityHashName": name, "name": name, "shortLeasePrice": 100}
    if abrade is not None:
        info["abrade"] = str(abrade)
    return {"orderId": order, "commodityInfo": info}


def _patch_lease_fetch(monkeypatch, records):
    async def fake(page=1, page_size=30):
        return (records, len(records), "件数：1｜价值：¥1｜总租金：¥1/天") if page == 1 else ([], 0, "")
    monkeypatch.setattr(yp, "fetch_lease_records", fake)


def test_import_reuses_unique_unknown_row(monkeypatch):
    async def body():
        async with memory_db() as Session:
            # 旧 unknown 行带成本(上个租赁周期遗留)
            await _seed(Session, [inv("AK", "unknown", abrade=0.123456, price=88.0, cid=111)])
            _patch_lease_fetch(monkeypatch, [_lease_rec(222, "AK", abrade=0.123456)])
            async with Session() as db:
                r = await yp.import_lease_records(db)
                assert r["upserted"] == 1
                rows = (await db.execute(select(InventoryItem))).scalars().all()
                assert len(rows) == 1                      # 复用,不建新行
                row = rows[0]
                assert row.status == "rented_out"
                assert row.youpin_commodity_id == 222      # 指向新周期
                assert row.purchase_price == 88.0          # 成本保留(断链根治)
    _run(body())


def test_import_ambiguous_creates_new_row(monkeypatch):
    async def body():
        async with memory_db() as Session:
            await _seed(Session, [
                inv("AK", "unknown", abrade=0.5, price=88.0, cid=111),
                inv("AK", "unknown", abrade=0.5, price=99.0, cid=112),  # 两候选 → 歧义
            ])
            _patch_lease_fetch(monkeypatch, [_lease_rec(222, "AK", abrade=0.5)])
            async with Session() as db:
                await yp.import_lease_records(db)
                n = (await db.execute(select(func.count(InventoryItem.id)))).scalar()
                assert n == 3  # 建了新行,unknown 两行原样
    _run(body())


def test_import_no_abrade_creates_new_row(monkeypatch):
    async def body():
        async with memory_db() as Session:
            await _seed(Session, [inv("AK", "unknown", abrade=0.5, price=88.0, cid=111)])
            _patch_lease_fetch(monkeypatch, [_lease_rec(222, "AK", abrade=None)])  # 无指纹
            async with Session() as db:
                await yp.import_lease_records(db)
                n = (await db.execute(select(func.count(InventoryItem.id)))).scalar()
                assert n == 2
    _run(body())


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
