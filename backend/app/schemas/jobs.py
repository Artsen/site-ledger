from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class JobRead(BaseModel):
    id: int
    job_type: str
    status: str
    presentation_status: str
    priority: int
    scan_id: int | None
    source_refresh_id: int | None
    scan_comparison_id: int | None
    performance_run_id: int | None
    website_property_id: int | None
    dedupe_key: str
    payload_json: dict[str, Any]
    progress_version: int
    progress_json: dict[str, Any]
    current_operation: str | None
    progress_current: int | None
    progress_total: int | None
    progress_unit: str | None
    result_json: dict[str, Any] | None
    created_at: datetime
    available_at: datetime
    claimed_at: datetime | None
    started_at: datetime | None
    heartbeat_at: datetime | None
    lease_expires_at: datetime | None
    finished_at: datetime | None
    worker_id: str | None
    attempt_count: int
    max_attempts: int
    cancellation_requested_at: datetime | None
    cancelled_at: datetime | None
    error_type: str | None
    error_message: str | None
    last_error_at: datetime | None

    model_config = {"from_attributes": True}


class JobList(BaseModel):
    items: list[JobRead]
    total: int
    limit: int
    offset: int


class JobEventRead(BaseModel):
    id: int
    job_id: int
    event_type: str
    level: str
    message: str
    data_json: dict[str, Any]
    created_at: datetime

    model_config = {"from_attributes": True}


class JobEventList(BaseModel):
    items: list[JobEventRead]
    total: int
    limit: int
    offset: int


class WorkerHealth(BaseModel):
    online_workers: int
    total_concurrency: int
    last_worker_heartbeat: datetime | None
    queued_work_has_worker: bool
    offline_threshold_seconds: float
    worker_capabilities: list[dict[str, Any]] = Field(default_factory=list)


class JobSummary(BaseModel):
    id: int
    job_type: str
    status: str
    presentation_status: str
    current_operation: str | None = None
    progress_current: int | None = None
    progress_total: int | None = None
    progress_unit: str | None = None
    cancellation_requested_at: datetime | None = None
    worker_id: str | None = None
    error_type: str | None = None
    error_message: str | None = None

    model_config = {"from_attributes": True}


class EnqueuedJobResponse(BaseModel):
    item: dict[str, Any]
    job: JobSummary


class ProgressPayload(BaseModel):
    version: int = 1
    phase: str
    current_operation: str | None = None
    current: int | None = None
    total: int | None = None
    unit: str | None = None
    counters: dict[str, int] = Field(default_factory=dict)
    message: str | None = None
    updated_at: datetime
