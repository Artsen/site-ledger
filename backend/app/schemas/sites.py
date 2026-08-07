from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator

from app.schemas.scans import ScopeConfigPayload
from app.services.site_classifications import normalize_classification


def normalize_locale(value: str | None) -> str | None:
    if value in {None, ""}:
        return None
    parts = value.split("-")
    if len(parts) != 2 or len(parts[0]) != 2 or len(parts[1]) != 2:
        raise ValueError("Locale must look like en-US.")
    language, region = parts
    if not (language.isalpha() and region.isalpha()):
        raise ValueError("Locale must look like en-US.")
    return f"{language.lower()}-{region.upper()}"


def normalize_timezone(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    value = value.strip()
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("Time zone must be a valid IANA identifier.") from exc
    return value


class WebsitePropertyBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    base_url: str = Field(min_length=1, max_length=2048)
    description: str | None = Field(default=None, max_length=5000)
    group_key: str = "Other"
    locale: str | None = Field(default=None, max_length=32)
    platform_key: str = "Other"
    ownership_key: str = "Unknown"
    display_timezone: str | None = Field(default=None, max_length=255)
    scope_config: ScopeConfigPayload = Field(default_factory=ScopeConfigPayload)
    is_active: bool = True

    @field_validator("group_key")
    @classmethod
    def validate_group_key(cls, value: str) -> str:
        return normalize_classification(value, fallback="Other")

    @field_validator("platform_key")
    @classmethod
    def validate_platform_key(cls, value: str) -> str:
        return normalize_classification(value, fallback="Other")

    @field_validator("ownership_key")
    @classmethod
    def validate_ownership_key(cls, value: str) -> str:
        return normalize_classification(value, fallback="Unknown")

    @field_validator("locale")
    @classmethod
    def validate_locale(cls, value: str | None) -> str | None:
        return normalize_locale(value)

    @field_validator("display_timezone")
    @classmethod
    def validate_display_timezone(cls, value: str | None) -> str | None:
        return normalize_timezone(value)


class WebsitePropertyCreate(WebsitePropertyBase):
    pass


class WebsitePropertyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    base_url: str | None = Field(default=None, min_length=1, max_length=2048)
    description: str | None = Field(default=None, max_length=5000)
    group_key: str | None = None
    locale: str | None = Field(default=None, max_length=32)
    platform_key: str | None = None
    ownership_key: str | None = None
    display_timezone: str | None = Field(default=None, max_length=255)
    scope_config: ScopeConfigPayload | None = None
    is_active: bool | None = None

    @field_validator("group_key")
    @classmethod
    def validate_group_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_classification(value, fallback="Other")

    @field_validator("platform_key")
    @classmethod
    def validate_platform_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_classification(value, fallback="Other")

    @field_validator("ownership_key")
    @classmethod
    def validate_ownership_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_classification(value, fallback="Unknown")

    @field_validator("locale")
    @classmethod
    def validate_locale(cls, value: str | None) -> str | None:
        return normalize_locale(value)

    @field_validator("display_timezone")
    @classmethod
    def validate_display_timezone(cls, value: str | None) -> str | None:
        return normalize_timezone(value)


class ScanSummary(BaseModel):
    id: int
    website_property_id: int | None = None
    website_property_name: str | None = None
    website_property_base_url: str | None = None
    website_property_display_timezone: str | None = None
    starting_url: str
    status: str
    scope_config: dict[str, Any]
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    discovered_count: int
    fetched_count: int
    failed_count: int
    skipped_count: int
    queued_count: int
    stop_reason: str | None
    fatal_error_message: str | None


class WebsitePropertyRead(BaseModel):
    id: int
    name: str
    base_url: str
    normalized_base_url: str
    description: str | None
    group_key: str
    locale: str | None
    platform_key: str
    ownership_key: str
    display_timezone: str | None
    scope_config: dict[str, Any]
    is_active: bool
    created_at: datetime
    updated_at: datetime
    total_scan_count: int = 0
    latest_scan: ScanSummary | None = None
    recent_scans: list[ScanSummary] = Field(default_factory=list)
    note_count: int = 0
    category_count: int = 0

    model_config = {"from_attributes": True}


class WebsitePropertyListItem(BaseModel):
    id: int
    name: str
    base_url: str
    normalized_base_url: str
    description: str | None
    group_key: str
    locale: str | None
    platform_key: str
    ownership_key: str
    display_timezone: str | None
    scope_config: dict[str, Any]
    is_active: bool
    created_at: datetime
    updated_at: datetime
    total_scan_count: int
    latest_scan_id: int | None = None
    latest_scan_status: str | None = None
    latest_scan_date: datetime | None = None
    latest_scan_discovered_count: int | None = None
    latest_scan_failed_count: int | None = None


class WebsitePropertyList(BaseModel):
    items: list[WebsitePropertyListItem]
    total: int
    limit: int
    offset: int


class SiteScans(BaseModel):
    items: list[ScanSummary]
    total: int
    limit: int
    offset: int


class SiteScanCreate(BaseModel):
    scope_config: ScopeConfigPayload
    include_inventory: bool = False
    source_ids: list[int] = Field(default_factory=list)


class SiteDeleteResult(BaseModel):
    deleted_site_id: int
