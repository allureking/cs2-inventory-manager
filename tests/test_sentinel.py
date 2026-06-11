"""
凭证哨兵测试(v0.13.0 提案6)：mock check_token_status,内存库,无网络。

  - token 失效 → 写入 critical quant_alert + 返回 alerted
  - 已有未读凭证告警 → 去重不重复写
  - token 恢复 → 未读凭证告警自动转已读(自动愈合)
  - 外部渠道未配置 → 不发推送(无网络调用)
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from sqlalchemy import select

import app.core.database as core_db
import app.services.sentinel as sentinel
import app.services.youpin as yp
from app.models.db_models import QuantAlert
from tests.conftest import memory_db


def _run(coro):
    return asyncio.run(coro)


def _patch_token(monkeypatch, valid, error=None):
    async def fake():
        return {"valid": valid, "nickname": "测试" if valid else None, "error": error}
    monkeypatch.setattr(yp, "check_token_status", fake)


def _patch_no_push(monkeypatch):
    calls = {"n": 0}

    async def fake_push(title, body):
        calls["n"] += 1
    monkeypatch.setattr(sentinel, "_push_external", fake_push)
    return calls


def test_invalid_token_creates_critical_alert(monkeypatch):
    _patch_token(monkeypatch, False, "Token 已过期")
    push = _patch_no_push(monkeypatch)

    async def body():
        async with memory_db() as Session:
            monkeypatch.setattr(core_db, "AsyncSessionLocal", Session)
            r = await sentinel.run_credential_sentinel()
            assert r == {"youpin_valid": False, "alerted": True}
            async with Session() as db:
                rows = (await db.execute(select(QuantAlert))).scalars().all()
                assert len(rows) == 1
                a = rows[0]
                assert a.alert_type == "credential"
                assert a.severity == "critical"
                assert a.is_read is False
                assert "Token" in a.title
    _run(body())
    assert push["n"] == 1  # 外推走了(被 mock)


def test_dedupe_no_duplicate_unread_alert(monkeypatch):
    _patch_token(monkeypatch, False, "Token 已过期")
    push = _patch_no_push(monkeypatch)

    async def body():
        async with memory_db() as Session:
            monkeypatch.setattr(core_db, "AsyncSessionLocal", Session)
            r1 = await sentinel.run_credential_sentinel()
            r2 = await sentinel.run_credential_sentinel()
            assert r1["alerted"] is True
            assert r2 == {"youpin_valid": False, "alerted": False, "deduped": True}
            async with Session() as db:
                rows = (await db.execute(select(QuantAlert))).scalars().all()
                assert len(rows) == 1  # 不刷屏
    _run(body())
    assert push["n"] == 1


def test_recovery_auto_heals_unread_alert(monkeypatch):
    push = _patch_no_push(monkeypatch)

    async def body():
        async with memory_db() as Session:
            monkeypatch.setattr(core_db, "AsyncSessionLocal", Session)
            _patch_token(monkeypatch, False, "Token 已过期")
            await sentinel.run_credential_sentinel()
            _patch_token(monkeypatch, True)
            r = await sentinel.run_credential_sentinel()
            assert r == {"youpin_valid": True, "alerted": False}
            async with Session() as db:
                rows = (await db.execute(select(QuantAlert))).scalars().all()
                assert len(rows) == 1
                assert rows[0].is_read is True  # 自动愈合
    _run(body())


def test_valid_token_no_alert(monkeypatch):
    _patch_token(monkeypatch, True)
    _patch_no_push(monkeypatch)

    async def body():
        async with memory_db() as Session:
            monkeypatch.setattr(core_db, "AsyncSessionLocal", Session)
            r = await sentinel.run_credential_sentinel()
            assert r == {"youpin_valid": True, "alerted": False}
            async with Session() as db:
                assert (await db.execute(select(QuantAlert))).scalars().all() == []
    _run(body())


def test_push_external_skips_without_channels():
    # 渠道未配置 → 函数直接结束,不发任何网络请求(httpx client 在 with 内不被使用)
    async def body():
        await sentinel._push_external("t", "b")  # 不抛错即通过
    _run(body())


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
