"""
应用登录认证服务（v0.10.0 用户系统）

设计（零新依赖，全部标准库）：
  - 密码哈希：PBKDF2-HMAC-SHA256，600k 迭代，16 字节随机盐，
    存储格式 "pbkdf2_sha256$<iters>$<salt_hex>$<hash_hex>"。
  - Session token：HMAC-SHA256 签名的无状态 token，
    格式 "<user_id>.<iat>.<exp>.<sig_hex>"，HttpOnly cookie 下发。
    改密/重置后 password_changed_at 更新，旧 token（iat < 该值）全部失效。
  - 登录限速：内存版按 IP+用户名 计数（workers=1 部署，无需跨进程共享），
    5 次失败锁 5 分钟，防爆破。
  - 签名密钥：settings.app_secret（.env 配置）；未配置时进程内随机生成
    （重启后所有 session 失效）并打 warning。
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import time
from typing import Optional

from sqlalchemy import func, select

logger = logging.getLogger(__name__)

SESSION_COOKIE = "cs2_session"
SESSION_TTL = 30 * 24 * 3600  # 30 天
_PBKDF2_ITERATIONS = 600_000

# 登录限速
_MAX_FAILS = 5
_LOCK_WINDOW = 300  # 秒
_fail_log: dict[str, list[float]] = {}

# "系统是否已初始化(存在用户)"缓存：种子前中间件直通,避免每请求查库
_USERS_EXIST_TTL = 30.0
_users_exist_cache: Optional[tuple[float, bool]] = None

_ephemeral_secret: Optional[str] = None


def _get_secret() -> str:
    from app.core.config import settings

    if settings.app_secret:
        return settings.app_secret
    global _ephemeral_secret
    if _ephemeral_secret is None:
        _ephemeral_secret = secrets.token_hex(32)
        logger.warning("APP_SECRET 未配置，使用进程内随机密钥（重启后所有登录失效）")
    return _ephemeral_secret


# ── 密码哈希 ──────────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(),
                                 bytes.fromhex(salt_hex), int(iters))
        return hmac.compare_digest(dk.hex(), hash_hex)
    except (ValueError, AttributeError):
        return False


# ── Session token ─────────────────────────────────────────────────────────

def _sign(payload: str) -> str:
    return hmac.new(_get_secret().encode(), payload.encode(), hashlib.sha256).hexdigest()


def issue_token(user_id: int, now: Optional[float] = None) -> str:
    iat = int(now if now is not None else time.time())
    exp = iat + SESSION_TTL
    payload = f"{user_id}.{iat}.{exp}"
    return f"{payload}.{_sign(payload)}"


def parse_token(token: str) -> Optional[tuple[int, int]]:
    """返回 (user_id, iat)；签名/格式/过期不合法时返回 None。"""
    try:
        uid_s, iat_s, exp_s, sig = token.split(".")
        payload = f"{uid_s}.{iat_s}.{exp_s}"
        if not hmac.compare_digest(_sign(payload), sig):
            return None
        if int(exp_s) < time.time():
            return None
        return int(uid_s), int(iat_s)
    except (ValueError, AttributeError):
        return None


async def verify_session(token: str) -> Optional[dict]:
    """校验 token 并返回用户信息 dict；无效返回 None。"""
    parsed = parse_token(token)
    if not parsed:
        return None
    user_id, iat = parsed
    from app.core.database import AsyncSessionLocal
    from app.models.db_models import AppUser

    async with AsyncSessionLocal() as db:
        user = (await db.execute(
            select(AppUser).where(AppUser.id == user_id)
        )).scalar_one_or_none()
    if user is None:
        return None
    # 改密/重置后旧 token 全部失效
    if iat < (user.password_changed_at or 0.0):
        return None
    return {"id": user.id, "username": user.username, "role": user.role}


async def users_exist() -> bool:
    """系统里是否已有用户（带 30s 缓存）。种子前为 False → 认证中间件直通。"""
    global _users_exist_cache
    now = time.time()
    if _users_exist_cache and now - _users_exist_cache[0] < _USERS_EXIST_TTL:
        return _users_exist_cache[1]
    from app.core.database import AsyncSessionLocal
    from app.models.db_models import AppUser

    async with AsyncSessionLocal() as db:
        count = (await db.execute(select(func.count(AppUser.id)))).scalar() or 0
    exists = count > 0
    # 一旦有用户即恒为 True,不再过期（用户只增不删归零;避免缓存抖动导致门禁闪开）
    _users_exist_cache = (now if not exists else float("inf"), exists)
    return exists


def reset_users_exist_cache() -> None:
    """种子/测试后强制重查。"""
    global _users_exist_cache
    _users_exist_cache = None


# ── 登录限速 ──────────────────────────────────────────────────────────────

def throttle_locked(key: str) -> bool:
    now = time.time()
    fails = [t for t in _fail_log.get(key, []) if now - t < _LOCK_WINDOW]
    _fail_log[key] = fails
    return len(fails) >= _MAX_FAILS


def throttle_hit(key: str) -> None:
    _fail_log.setdefault(key, []).append(time.time())


def throttle_clear(key: str) -> None:
    _fail_log.pop(key, None)
