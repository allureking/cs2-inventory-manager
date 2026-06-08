"""
悠悠分页 loop-until-empty-page 终止逻辑测试。

import_buy_records / import_sell_records 的循环：
  page=1; while page<=MAX_PAGES:
    batch = fetch(page)         # 异常 → break
    if not batch: break          # 空页 → 停
    accumulate
    if len(batch) < PAGE_SIZE: break   # 末页不满 → 停
    page += 1

mock 掉 fetch_buy_records / fetch_sell_records（不发真实网络），用 dummy 记录 {}（
匹配阶段 _parse_hash_name 返回 None 被跳过），只验证：累积条数 + 终止时机 + 调用次数。
PAGE_SIZE=30, MAX_PAGES=200。
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from app.services import youpin
from app.services.youpin import import_buy_records, import_sell_records
from tests.conftest import memory_db

PAGE_SIZE = 30


def _run(coro):
    return asyncio.run(coro)


def _make_fake(pages):
    """pages: 每页内容(list)或要抛的 Exception。返回 (fake_coro, calls)。"""
    calls = {"n": 0}

    async def fake(page: int = 1, page_size: int = 30):
        calls["n"] += 1
        item = pages[page - 1] if page - 1 < len(pages) else []
        if isinstance(item, Exception):
            raise item
        return item

    return fake, calls


def _full():
    return [{} for _ in range(PAGE_SIZE)]


def _partial(n):
    return [{} for _ in range(n)]


# ── import_buy_records 分页 ─────────────────────────────────────────────────


@pytest.mark.parametrize("fn_name,importer", [
    ("fetch_buy_records", import_buy_records),
    ("fetch_sell_records", import_sell_records),
])
class TestPaginationTermination:
    def test_empty_first_page(self, monkeypatch, fn_name, importer):
        fake, calls = _make_fake([[]])
        monkeypatch.setattr(youpin, fn_name, fake)

        async def body():
            async with memory_db() as Session:
                async with Session() as db:
                    res = await importer(db)
                    assert res["total_records"] == 0
        _run(body())
        assert calls["n"] == 1  # 空页即停

    def test_single_partial_page(self, monkeypatch, fn_name, importer):
        fake, calls = _make_fake([_partial(5)])
        monkeypatch.setattr(youpin, fn_name, fake)

        async def body():
            async with memory_db() as Session:
                async with Session() as db:
                    res = await importer(db)
                    assert res["total_records"] == 5
        _run(body())
        assert calls["n"] == 1  # 末页不满 → 停,不再请求下一页

    def test_full_then_empty(self, monkeypatch, fn_name, importer):
        fake, calls = _make_fake([_full(), []])
        monkeypatch.setattr(youpin, fn_name, fake)

        async def body():
            async with memory_db() as Session:
                async with Session() as db:
                    res = await importer(db)
                    assert res["total_records"] == PAGE_SIZE
        _run(body())
        assert calls["n"] == 2  # 满页后再请求,空页停

    def test_full_then_partial(self, monkeypatch, fn_name, importer):
        fake, calls = _make_fake([_full(), _partial(7)])
        monkeypatch.setattr(youpin, fn_name, fake)

        async def body():
            async with memory_db() as Session:
                async with Session() as db:
                    res = await importer(db)
                    assert res["total_records"] == PAGE_SIZE + 7
        _run(body())
        assert calls["n"] == 2  # 第二页不满 → 停

    def test_multi_full_then_empty(self, monkeypatch, fn_name, importer):
        fake, calls = _make_fake([_full(), _full(), []])
        monkeypatch.setattr(youpin, fn_name, fake)

        async def body():
            async with memory_db() as Session:
                async with Session() as db:
                    res = await importer(db)
                    assert res["total_records"] == PAGE_SIZE * 2
        _run(body())
        assert calls["n"] == 3

    def test_exception_on_first_page_breaks(self, monkeypatch, fn_name, importer):
        fake, calls = _make_fake([RuntimeError("boom")])
        monkeypatch.setattr(youpin, fn_name, fake)

        async def body():
            async with memory_db() as Session:
                async with Session() as db:
                    res = await importer(db)
                    assert res["total_records"] == 0  # 异常 break,不抛出
        _run(body())
        assert calls["n"] == 1

    def test_exception_on_second_page_keeps_first(self, monkeypatch, fn_name, importer):
        fake, calls = _make_fake([_full(), RuntimeError("boom")])
        monkeypatch.setattr(youpin, fn_name, fake)

        async def body():
            async with memory_db() as Session:
                async with Session() as db:
                    res = await importer(db)
                    assert res["total_records"] == PAGE_SIZE  # 保留第一页
        _run(body())
        assert calls["n"] == 2

    def test_max_pages_cap(self, monkeypatch, fn_name, importer):
        # 永远返回满页 → 应在 MAX_PAGES(200) 处停
        always_full = [_full() for _ in range(250)]
        fake, calls = _make_fake(always_full)
        monkeypatch.setattr(youpin, fn_name, fake)

        async def body():
            async with memory_db() as Session:
                async with Session() as db:
                    res = await importer(db)
                    assert res["total_records"] == PAGE_SIZE * 200
        _run(body())
        assert calls["n"] == 200  # 不会无限循环


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
