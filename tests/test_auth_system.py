"""
用户系统 characterization（v0.10.0）。

钉住的行为：
  - hash_password / verify_password：pbkdf2 roundtrip、错密码拒绝、坏格式拒绝
  - issue_token / parse_token：签名校验、篡改拒绝、过期拒绝
  - SessionAuthMiddleware：
      * 用户表为空 → 完全直通（0.9.x 兼容,种子前/本地开发）
      * 有用户后：无凭证 /api/* → 401；页面 → 302 /login；
        白名单(/health,/login,/api/auth/login)直通；
        session cookie 通过；APP_API_KEY(X-API-Key)等价通过
  - APIKeyMiddleware 兼容：session 用户写操作无需 X-API-Key
  - 登录：错密码 401；5 次失败锁 429；成功下发 HttpOnly cookie
  - 改密：旧密码错 400；成功后旧 token 失效、新密码可登录、旧密码不可
  - scripts/create_user.py：建号打印密码；--reset 重置并使旧 session 失效
"""

from __future__ import annotations

import asyncio
import sqlite3
import sys
import time
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

import app.core.database as core_db
import app.services.auth as auth_svc
from app.core.config import settings
from app.models.db_models import AppUser
from tests.conftest import memory_db

PW = "pw12345678"
PW_HASH = auth_svc.hash_password(PW)  # 模块级算一次（600k 迭代,逐测试算太慢）


def _run(coro):
    return asyncio.run(coro)


def _reset_auth_state():
    auth_svc.reset_users_exist_cache()
    auth_svc._fail_log.clear()


def _build_app():
    """最小 app：双中间件 + auth 路由 + 受保护的读/写探针路由。"""
    from main import APIKeyMiddleware, SessionAuthMiddleware
    from app.api.routes import auth as auth_routes
    from app.core.database import get_db

    app = FastAPI()
    app.add_middleware(APIKeyMiddleware)
    app.add_middleware(SessionAuthMiddleware)
    app.include_router(auth_routes.router, prefix="/api/auth")

    @app.get("/api/data")
    async def data():
        return {"ok": True}

    @app.post("/api/write")
    async def write():
        return {"written": True}

    @app.get("/")
    async def index():
        return {"page": "index"}

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app, get_db


def _client_ctx(Session, app, get_db):
    async def _override():
        async with Session() as db:
            yield db
    app.dependency_overrides[get_db] = _override
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def _seed_user(Session, username="superadmin", role="super_admin"):
    async with Session() as db:
        db.add(AppUser(username=username, password_hash=PW_HASH, role=role,
                       password_changed_at=0.0))
        await db.commit()


def _cookie_from(resp) -> str:
    sc = resp.headers.get("set-cookie", "")
    assert auth_svc.SESSION_COOKIE in sc
    return sc.split(f"{auth_svc.SESSION_COOKIE}=", 1)[1].split(";", 1)[0]


# ── 密码哈希 / token ───────────────────────────────────────────────────────


def test_password_hash_roundtrip():
    assert auth_svc.verify_password(PW, PW_HASH)
    assert not auth_svc.verify_password("wrong-password", PW_HASH)
    assert not auth_svc.verify_password(PW, "garbage")
    assert not auth_svc.verify_password(PW, "")


def test_token_roundtrip_tamper_expiry():
    with mock.patch.object(settings, "app_secret", "test-secret"):
        tok = auth_svc.issue_token(7)
        assert auth_svc.parse_token(tok) is not None
        assert auth_svc.parse_token(tok)[0] == 7
        # 篡改 user_id → 签名不过
        parts = tok.split(".")
        assert auth_svc.parse_token(".".join(["8"] + parts[1:])) is None
        # 过期 token
        old = auth_svc.issue_token(7, now=time.time() - auth_svc.SESSION_TTL - 10)
        assert auth_svc.parse_token(old) is None
        # 换密钥后签名失效
        with mock.patch.object(settings, "app_secret", "other-secret"):
            assert auth_svc.parse_token(tok) is None


# ── 中间件门禁 ────────────────────────────────────────────────────────────


