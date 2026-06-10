"""
APIKeyMiddleware characterization（main.py）。

钉住的行为：
  - app_api_key 未配置("") → 中间件完全直通
  - 配置后：GET/HEAD/OPTIONS 直通；非 /api/ 路径直通
  - /api/ 写请求：无凭证 → 401；Authorization: Bearer <key> 通过；
    X-API-Key: <key> 通过（nginx Basic Auth 占用 Authorization 的场景）
  - 错误的 key（两种头）→ 401
"""

from __future__ import annotations

import asyncio

import httpx
from fastapi import FastAPI

from app.core.config import settings


def _build_app():
    from main import APIKeyMiddleware

    app = FastAPI()
    app.add_middleware(APIKeyMiddleware)

    @app.get("/api/ping")
    async def ping_get():
        return {"ok": True}

    @app.post("/api/ping")
    async def ping_post():
        return {"ok": True}

    @app.post("/outside")
    async def outside_post():
        return {"ok": True}

    return app


def _request(method: str, path: str, headers: dict | None = None) -> int:
    async def _run() -> int:
        transport = httpx.ASGITransport(app=_build_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.request(method, path, headers=headers)
            return resp.status_code

    return asyncio.run(_run())


def test_no_key_configured_passes_writes(monkeypatch):
    monkeypatch.setattr(settings, "app_api_key", "")
    assert _request("POST", "/api/ping") == 200


def test_get_passes_without_key(monkeypatch):
    monkeypatch.setattr(settings, "app_api_key", "sek-123")
    assert _request("GET", "/api/ping") == 200


def test_non_api_path_passes_without_key(monkeypatch):
    monkeypatch.setattr(settings, "app_api_key", "sek-123")
    assert _request("POST", "/outside") == 200


def test_api_write_without_key_rejected(monkeypatch):
    monkeypatch.setattr(settings, "app_api_key", "sek-123")
    assert _request("POST", "/api/ping") == 401


def test_bearer_token_accepted(monkeypatch):
    monkeypatch.setattr(settings, "app_api_key", "sek-123")
    assert _request("POST", "/api/ping", {"Authorization": "Bearer sek-123"}) == 200


def test_x_api_key_accepted(monkeypatch):
    monkeypatch.setattr(settings, "app_api_key", "sek-123")
    assert _request("POST", "/api/ping", {"X-API-Key": "sek-123"}) == 200


def test_x_api_key_coexists_with_basic_auth_header(monkeypatch):
    """nginx Basic Auth 场景：Authorization 被 Basic 占用，X-API-Key 仍应放行。"""
    monkeypatch.setattr(settings, "app_api_key", "sek-123")
    headers = {"Authorization": "Basic dXNlcjpwYXNz", "X-API-Key": "sek-123"}
    assert _request("POST", "/api/ping", headers) == 200


def test_wrong_keys_rejected(monkeypatch):
    monkeypatch.setattr(settings, "app_api_key", "sek-123")
    assert _request("POST", "/api/ping", {"Authorization": "Bearer wrong"}) == 401
    assert _request("POST", "/api/ping", {"X-API-Key": "wrong"}) == 401
