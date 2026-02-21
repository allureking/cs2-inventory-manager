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

    database_url: str = "sqlite+aiosqlite:///./cs2_inventory.db"

    host: str = "0.0.0.0"
    port: int = 8000

    # SteamDT API
    steamdt_base_url: str = "https://open.steamdt.com"


settings = Settings()
