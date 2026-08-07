from datetime import datetime
from typing import Literal

import regex  # type: ignore[import-untyped]
from pydantic import BaseModel, Field, field_validator, model_validator

RuleTarget = Literal["normalized_url", "host", "path", "query", "filename"]
RuleOperator = Literal["equals", "starts_with", "ends_with", "contains", "glob", "regex"]
MatchMode = Literal["all", "any"]

MAX_RULE_CONDITIONS = 500
MAX_PATTERN_LENGTH = 2048


class CategoryRuleConditionPayload(BaseModel):
    target: RuleTarget
    operator: RuleOperator
    value: str = Field(max_length=MAX_PATTERN_LENGTH)
    negate: bool = False
    case_sensitive: bool = False
    sort_order: int = Field(default=0, ge=-100_000, le=100_000)

    @field_validator("value")
    @classmethod
    def validate_value(cls, value: str) -> str:
        if not value:
            raise ValueError("Condition value cannot be empty.")
        return value

    @model_validator(mode="after")
    def validate_condition(self) -> "CategoryRuleConditionPayload":
        if self.target == "host" and self.case_sensitive:
            raise ValueError("Host conditions are always case-insensitive.")
        if self.operator == "regex":
            try:
                regex.compile(self.value)
            except regex.error as exc:
                raise ValueError(f"Invalid regular expression: {exc}") from exc
        return self


class CategoryRuleDefinition(BaseModel):
    category_id: int
    match_mode: MatchMode = "all"
    conditions: list[CategoryRuleConditionPayload] = Field(
        min_length=1, max_length=MAX_RULE_CONDITIONS
    )


class CategoryRuleCreate(CategoryRuleDefinition):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=2000)
    is_active: bool = True
    sort_order: int = Field(default=0, ge=-100_000, le=100_000)

    @field_validator("name")
    @classmethod
    def trim_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Rule name cannot be empty.")
        return value


class CategoryRuleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=2000)
    category_id: int | None = None
    match_mode: MatchMode | None = None
    conditions: list[CategoryRuleConditionPayload] | None = Field(
        default=None, min_length=1, max_length=MAX_RULE_CONDITIONS
    )
    is_active: bool | None = None
    sort_order: int | None = Field(default=None, ge=-100_000, le=100_000)


class CategoryRuleConditionRead(CategoryRuleConditionPayload):
    id: int
    rule_id: int
    created_at: datetime

    model_config = {"from_attributes": True}


class CategoryRuleRead(BaseModel):
    id: int
    website_property_id: int
    category_id: int
    category_name: str
    name: str
    description: str | None
    match_mode: MatchMode
    is_active: bool
    sort_order: int
    current_revision_number: int
    current_match_count: int
    current_excluded_count: int
    last_evaluated_at: datetime | None
    created_at: datetime
    updated_at: datetime
    conditions: list[CategoryRuleConditionRead]


class CategoryRuleList(BaseModel):
    items: list[CategoryRuleRead]
    total: int
    limit: int
    offset: int


class CategoryRulePreviewRequest(CategoryRuleDefinition):
    rule_id: int | None = None


class CategoryRulePreviewPage(BaseModel):
    resource_id: int
    normalized_url: str


class CategoryRulePreview(BaseModel):
    total_pages_evaluated: int
    matching_pages: int
    currently_assigned: int
    would_gain_automatic_support: int
    would_lose_automatic_support: int
    excluded_matches: int
    sample_matching_pages: list[CategoryRulePreviewPage]
    sample_non_matching_pages: list[CategoryRulePreviewPage]
    invalid_conditions: list[str] = Field(default_factory=list)
    evaluation_duration_ms: int


class CategoryRuleDeletePreview(BaseModel):
    rule: CategoryRuleRead
    rule_support_count: int
    effective_assignments_removed: int
    effective_assignments_retained: int


class CategoryRuleRunRead(BaseModel):
    id: int
    website_property_id: int
    trigger_type: str
    trigger_rule_id: int | None
    status: str
    started_at: datetime | None
    finished_at: datetime | None
    page_count: int
    rule_count: int
    condition_count: int
    match_count: int
    rule_supports_added: int
    rule_supports_removed: int
    effective_assignments_added: int
    effective_assignments_removed: int
    exclusions_suppressing_matches: int
    unchanged_count: int
    error_type: str | None
    error_message: str | None
    configuration_json: dict[str, object]
    evaluator_version: str
    created_at: datetime

    model_config = {"from_attributes": True}


class CategoryRuleRunList(BaseModel):
    items: list[CategoryRuleRunRead]
    total: int
    limit: int
    offset: int


class CategoryProvenanceRule(BaseModel):
    id: int
    name: str


class CategoryProvenanceRead(BaseModel):
    category_id: int
    category_name: str
    manually_assigned: bool
    matching_rules: list[CategoryProvenanceRule]
    automatic_exclusion: bool
    effective: bool
    effective_reason: str


class CategoryProvenanceList(BaseModel):
    items: list[CategoryProvenanceRead]


class AutomaticExclusionPayload(BaseModel):
    category_id: int
    reason: str | None = Field(default=None, max_length=2000)
