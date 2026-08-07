from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

WORKFLOW_STATUSES = {
    "unreviewed",
    "needs_review",
    "approved",
    "updating",
    "deprecated",
    "archived",
}
CATEGORY_COLOR_KEYS = {
    "stone",
    "red",
    "orange",
    "amber",
    "green",
    "teal",
    "blue",
    "indigo",
    "violet",
    "pink",
}


def _trim_text(value: str, *, field: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"{field} cannot be empty.")
    if any(ord(char) < 32 and char not in "\n\r\t" for char in value):
        raise ValueError(f"{field} contains unsupported control characters.")
    return value


class PageCategoryRead(BaseModel):
    id: int
    website_property_id: int
    name: str
    description: str | None
    color_key: str
    sort_order: int
    is_active: bool
    assignment_count: int = 0
    manual_assignment_count: int = 0
    automatic_assignment_count: int = 0
    exclusion_count: int = 0
    rule_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PageCategoryList(BaseModel):
    items: list[PageCategoryRead]
    total: int
    limit: int
    offset: int


class PageCategoryCreate(BaseModel):
    name: str = Field(max_length=100)
    description: str | None = Field(default=None, max_length=2000)
    color_key: str = "stone"
    sort_order: int = Field(default=0, ge=-100_000, le=100_000)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return _trim_text(value, field="Category name")

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        return _trim_text(value, field="Description")

    @field_validator("color_key")
    @classmethod
    def validate_color(cls, value: str) -> str:
        if value not in CATEGORY_COLOR_KEYS:
            raise ValueError("Unsupported category color.")
        return value


class PageCategoryUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, max_length=2000)
    color_key: str | None = None
    sort_order: int | None = Field(default=None, ge=-100_000, le=100_000)
    is_active: bool | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        return _trim_text(value, field="Category name") if value is not None else None

    @field_validator("description")
    @classmethod
    def validate_description(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        return _trim_text(value, field="Description")

    @field_validator("color_key")
    @classmethod
    def validate_color(cls, value: str | None) -> str | None:
        if value is not None and value not in CATEGORY_COLOR_KEYS:
            raise ValueError("Unsupported category color.")
        return value


class CategoryDeletionPage(BaseModel):
    resource_id: int
    normalized_url: str


class PageCategoryDeletionPreview(BaseModel):
    category: PageCategoryRead
    assignment_count: int
    manual_support_count: int = 0
    rule_support_count: int = 0
    rule_count: int = 0
    exclusion_count: int = 0
    sample_pages: list[CategoryDeletionPage]
    can_delete: bool = True


class PageMetadataUpdate(BaseModel):
    owner_label: str | None = Field(default=None, max_length=128)
    workflow_status: str | None = None
    category_ids: list[int] | None = None

    @field_validator("owner_label")
    @classmethod
    def validate_owner(cls, value: str | None) -> str | None:
        return _trim_text(value, field="Owner") if value and value.strip() else None

    @field_validator("workflow_status")
    @classmethod
    def validate_status(cls, value: str | None) -> str | None:
        if value is not None and value not in WORKFLOW_STATUSES:
            raise ValueError("Unsupported workflow status.")
        return value

    @field_validator("category_ids")
    @classmethod
    def validate_category_ids(cls, value: list[int] | None) -> list[int] | None:
        if value is not None and len(value) != len(set(value)):
            raise ValueError("category_ids cannot contain duplicates.")
        return value


class BulkPageCategories(BaseModel):
    resource_ids: list[int] = Field(min_length=1, max_length=500)
    add_category_ids: list[int] = Field(default_factory=list)
    remove_category_ids: list[int] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_ids(self) -> "BulkPageCategories":
        if len(self.resource_ids) != len(set(self.resource_ids)):
            raise ValueError("resource_ids cannot contain duplicates.")
        if len(self.add_category_ids) != len(set(self.add_category_ids)):
            raise ValueError("add_category_ids cannot contain duplicates.")
        if len(self.remove_category_ids) != len(set(self.remove_category_ids)):
            raise ValueError("remove_category_ids cannot contain duplicates.")
        if set(self.add_category_ids) & set(self.remove_category_ids):
            raise ValueError("A category cannot be added and removed in the same request.")
        return self


class BulkPageMetadata(BaseModel):
    resource_ids: list[int] = Field(min_length=1, max_length=500)
    owner_label: str | None = Field(default=None, max_length=128)
    workflow_status: str | None = None

    @model_validator(mode="after")
    def validate_payload(self) -> "BulkPageMetadata":
        if len(self.resource_ids) != len(set(self.resource_ids)):
            raise ValueError("resource_ids cannot contain duplicates.")
        if not ({"owner_label", "workflow_status"} & self.model_fields_set):
            raise ValueError("Supply owner_label or workflow_status.")
        return self

    @field_validator("owner_label")
    @classmethod
    def validate_owner(cls, value: str | None) -> str | None:
        return _trim_text(value, field="Owner") if value and value.strip() else None

    @field_validator("workflow_status")
    @classmethod
    def validate_status(cls, value: str | None) -> str | None:
        if value is not None and value not in WORKFLOW_STATUSES:
            raise ValueError("Unsupported workflow status.")
        return value


class BulkMutationResult(BaseModel):
    selected: int
    changed: int
    unchanged: int
    rejected: int = 0


class NoteCreate(BaseModel):
    body: str = Field(max_length=20_000)
    is_pinned: bool = False

    @field_validator("body")
    @classmethod
    def validate_body(cls, value: str) -> str:
        return _trim_text(value, field="Note")


class NoteUpdate(BaseModel):
    body: str | None = Field(default=None, max_length=20_000)
    is_pinned: bool | None = None

    @field_validator("body")
    @classmethod
    def validate_body(cls, value: str | None) -> str | None:
        return _trim_text(value, field="Note") if value is not None else None


class NoteRead(BaseModel):
    id: int
    website_property_id: int | None
    scan_id: int | None
    site_page_id: int | None
    body: str
    is_pinned: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class NoteList(BaseModel):
    items: list[NoteRead]
    total: int
    limit: int
    offset: int


NoteSort = Literal["created_at", "updated_at"]
