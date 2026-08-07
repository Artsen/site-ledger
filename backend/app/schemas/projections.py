from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class ProjectionMetadata(BaseModel):
    projection_source: Literal["materialized", "dynamic"]
    projection_version: str
    projection_build_id: int | None = None
    projection_status: str


class ScanProjectionBuildRead(BaseModel):
    id: int
    scan_id: int
    projection_version: str
    algorithm_identity: str
    status: str
    started_at: datetime | None
    finished_at: datetime | None
    failed_at: datetime | None
    error_type: str | None
    error_message: str | None
    page_count: int
    resource_count: int
    link_edge_count: int
    graph_node_count: int
    graph_edge_count: int
    rendered_page_count: int
    source_snapshot_count: int
    source_link_occurrence_count: int
    source_resource_reference_count: int
    build_duration_ms: int | None
    checksum_sha256: str | None
    validation_json: dict[str, object]
    created_at: datetime

    model_config = {"from_attributes": True}


class ScanProjectionStatusRead(BaseModel):
    scan_id: int
    scan_status: str
    expected_version: str
    projection_source: Literal["materialized", "dynamic"]
    projection_status: str
    current_build: ScanProjectionBuildRead | None = None
    active_build: ScanProjectionBuildRead | None = None
    latest_build: ScanProjectionBuildRead | None = None
    can_build: bool
    can_rebuild: bool
