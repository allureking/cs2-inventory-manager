"""通用工具函数"""

from __future__ import annotations

from typing import Optional


def parse_money(value: Optional[object]) -> float:
    """
    解析金额字符串为 float，剥离 '¥' 前缀、千分位逗号与空白。

    悠悠 API 的估值字段有时带 '¥' 前缀有时不带（如 '¥425194.14' / '425194.14'），
    tracker 与 collector 共用本函数，避免同一解析逻辑写两遍且不一致。

    None / 空串 → 0.0；无法解析的串抛 ValueError（调用方已有 warning+fallback 处理）。
    """
    if value is None:
        return 0.0
    s = str(value).strip().replace("¥", "").replace(",", "")
    if not s:
        return 0.0
    return float(s)
