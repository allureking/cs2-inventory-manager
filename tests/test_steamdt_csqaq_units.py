"""
steamdt / csqaq 的纯辅助函数测试（无网络）。
（两模块的 API 客户端 fetch_* / sync_* 依赖真实 SteamDT/CSQAQ,见 REPORT §2。）

  steamdt: _auth_headers / _snapshot_minute / _today_str / _check_response / _allowed_platforms
  csqaq:   _headers
"""

import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from app.core.config import settings
from app.services import steamdt
from app.services.steamdt import (
    _auth_headers,
    _snapshot_minute,
    _today_str,
    _check_response,
    _allowed_platforms,
)
from app.services import csqaq
from app.schemas.steamdt import SteamDTResponse


# ── steamdt 纯 helper ──────────────────────────────────────────────────────


def test_auth_headers():
    h = _auth_headers()
    assert h["Authorization"].startswith("Bearer ")
    assert h["Accept"] == "application/json"


def test_snapshot_minute_format():
    s = _snapshot_minute()
    assert re.fullmatch(r"\d{12}", s)
    assert s.startswith(datetime.now(timezone.utc).strftime("%Y%m%d"))


def test_today_str_format():
    assert re.fullmatch(r"\d{8}", _today_str())


def test_check_response_success_ok():
    _check_response(SteamDTResponse(success=True))  # 不抛


def test_check_response_failure_raises():
    with pytest.raises(ValueError):
        _check_response(SteamDTResponse(success=False, errorCode=500, errorMsg="boom"))


def test_allowed_platforms_default(monkeypatch):
    monkeypatch.setattr(settings, "price_platforms", "YOUPIN,BUFF,STEAM")
    assert _allowed_platforms() == {"YOUPIN", "BUFF", "STEAM"}


def test_allowed_platforms_normalizes_and_trims(monkeypatch):
    monkeypatch.setattr(settings, "price_platforms", " buff , c5 ")
    assert _allowed_platforms() == {"BUFF", "C5"}


def test_allowed_platforms_empty_returns_none(monkeypatch):
    monkeypatch.setattr(settings, "price_platforms", "")
    assert _allowed_platforms() is None


# ── csqaq 纯 helper ────────────────────────────────────────────────────────


def test_csqaq_headers():
    h = csqaq._headers()
    assert "ApiToken" in h
    assert h["Content-Type"] == "application/json"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
