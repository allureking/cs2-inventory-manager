"""
用户认证路由（v0.10.0）

POST /api/auth/login            — 登录，下发 HttpOnly session cookie（限速 5次失败/5分钟）
POST /api/auth/logout           — 登出，清 cookie
GET  /api/auth/me               — 当前用户信息（需登录）
POST /api/auth/change-password  — 修改密码（需登录 + 旧密码验证；旧 session 全部失效）

中间件配合（main.py SessionAuthMiddleware）：
  login/logout 在白名单；me / change-password 由中间件先验 session，
  request.state.user = {"id", "username", "role"}。
"""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.db_models import AppUser
from app.services import auth as auth_svc

logger = logging.getLogger(__name__)
router = APIRouter()


class LoginBody(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class ChangePasswordBody(BaseModel):
    old_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=8, max_length=256)


def _client_ip(request: Request) -> str:
    # nginx 反代场景取 X-Real-IP / X-Forwarded-For 首值；直连取 socket 地址
    return (request.headers.get("X-Real-IP")
            or request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
            or (request.client.host if request.client else "unknown"))


def _set_session_cookie(resp: JSONResponse, token: str) -> None:
    resp.set_cookie(
        auth_svc.SESSION_COOKIE, token,
        max_age=auth_svc.SESSION_TTL, path="/",
        httponly=True, samesite="lax",
        secure=settings.session_cookie_secure,
    )


@router.post("/login")
async def login(body: LoginBody, request: Request, db: AsyncSession = Depends(get_db)):
    throttle_key = f"{_client_ip(request)}:{body.username}"
    if auth_svc.throttle_locked(throttle_key):
        return JSONResponse(status_code=429, content={
            "detail": "尝试次数过多，请 5 分钟后再试 / Too many attempts, retry in 5 minutes",
        })

    user = (await db.execute(
        select(AppUser).where(AppUser.username == body.username)
    )).scalar_one_or_none()

    if user is None or not auth_svc.verify_password(body.password, user.password_hash):
        auth_svc.throttle_hit(throttle_key)
        logger.warning("auth login FAILED — username=%s ip=%s", body.username, _client_ip(request))
        raise HTTPException(status_code=401, detail="用户名或密码错误 / Invalid credentials")

    auth_svc.throttle_clear(throttle_key)
    token = auth_svc.issue_token(user.id)
    resp = JSONResponse({"ok": True, "username": user.username, "role": user.role})
    _set_session_cookie(resp, token)
    logger.info("auth login OK — username=%s ip=%s", user.username, _client_ip(request))
    return resp


@router.post("/logout")
async def logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(auth_svc.SESSION_COOKIE, path="/")
    return resp


@router.get("/me")
async def me(request: Request):
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return {"username": user["username"], "role": user["role"]}


@router.post("/change-password")
async def change_password(body: ChangePasswordBody, request: Request,
                          db: AsyncSession = Depends(get_db)):
    state_user = getattr(request.state, "user", None)
    if not state_user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if state_user.get("via") == "api_key":
        raise HTTPException(status_code=403, detail="API key 通道不能改密码，请登录后操作")

    user = (await db.execute(
        select(AppUser).where(AppUser.id == state_user["id"])
    )).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if not auth_svc.verify_password(body.old_password, user.password_hash):
        raise HTTPException(status_code=400, detail="旧密码错误 / Wrong current password")

    now = time.time()
    user.password_hash = auth_svc.hash_password(body.new_password)
    user.password_changed_at = now
    await db.commit()
    logger.info("auth password changed — username=%s", user.username)

    # 旧 token 全部失效；给当前会话签发新 token（iat 必须 ≥ changed_at）
    resp = JSONResponse({"ok": True})
    _set_session_cookie(resp, auth_svc.issue_token(user.id, now=now + 1))
    return resp
