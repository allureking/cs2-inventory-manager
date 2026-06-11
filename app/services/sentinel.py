"""
凭证哨兵（v0.13.0,架构审查提案6①）

问题背景:悠悠 token 过期时全链路静默 fallback(估值→0→缓存兜底),
用户可能数天后才从图表异常发现数据停更。本模块在每日任务链头部 + 服务启动时
主动探测凭证,失效立即告警:

  - 应用内:写入 quant_alert(severity=critical),预警中心红点可见——零依赖必达
  - 外部推送(可选,.env 配置即生效):
      SERVERCHAN_KEY            → Server酱 (https://sct.ftqq.com)
      TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID → Telegram Bot
  - 日志 ERROR 必记

去重:同渠道存在未读 credential 告警时不再重复写(避免每日刷屏);
凭证恢复后自动把该渠道未读告警标记已读(自动愈合)。
"""

from __future__ import annotations

import logging

import httpx
from sqlalchemy import select, update

from app.core.config import settings
from app.models.db_models import QuantAlert

logger = logging.getLogger(__name__)

# quant_alert.market_hash_name 非空,凭证告警用渠道标识占位
_CHANNEL_KEY = "__credential__youpin"
_ALERT_TYPE = "credential"


async def _push_external(title: str, body: str) -> None:
    """外部推送(渠道未配置时静默跳过;推送失败不影响应用内告警)。"""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            if settings.serverchan_key:
                await client.post(
                    f"https://sctapi.ftqq.com/{settings.serverchan_key}.send",
                    data={"title": title, "desp": body},
                )
            if settings.telegram_bot_token and settings.telegram_chat_id:
                await client.post(
                    f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
                    json={"chat_id": settings.telegram_chat_id, "text": f"{title}\n{body}"},
                )
    except Exception as e:
        logger.warning("sentinel external push failed: %s", e)


async def run_credential_sentinel() -> dict:
    """探测悠悠 token;失效 → 告警(带去重),恢复 → 自动已读。返回探测结果供测试/手动调用。"""
    from app.core.database import AsyncSessionLocal
    from app.services.youpin import check_token_status

    status = await check_token_status()
    valid = bool(status.get("valid"))

    async with AsyncSessionLocal() as db:
        unread_q = select(QuantAlert).where(
            QuantAlert.alert_type == _ALERT_TYPE,
            QuantAlert.market_hash_name == _CHANNEL_KEY,
            QuantAlert.is_read == False,  # noqa: E712
        )
        existing = (await db.execute(unread_q)).scalars().first()

        if valid:
            if existing:
                # 凭证恢复:自动愈合,未读告警转已读
                await db.execute(
                    update(QuantAlert)
                    .where(
                        QuantAlert.alert_type == _ALERT_TYPE,
                        QuantAlert.market_hash_name == _CHANNEL_KEY,
                        QuantAlert.is_read == False,  # noqa: E712
                    )
                    .values(is_read=True)
                )
                await db.commit()
                logger.info("sentinel: 悠悠 token 已恢复,凭证告警自动愈合")
            return {"youpin_valid": True, "alerted": False}

        # 失效:日志必记
        err = status.get("error") or "unknown"
        logger.error("sentinel: 悠悠 token 失效 — %s(估值/导入/上架已不可用,数据将停更)", err)

        if existing:
            return {"youpin_valid": False, "alerted": False, "deduped": True}

        title = "悠悠有品 Token 失效"
        detail = f"{err}。估值/租赁导入/上架操作已不可用,daily_tracker 将静默停更。请重新登录或更新 .env 的 YOUPIN_TOKEN。"
        db.add(QuantAlert(
            market_hash_name=_CHANNEL_KEY,
            alert_type=_ALERT_TYPE,
            severity="critical",
            title=title,
            detail=detail,
        ))
        await db.commit()
        await _push_external(f"[CS2] {title}", detail)
        return {"youpin_valid": False, "alerted": True}
