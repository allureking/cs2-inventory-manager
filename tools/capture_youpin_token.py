"""
悠悠有品 Bearer Token 抓取脚本
用法：/opt/homebrew/bin/mitmdump -s tools/capture_youpin_token.py --listen-port 8080

捕获到 Token 后会：
1. 打印到终端
2. 自动写入项目根目录的 .env 文件
"""

import re
from pathlib import Path

ENV_PATH = Path(__file__).parent.parent / ".env"

# 可能的 token header 名（按优先级排列）
_TOKEN_HEADERS = ["authorization", "token", "appauthorization", "uk"]

_captured_token = set()
_printed_hosts = set()


def response(flow):
    host = flow.request.pretty_host
    if "youpin898.com" not in host:
        return

    url = flow.request.pretty_url

    # ── 诊断模式：打印所有 youpin898.com 请求的关键 headers ──
    if host not in _printed_hosts:
        _printed_hosts.add(host)
        print(f"\n[诊断] 新 host: {host}")

    interesting = {
        k: v for k, v in flow.request.headers.items()
        if k.lower() in _TOKEN_HEADERS or k.lower() in (
            "cookie", "content-type", "x-requested-with",
            "appid", "devicesn", "deviceid", "app-version",
        )
    }
    if interesting:
        print(f"[诊断] {flow.request.method} {url[:80]}")
        for k, v in interesting.items():
            # cookie 只打印前 80 字符避免刷屏
            display_v = v[:80] + "..." if len(v) > 80 else v
            print(f"       {k}: {display_v}")

    # ── 正式捕获逻辑 ──
    token = None
    for header in _TOKEN_HEADERS:
        val = flow.request.headers.get(header, "")
        if header == "authorization":
            if val.lower().startswith("bearer "):
                token = val[7:]
                break
        elif val and len(val) > 20:  # 其他 header：有值且够长就认为是 token
            token = val
            break

    if not token or token in _captured_token:
        return

    _captured_token.add(token)

    print("\n" + "=" * 60)
    print("✅  捕获到悠悠有品 Token！")
    print(f"   来源接口: {url}")
    print(f"   Header: {header}")
    print(f"   Token 前32位: {token[:32]}...")
    print("=" * 60)

    _write_to_env(token)


def _write_to_env(token: str):
    if not ENV_PATH.exists():
        print(f"⚠️  找不到 .env 文件: {ENV_PATH}")
        return

    content = ENV_PATH.read_text(encoding="utf-8")

    if "YOUPIN_TOKEN=" in content:
        content = re.sub(r"YOUPIN_TOKEN=.*", f"YOUPIN_TOKEN={token}", content)
    else:
        content += f"\n# 悠悠有品 Token（通过抓包获取）\nYOUPIN_TOKEN={token}\n"

    ENV_PATH.write_text(content, encoding="utf-8")
    print(f"✅  已自动写入 {ENV_PATH}")
    print("   现在可以按 Ctrl+C 停止抓包。\n")