def test_middleware_fail_closed_when_no_users():
    """v0.13.3 行为变更(安全):用户表为空 → fail-closed,不再静默直通。

    旧行为(0.9.x~0.13.2)是直通,风险:恢复 v0.10.0 之前的备份、误删 app_user、
    或新机 init_db 建完空表就起服务 → 全站读端点(持仓/成本/逐件PnL/租赁明细)
    对公网敞开且无告警。现在 API 返回 503、页面 302 → /login。
    """
    async def body():
        async with memory_db() as Session:
            _reset_auth_state()
            app, get_db = _build_app()
            with mock.patch.object(core_db, "AsyncSessionLocal", Session), \
                 mock.patch.object(settings, "app_api_key", ""), \
                 mock.patch.object(settings, "allow_anonymous", False):
                async with _client_ctx(Session, app, get_db) as c:
                    assert (await c.get("/api/data")).status_code == 503
                    assert (await c.post("/api/write")).status_code == 503
                    r = await c.get("/")
                    assert r.status_code == 302 and "/login" in r.headers.get("location", "")
    _run(body())


def test_middleware_passthrough_when_allow_anonymous():
    """本地开发逃生门:显式 ALLOW_ANONYMOUS=1 时保留旧的直通行为。"""
    async def body():
        async with memory_db() as Session:
            _reset_auth_state()
            app, get_db = _build_app()
            with mock.patch.object(core_db, "AsyncSessionLocal", Session), \
                 mock.patch.object(settings, "app_api_key", ""), \
                 mock.patch.object(settings, "allow_anonymous", True):
                async with _client_ctx(Session, app, get_db) as c:
                    assert (await c.get("/api/data")).status_code == 200
                    assert (await c.post("/api/write")).status_code == 200
                    assert (await c.get("/")).status_code == 200
    _run(body())


def test_middleware_enforces_after_user_exists():
    async def body():
        async with memory_db() as Session:
            _reset_auth_state()
            await _seed_user(Session)
            app, get_db = _build_app()
            with mock.patch.object(core_db, "AsyncSessionLocal", Session), \
                 mock.patch.object(settings, "app_api_key", ""), \
                 mock.patch.object(settings, "app_secret", "test-secret"):
                async with _client_ctx(Session, app, get_db) as c:
                    # API 无凭证 → 401
                    assert (await c.get("/api/data")).status_code == 401
                    assert (await c.post("/api/write")).status_code == 401
                    # 页面 → 302 /login
                    r = await c.get("/", follow_redirects=False)
                    assert r.status_code == 302 and r.headers["location"] == "/login"
                    # 白名单直通
                    assert (await c.get("/health")).status_code == 200
    _run(body())


def test_login_flow_and_session_access():
    async def body():
        async with memory_db() as Session:
            _reset_auth_state()
            await _seed_user(Session)
            app, get_db = _build_app()
            with mock.patch.object(core_db, "AsyncSessionLocal", Session), \
                 mock.patch.object(settings, "app_api_key", "srvkey"), \
                 mock.patch.object(settings, "app_secret", "test-secret"):
                async with _client_ctx(Session, app, get_db) as c:
                    # 错密码 → 401
                    r = await c.post("/api/auth/login",
                                     json={"username": "superadmin", "password": "nope-nope"})
                    assert r.status_code == 401
                    # 正确登录 → cookie
                    r = await c.post("/api/auth/login",
                                     json={"username": "superadmin", "password": PW})
                    assert r.status_code == 200
                    assert r.json()["role"] == "super_admin"
                    sc = r.headers["set-cookie"].lower()
                    assert "httponly" in sc and "samesite=lax" in sc
                    token = _cookie_from(r)
                    hdr = {"Cookie": f"{auth_svc.SESSION_COOKIE}={token}"}
                    # session 读 + 写（写无需 X-API-Key,即便 APP_API_KEY 已配置）
                    assert (await c.get("/api/data", headers=hdr)).status_code == 200
                    assert (await c.post("/api/write", headers=hdr)).status_code == 200
                    # /api/auth/me
                    r = await c.get("/api/auth/me", headers=hdr)
                    assert r.json() == {"username": "superadmin", "role": "super_admin"}
                    # X-API-Key 通道仍可用（脚本/curl）；坏 key 不行
                    assert (await c.post("/api/write", headers={"X-API-Key": "srvkey"})).status_code == 200
                    assert (await c.post("/api/write", headers={"X-API-Key": "bad"})).status_code == 401
    _run(body())


