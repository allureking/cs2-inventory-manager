"""
悠悠有品 手机号 + 短信验证码 登录脚本
用法：python tools/youpin_login.py

成功后自动将 YOUPIN_TOKEN 写入项目根目录的 .env 文件。

依赖：pip install pycryptodome requests
"""

import base64
import json
import random
import re
import string
import sys
import uuid
from pathlib import Path

import requests
from Crypto.Cipher import AES, PKCS1_v1_5
from Crypto.PublicKey import RSA
from Crypto.Util.Padding import pad, unpad

BASE_URL = "https://api.youpin898.com"
ENV_PATH = Path(__file__).parent.parent / ".env"

_RSA_PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAv9BDdhCDahZNFuJeesx3
gzoQfD7pE0AeWiNBZlc21ph6kU9zd58X/1warV3C1VIX0vMAmhOcj5u86i+L2Lb2
V68dX2Nb70MIDeW6Ibe8d0nF8D30tPsM7kaAyvxkY6ECM6RHGNhV4RrzkHmf5DeR
9bybQGE0A9jcjuxszD1wsW/n19eeom7MroHqlRorp5LLNR8bSbmhTw6M/RQ/Fm3l
KjKcvs1QNVyBNimrbD+ZVPE/KHSZLQ1jdF6tppvFnGxgJU9NFmxGFU0hx6cZiQHk
hOQfGDFkElxgtj8gFJ1narTwYbvfe5nGSiznv/EUJSjTHxzX1TEkex0+5j4vSANt
1QIDAQAB
-----END PUBLIC KEY-----"""


def _rand_str(length: int) -> str:
    return "".join(random.choices(string.ascii_letters + string.digits, k=length))


# ── RSA+AES uk 生成（与 Steamauto 完全一致）──────────────────────────────

class _ApiCrypt:
    def __init__(self, aes_key: str):
        self.aes_key = aes_key.encode("utf-8")

    def get_encrypted_aes_key(self) -> str:
        pub = RSA.import_key(_RSA_PUBLIC_KEY)
        cipher = PKCS1_v1_5.new(pub)
        return base64.b64encode(cipher.encrypt(self.aes_key)).decode("utf-8")

    def encrypt(self, content: str) -> str:
        cipher = AES.new(self.aes_key, AES.MODE_ECB)
        return base64.b64encode(
            cipher.encrypt(pad(content.encode("utf-8"), AES.block_size))
        ).decode("utf-8")

    def decrypt(self, encrypted_b64: bytes) -> str:
        cipher = AES.new(self.aes_key, AES.MODE_ECB)
        return unpad(cipher.decrypt(base64.b64decode(encrypted_b64)), AES.block_size).decode("utf-8")


def _get_uk() -> str:
    crypt = _ApiCrypt(_rand_str(16))
    payload = json.dumps({"iud": str(uuid.uuid4())})
    resp = requests.post(
        f"{BASE_URL}/api/deviceW2",
        json={
            "encryptedData": crypt.encrypt(payload),
            "encryptedAesKey": crypt.get_encrypted_aes_key(),
        },
        timeout=15,
    )
    resp.raise_for_status()
    return json.loads(crypt.decrypt(resp.content))["u"]


# ── Headers ────────────────────────────────────────────────────────────────

def _build_headers(device_token: str, uk: str = "") -> dict:
    if not uk:
        uk = _rand_str(65)   # fallback，正常流程会传入真实 uk
    return {
        "uk": uk,
        "authorization": "Bearer ",
        "content-type": "application/json; charset=utf-8",
        "user-agent": "okhttp/3.14.9",
        "App-Version": "5.42.0",
        "AppType": "4",
        "deviceType": "1",
        "package-type": "uuyp",
        "DeviceToken": device_token,
        "DeviceId": device_token,
        "platform": "android",
        "accept-encoding": "gzip",
        "Gameid": "730",
        "Device-Info": json.dumps(
            {
                "deviceId": device_token,
                "deviceType": device_token,
                "hasSteamApp": 1,
                "requestTag": _rand_str(32).upper(),
                "systemName": "Android",
                "systemVersion": "15",
            },
            ensure_ascii=False,
        ),
    }


# ── API 调用 ────────────────────────────────────────────────────────────────

def send_sms(phone: str, session_id: str, uk: str) -> dict:
    headers = _build_headers(session_id, uk)
    payload = {"Area": 86, "Mobile": phone, "Sessionid": session_id, "Code": ""}
    resp = requests.post(
        f"{BASE_URL}/api/user/Auth/SendSignInSmsCode",
        json=payload,
        headers=headers,
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def sms_login(phone: str, code: str, session_id: str, uk: str) -> dict:
    headers = _build_headers(session_id, uk)
    payload = {
        "Area": 86,
        "Code": code,
        "DeviceName": session_id,
        "Sessionid": session_id,
        "Mobile": phone,
    }
    resp = requests.post(
        f"{BASE_URL}/api/user/Auth/SmsSignIn",
        json=payload,
        headers=headers,
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


# ── .env 写入 ───────────────────────────────────────────────────────────────

def write_to_env(token: str) -> None:
    if not ENV_PATH.exists():
        print(f"⚠️  找不到 .env 文件: {ENV_PATH}")
        return
    content = ENV_PATH.read_text(encoding="utf-8")
    if "YOUPIN_TOKEN=" in content:
        content = re.sub(r"YOUPIN_TOKEN=.*", f"YOUPIN_TOKEN={token}", content)
    else:
        content += f"\n# 悠悠有品 Bearer Token\nYOUPIN_TOKEN={token}\n"
    ENV_PATH.write_text(content, encoding="utf-8")
    print(f"✅  Token 已写入 {ENV_PATH}")


# ── 主流程 ──────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 50)
    print("  悠悠有品 短信登录")
    print("=" * 50)

    phone = input("请输入手机号（无需加区号）: ").strip()
    if not phone:
        print("手机号不能为空")
        sys.exit(1)

    session_id = _rand_str(32)

    print("正在获取设备凭证（uk）...")
    try:
        uk = _get_uk()
        print(f"✅  uk 获取成功（前8位: {uk[:8]}...）")
    except Exception as e:
        print(f"⚠️  uk 获取失败，使用随机值: {e}")
        uk = _rand_str(65)

    print("正在发送短信验证码...")
    try:
        result = send_sms(phone, session_id, uk)
    except Exception as e:
        print(f"❌ 发送失败: {e}")
        sys.exit(1)

    print(f"服务器返回: Code={result.get('Code')} Msg={result.get('Msg')}")
    if result.get("Code") != 0:
        print("❌ 短信发送失败")
        sys.exit(1)

    print("✅ 短信已发送")
    code = input("请输入收到的验证码: ").strip()
    if not code:
        print("验证码不能为空")
        sys.exit(1)

    print("正在登录...")
    try:
        login_result = sms_login(phone, code, session_id, uk)
    except Exception as e:
        print(f"❌ 登录请求失败: {e}")
        sys.exit(1)

    print(f"服务器返回: Code={login_result.get('Code')} Msg={login_result.get('Msg')}")

    if login_result.get("Code") != 0:
        print(f"❌ 登录失败: {login_result.get('Msg')}")
        sys.exit(1)

    token = (login_result.get("Data") or {}).get("Token")
    if not token:
        print("❌ 登录成功但未找到 Token，原始响应:")
        print(json.dumps(login_result, ensure_ascii=False, indent=2))
        sys.exit(1)

    nickname = (login_result.get("Data") or {}).get("NickName", "")
    print(f"\n✅  登录成功！昵称: {nickname}")
    print(f"   Token 前32位: {token[:32]}...")

    write_to_env(token)
    print("\n现在可以继续运行项目了。")


if __name__ == "__main__":
    main()
