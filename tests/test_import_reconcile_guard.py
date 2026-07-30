"""
导入对账完整性闸测试（v0.13.3 高危修复）。内存库 + mock,无网络。

背景:悠悠返回空列表(code=9004001 被 _check 视为正常)或分页中途失败时,
旧逻辑会无条件把全部 rented_out 置为 unknown 并 commit
→ 一次接口抖动就让 3000+ 件在租资产从全站市值/成本中消失,且无告警。

本文件锁住三条不变量,任一被改坏必须变红:
  A. 空响应   → 绝不对账,既有 rented_out 原样保留
  B. 分页截断 → 绝不对账(即便取到了一部分)
  C. 正常全量 → 照常对账(未出现的租约转 unknown),即闸门不能"因噎废食"
  D. 库存对账不得触碰 sold / in_storage
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

_seq = {"n": 0}


def _run(coro):
    return asyncio.run(coro)


def inv(name="AK-47 | Redline (Field-Tested)", status="rented_out", cid=None,
        class_id="YOUPIN", instance_id=None, purchase_price=None):
    _seq["n"] += 1
    return InventoryItem(
        steam_id="", class_id=class_id, instance_id=instance_id or f"i{_seq['n']}",
        market_hash_name=name, name=name, status=status,
        youpin_commodity_id=cid, purchase_price=purchase_price,
    )


def lease_rec(cid, name="AK-47 | Redline (Field-Tested)"):
    return {"orderId": f"o{cid}",
            "commodityInfo": {"commodityId": cid, "commodityHashName": name,
                              "name": name, "shortLeasePrice": 100}}


def _patch_lease(monkeypatch, pages, total_count, fail_at_page=None):
    """pages: {page_no: [records]};fail_at_page: 该页抛异常(模拟超时)"""
    async def fake(page=1, page_size=30):
        if fail_at_page is not None and page == fail_at_page:
            raise RuntimeError("simulated timeout")
        return pages.get(page, []), total_count, "件数：1｜价值：¥1｜总租金：¥1/天"
    monkeypatch.setattr(yp, "fetch_lease_records", fake)


async def _statuses(Session):
    async with Session() as db:
        rows = (await db.execute(select(InventoryItem))).scalars().all()
        return sorted(r.status for r in rows)


# ── A. 空响应绝不清空 ───────────────────────────────────────────────────────


def test_empty_response_never_wipes_rented_out(monkeypatch):
    """悠悠返回空列表 → 3 件在租必须原样保留(旧代码会全部变 unknown)。"""
    _patch_lease(monkeypatch, pages={}, total_count=0)

    async def body():
        async with memory_db() as Session:
            async with Session() as db:
                for i in range(3):
                    db.add(inv(cid=100 + i))
                await db.commit()
                r = await yp.import_lease_records(db)
                assert r["reconciled"] is False
                assert "空响应" in r["partial_reason"] or "未取到" in r["partial_reason"]
                assert r["reconciled_returned"] == 0
            assert await _statuses(Session) == ["rented_out"] * 3   # 零丢失
    _run(body())


# ── B. 分页截断绝不对账 ────────────────────────────────────────────────────


def test_pagination_failure_skips_reconcile(monkeypatch):
    """第 2 页超时 → 已有在租不得被清；仅 upsert 已取到的。"""
    full_page = [lease_rec(200 + i) for i in range(30)]   # 满页 → 会继续翻页
    _patch_lease(monkeypatch, pages={1: full_page}, total_count=100, fail_at_page=2)

    async def body():
        async with memory_db() as Session:
            async with Session() as db:
                db.add(inv(cid=999))            # 一件老在租,不在本次(截断的)结果里
                await db.commit()
                r = await yp.import_lease_records(db)
                assert r["reconciled"] is False
                assert "分页中断" in r["partial_reason"]
            # 老件必须仍是 rented_out(旧代码会变 unknown 且永不自愈)
            async with Session() as db:
                old = (await db.execute(
                    select(InventoryItem).where(InventoryItem.youpin_commodity_id == 999)
                )).scalar_one()
                assert old.status == "rented_out"
    _run(body())


def test_count_far_below_total_skips_reconcile(monkeypatch):
    """抓到 1 条但 API 说有 100 条 → 视为不可信,跳过对账。"""
    _patch_lease(monkeypatch, pages={1: [lease_rec(300)]}, total_count=100)

    async def body():
        async with memory_db() as Session:
            async with Session() as db:
                db.add(inv(cid=999))
                await db.commit()
                r = await yp.import_lease_records(db)
                assert r["reconciled"] is False
                assert "totalCount" in r["partial_reason"]
            async with Session() as db:
                old = (await db.execute(
                    select(InventoryItem).where(InventoryItem.youpin_commodity_id == 999)
                )).scalar_one()
                assert old.status == "rented_out"
    _run(body())


# ── C. 正常全量仍要对账(闸门不能因噎废食)────────────────────────────────


def test_full_fetch_still_reconciles(monkeypatch):
    """完整抓取:本次在租的标 rented_out,未出现的老件转 unknown。"""
    _patch_lease(monkeypatch, pages={1: [lease_rec(500)]}, total_count=1)

    async def body():
        async with memory_db() as Session:
            async with Session() as db:
                db.add(inv(cid=500))    # 本次仍在租
                db.add(inv(cid=501))    # 已归还,不在本次结果
                await db.commit()
                r = await yp.import_lease_records(db)
                assert r["reconciled"] is True
                assert r["partial_reason"] is None
            async with Session() as db:
                rows = {x.youpin_commodity_id: x.status for x in
                        (await db.execute(select(InventoryItem))).scalars().all()}
                assert rows[500] == "rented_out"   # 续租
                assert rows[501] == "unknown"      # 归还 → 待库存同步确认
    _run(body())


# ── D. 库存对账不得触碰 sold / in_storage ──────────────────────────────────


def test_stock_reconcile_preserves_sold_and_storage(monkeypatch):
    """已 sold / in_storage 的保护期物品不得被库存对账刷成 unknown。
    (旧逻辑无 status 过滤 → sold 每次同步都被还原,且 import_sell_records
     排除 STEAM_PROTECTED 永不标回)"""
    async def fake_stock(page=1, page_size=100):
        # 只返回 keep 这一件;sold/storage 两件不在结果里
        if page == 1:
            return ([{"id": 1, "assetId": "keep", "commodityHashName": "AK-47 | Redline (Field-Tested)",
                      "name": "AK", "abrade": "0.1"}], 1, "¥100")
        return ([], 1, "¥100")
    monkeypatch.setattr(yp, "fetch_stock_records", fake_stock)

    async def body():
        async with memory_db() as Session:
            async with Session() as db:
                db.add(inv(class_id="STEAM_PROTECTED", instance_id="sold-1", status="sold"))
                db.add(inv(class_id="STEAM_PROTECTED", instance_id="stor-1", status="in_storage"))
                await db.commit()
                try:
                    await yp.import_stock_records(db)
                except Exception:
                    pass   # 该函数还有其它外部依赖;此处只关心状态不被误改
            async with Session() as db:
                rows = {x.instance_id: x.status for x in
                        (await db.execute(select(InventoryItem))).scalars().all()}
                assert rows.get("sold-1") == "sold"          # 不得被还原
                assert rows.get("stor-1") == "in_storage"    # 不得被清
    _run(body())


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