def test_login_throttle_lockout():
    async def body():
        async with memory_db() as Session:
            _reset_auth_state()
            await _seed_user(Session)
            app, get_db = _build_app()
            with mock.patch.object(core_db, "AsyncSessionLocal", Session), \
                 mock.patch.object(settings, "app_api_key", ""), \
                 mock.patch.object(settings, "app_secret", "test-secret"):
                async with _client_ctx(Session, app, get_db) as c:
                    for _ in range(5):
                        r = await c.post("/api/auth/login",
                                         json={"username": "superadmin", "password": "x" * 8})
                        assert r.status_code == 401
                    # 第 6 次：锁定（即使密码正确）
                    r = await c.post("/api/auth/login",
                                     json={"username": "superadmin", "password": PW})
                    assert r.status_code == 429
    _run(body())


def test_change_password_invalidates_old_sessions():
    async def body():
        async with memory_db() as Session:
            _reset_auth_state()
            await _seed_user(Session)
            app, get_db = _build_app()
            with mock.patch.object(core_db, "AsyncSessionLocal", Session), \
                 mock.patch.object(settings, "app_api_key", ""), \
                 mock.patch.object(settings, "app_secret", "test-secret"):
                async with _client_ctx(Session, app, get_db) as c:
                    r = await c.post("/api/auth/login",
                                     json={"username": "superadmin", "password": PW})
                    old_token = _cookie_from(r)
                    old_hdr = {"Cookie": f"{auth_svc.SESSION_COOKIE}={old_token}"}
                    # 旧密码错 → 400
                    r = await c.post("/api/auth/change-password", headers=old_hdr,
                                     json={"old_password": "wrong-old", "new_password": "newpw12345"})
                    assert r.status_code == 400
                    # 新密码太短 → 422（pydantic min_length=8）
                    r = await c.post("/api/auth/change-password", headers=old_hdr,
                                     json={"old_password": PW, "new_password": "short"})
                    assert r.status_code == 422
                    # 正确改密 → 下发新 cookie
                    r = await c.post("/api/auth/change-password", headers=old_hdr,
                                     json={"old_password": PW, "new_password": "newpw12345"})
                    assert r.status_code == 200
                    new_token = _cookie_from(r)
                    # 旧 token 失效,新 token 可用
                    assert (await c.get("/api/data", headers=old_hdr)).status_code == 401
                    new_hdr = {"Cookie": f"{auth_svc.SESSION_COOKIE}={new_token}"}
                    assert (await c.get("/api/data", headers=new_hdr)).status_code == 200
                    # 旧密码登录失败,新密码成功
                    r = await c.post("/api/auth/login",
                                     json={"username": "superadmin", "password": PW})
                    assert r.status_code == 401
                    auth_svc._fail_log.clear()
                    r = await c.post("/api/auth/login",
                                     json={"username": "superadmin", "password": "newpw12345"})
                    assert r.status_code == 200
    _run(body())


# ── scripts/create_user.py ────────────────────────────────────────────────


def _make_file_db(tmp_path) -> str:
    from sqlalchemy import create_engine
    from app.core.database import Base
    db_path = str(tmp_path / "u.db")
    eng = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(eng)
    eng.dispose()
    return db_path


def test_create_user_script_and_reset(tmp_path, capsys):
    from scripts.create_user import main as cu_main

    db_path = _make_file_db(tmp_path)
    with mock.patch.object(sys, "argv", ["create_user.py", "--db", db_path]):
        assert cu_main() == 0
    out = capsys.readouterr().out
    assert "superadmin" in out and "密码: " in out
    password = out.split("密码: ")[1].splitlines()[0].strip()

    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT username, role, password_hash FROM app_user").fetchone()
    assert row[0] == "superadmin" and row[1] == "super_admin"
    assert auth_svc.verify_password(password, row[2])

    # 重复创建（无 --reset）→ 报错退出
    with mock.patch.object(sys, "argv", ["create_user.py", "--db", db_path]):
        assert cu_main() == 1

    # --reset → 新密码生效、password_changed_at 前移（旧 session 失效）
    old_changed = conn.execute("SELECT password_changed_at FROM app_user").fetchone()[0]
    with mock.patch.object(sys, "argv", ["create_user.py", "--db", db_path, "--reset"]):
        assert cu_main() == 0
    out2 = capsys.readouterr().out
    new_password = out2.split("密码: ")[1].splitlines()[0].strip()
    row2 = conn.execute("SELECT password_hash, password_changed_at FROM app_user").fetchone()
    assert auth_svc.verify_password(new_password, row2[0])
    assert not auth_svc.verify_password(password, row2[0])
    assert row2[1] >= old_changed
    conn.close()
