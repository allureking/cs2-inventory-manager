"""
后台任务引用保持器（v0.13.3）。

CPython 只对 asyncio task 保持**弱引用**：`asyncio.create_task(...)` 的返回值若不
保存，task 可能在完成前被 GC 掉（官方文档明确要求调用方持引用）。

本项目最具体的伤害在 dashboard 的估值缓存：`_kick_refresh` 先把
`cache["refreshing"] = True`，再 create_task 去刷新；标志位只在 `_refresh_now`
的 finally 里复位。task 一旦被回收，标志位永远为 True → 该缓存此后再也不刷新，
overview 长期显示旧值（或 0，进而持续走 snapshot 兜底口径）。

用法：
    from app.core.tasks import spawn
    spawn(some_coro())
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Coroutine

logger = logging.getLogger(__name__)

# 强引用集合：task 完成后自动移除
_BG_TASKS: set[asyncio.Task] = set()


def spawn(coro: Coroutine[Any, Any, Any], *, name: str | None = None) -> asyncio.Task:
    """创建后台 task 并持有强引用，直到其完成；异常统一记日志（不再静默丢失）。"""
    task = asyncio.create_task(coro, name=name)
    _BG_TASKS.add(task)

    def _done(t: asyncio.Task) -> None:
        _BG_TASKS.discard(t)
        if t.cancelled():
            return
        exc = t.exception()
        if exc is not None:
            logger.error("后台任务 %s 异常结束: %r", t.get_name(), exc, exc_info=exc)

    task.add_done_callback(_done)
    return task


def pending_count() -> int:
    """当前在跑的后台任务数（供 /monitoring 观测）。"""
    return len(_BG_TASKS)
