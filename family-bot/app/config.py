from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    bot_token: str = ""
    public_url: str = "http://localhost:8080"
    database_url: str = "sqlite+aiosqlite:///./family.db"
    default_currency: str = "UAH"

    bot_mode: str = "polling"  # polling | webhook | off
    webhook_secret: str = "change-me"

    host: str = "0.0.0.0"
    port: int = 8080

    dev_tg_id: int | None = None

    @property
    def base_url(self) -> str:
        return self.public_url.rstrip("/")

    @property
    def webapp_url(self) -> str:
        return f"{self.base_url}/app/"

    def share_url(self, token: str) -> str:
        return f"{self.base_url}/s/{token}"

    def invite_url(self, code: str, bot_username: str) -> str:
        return f"https://t.me/{bot_username}?start=join_{code}"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
