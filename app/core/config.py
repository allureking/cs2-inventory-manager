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


settings = Settings()
