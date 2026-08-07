from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="SCANNER_")

    database_url: str = "sqlite:///../data/scanner.db"
    html_storage_root: Path = Path("../data/html")
    ai_document_storage_root: Path = Path("../data/ai-documents")
    rendered_artifact_storage_root: Path = Path("../data/rendered")
    crawler_user_agent: str = "WebsiteScanner/0.1"
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://127.0.0.1:5173", "http://localhost:5173"]
    )
    job_worker_concurrency: int = 1
    job_poll_interval_seconds: float = 1.0
    job_worker_heartbeat_seconds: float = 5.0
    job_lease_seconds: float = 30.0
    job_worker_offline_seconds: float = 20.0
    job_graceful_shutdown_seconds: float = 10.0
    job_progress_min_interval_seconds: float = 1.0
    job_event_limit_per_job: int = 500
    sqlite_busy_timeout_ms: int = 5000

    @model_validator(mode="after")
    def validate_job_settings(self) -> "Settings":
        if self.job_worker_concurrency < 1:
            raise ValueError("JOB_WORKER_CONCURRENCY must be at least 1.")
        if self.job_poll_interval_seconds <= 0:
            raise ValueError("JOB_POLL_INTERVAL_SECONDS must be positive.")
        if self.job_worker_heartbeat_seconds <= 0:
            raise ValueError("JOB_WORKER_HEARTBEAT_SECONDS must be positive.")
        if self.job_lease_seconds <= self.job_worker_heartbeat_seconds:
            raise ValueError("JOB_LEASE_SECONDS must be greater than worker heartbeat seconds.")
        if self.job_worker_offline_seconds <= self.job_worker_heartbeat_seconds:
            raise ValueError(
                "JOB_WORKER_OFFLINE_SECONDS must be greater than worker heartbeat seconds."
            )
        if self.job_graceful_shutdown_seconds <= 0:
            raise ValueError("JOB_GRACEFUL_SHUTDOWN_SECONDS must be positive.")
        if self.job_progress_min_interval_seconds < 0:
            raise ValueError("JOB_PROGRESS_MIN_INTERVAL_SECONDS cannot be negative.")
        if self.job_event_limit_per_job < 1:
            raise ValueError("JOB_EVENT_LIMIT_PER_JOB must be positive.")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
