from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="SCANNER_")

    database_url: str = "sqlite:///../data/scanner.db"
    html_storage_root: Path = Path("../data/html")
    crawler_user_agent: str = "WebsiteScanner/0.1"
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://127.0.0.1:5173", "http://localhost:5173"]
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
