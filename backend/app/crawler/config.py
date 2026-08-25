from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

CRAWL_POLICY_VERSION = "crawl-policy-v1"
STARTING_URL_MAX_LENGTH = 2_048


@dataclass(frozen=True)
class NumericLimit:
    minimum: int | float
    maximum: int | float
    integer: bool = True


@dataclass(frozen=True)
class CollectionLimit:
    max_items: int
    max_item_length: int


CRAWL_LIMITS: dict[str, NumericLimit] = {
    "max_pages": NumericLimit(1, 50_000),
    "max_depth": NumericLimit(0, 100),
    "request_timeout_seconds": NumericLimit(0.1, 120, integer=False),
    "static_max_attempts": NumericLimit(1, 5),
    "static_retry_initial_delay_ms": NumericLimit(0, 60_000),
    "static_retry_max_delay_ms": NumericLimit(0, 60_000),
    "max_html_response_bytes": NumericLimit(1, 20_000_000),
    "concurrent_requests_per_host": NumericLimit(1, 16),
    "delay_between_requests_ms": NumericLimit(0, 60_000),
    "max_redirects": NumericLimit(0, 20),
}

COLLECTION_LIMITS: dict[str, CollectionLimit] = {
    "allowed_host_patterns": CollectionLimit(256, 512),
    "excluded_host_patterns": CollectionLimit(256, 512),
    "included_path_prefixes": CollectionLimit(1_000, 2_048),
    "excluded_path_prefixes": CollectionLimit(1_000, 2_048),
    "drop_query_parameters": CollectionLimit(500, 256),
}

STRING_LIMITS: dict[str, int] = {
    "user_agent": 512,
}

BOOLEAN_FIELDS = {
    "follow_subdomains",
    "respect_robots_txt",
    "allow_private_networks",
    "enable_http_revalidation",
    "enable_parse_reuse",
}


class ScopeConfigValidationError(ValueError):
    pass


def validate_crawl_config(values: Mapping[str, object]) -> None:
    if not isinstance(values, Mapping):
        raise ScopeConfigValidationError("scope_config must be an object")

    for name, limit in CRAWL_LIMITS.items():
        value = values.get(name)
        if limit.integer:
            if type(value) is not int:
                raise ScopeConfigValidationError(f"{name} must be an integer")
            numeric_value: int | float = value
        elif isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ScopeConfigValidationError(f"{name} must be a finite number")
        else:
            numeric_value = value
            if not math.isfinite(numeric_value):
                raise ScopeConfigValidationError(f"{name} must be a finite number")
        if not limit.minimum <= numeric_value <= limit.maximum:
            raise ScopeConfigValidationError(
                f"{name} must be between {limit.minimum:g} and {limit.maximum:g}"
            )

    for name, collection_limit in COLLECTION_LIMITS.items():
        value = values.get(name)
        if not isinstance(value, list):
            raise ScopeConfigValidationError(f"{name} must be a list of strings")
        if len(value) > collection_limit.max_items:
            raise ScopeConfigValidationError(
                f"{name} cannot contain more than {collection_limit.max_items} items"
            )
        for item in value:
            if not isinstance(item, str):
                raise ScopeConfigValidationError(f"{name} must contain only strings")
            if len(item) > collection_limit.max_item_length:
                raise ScopeConfigValidationError(
                    f"{name} items cannot exceed {collection_limit.max_item_length} characters"
                )

    for name, max_length in STRING_LIMITS.items():
        value = values.get(name)
        if not isinstance(value, str):
            raise ScopeConfigValidationError(f"{name} must be a string")
        if len(value) > max_length:
            raise ScopeConfigValidationError(f"{name} cannot exceed {max_length} characters")

    for name in BOOLEAN_FIELDS:
        if not isinstance(values.get(name), bool):
            raise ScopeConfigValidationError(f"{name} must be a boolean")

    initial_delay = cast(int, values["static_retry_initial_delay_ms"])
    maximum_delay = cast(int, values["static_retry_max_delay_ms"])
    if initial_delay > maximum_delay:
        raise ScopeConfigValidationError(
            "static_retry_initial_delay_ms cannot exceed static_retry_max_delay_ms"
        )


def validate_starting_url_length(value: object) -> None:
    if not isinstance(value, str):
        raise ScopeConfigValidationError("starting_url must be a string")
    if len(value) > STARTING_URL_MAX_LENGTH:
        raise ScopeConfigValidationError(
            f"starting_url cannot exceed {STARTING_URL_MAX_LENGTH} characters"
        )
