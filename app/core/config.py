from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    steamdt_api_key: str = ""
    steam_api_key: str = ""
    steam_steam_id: str = ""

    # Steam 登录 Cookie（用于访问完整库存，含7天保护期物品）
    # 获取方式见 .env.example
    steam_login_secure: str = ""
    steam_session_id: str = ""

    database_url: str = "sqlite+aiosqlite:///./cs2_inventory.db"

    host: str = "0.0.0.0"
    port: int = 8000

    # SteamDT API
    steamdt_base_url: str = "https://open.steamdt.com"

    # CSQAQ 数据 API
    csqaq_api_key: str = ""
    csqaq_base_url: str = "https://api.csqaq.com/api/v1"

    # 悠悠有品
    youpin_token: str = ""
    youpin_device_id: str = ""
    youpin_app_version: str = "5.28.3"  # 可在 .env 中覆盖，如 API 要求更新版本

    # API 访问密钥 — 设置后所有修改类端点需要 Bearer token
    app_api_key: str = ""

    # 用户系统（v0.10.0）：session token 签名密钥（openssl rand -hex 32）
    # 未配置时进程内随机生成，重启后所有登录失效
    app_secret: str = ""
    # session cookie 的 Secure 标记（生产 https 保持 True；本地 http 调试可关）
    session_cookie_secure: bool = True

    # 采价平台白名单 — 只保存这些平台的价格快照，逗号分隔
    # 可选: YOUPIN,BUFF,STEAM,C5,HALOSKINS,SKINPORT,DMARKET,WAXPEER,CSMONEY
    price_platforms: str = "YOUPIN,BUFF,STEAM"


settings = Settings()
