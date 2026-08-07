from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

import regex  # type: ignore[import-untyped]

from app.models import WebResource
from app.schemas.category_rules import CategoryRuleConditionPayload

EVALUATOR_VERSION = "page-category-rules-v1"
MAX_TARGET_LENGTH = 8192
REGEX_TIMEOUT_SECONDS = 0.02


class RuleEvaluationError(ValueError):
    pass


@dataclass(frozen=True)
class CompiledCondition:
    payload: CategoryRuleConditionPayload
    pattern: Any | None = None


def compile_conditions(
    conditions: list[CategoryRuleConditionPayload],
) -> list[CompiledCondition]:
    compiled: list[CompiledCondition] = []
    for condition in conditions:
        flags = 0 if condition.case_sensitive else regex.IGNORECASE
        if condition.target == "host":
            flags = regex.IGNORECASE
        try:
            if condition.operator == "regex":
                pattern = regex.compile(condition.value, flags)
            elif condition.operator == "glob":
                pattern = regex.compile(fnmatch.translate(condition.value), flags)
            else:
                pattern = None
        except regex.error as exc:
            raise RuleEvaluationError(f"Invalid regular expression: {exc}") from exc
        compiled.append(CompiledCondition(condition, pattern))
    return compiled


def resource_matches(
    resource: WebResource, conditions: list[CompiledCondition], match_mode: str
) -> bool:
    outcomes = [condition_matches(resource, condition) for condition in conditions]
    return all(outcomes) if match_mode == "all" else any(outcomes)


def condition_matches(resource: WebResource, condition: CompiledCondition) -> bool:
    payload = condition.payload
    target = _target_value(resource, payload.target)
    if len(target) > MAX_TARGET_LENGTH:
        target = target[:MAX_TARGET_LENGTH]
    pattern = payload.value
    if payload.target == "host" or not payload.case_sensitive:
        comparable_target = target.casefold()
        comparable_pattern = pattern.casefold()
    else:
        comparable_target = target
        comparable_pattern = pattern
    try:
        if payload.operator == "equals":
            matched = comparable_target == comparable_pattern
        elif payload.operator == "starts_with":
            matched = comparable_target.startswith(comparable_pattern)
        elif payload.operator == "ends_with":
            matched = comparable_target.endswith(comparable_pattern)
        elif payload.operator == "contains":
            matched = comparable_pattern in comparable_target
        elif payload.operator == "glob":
            assert condition.pattern is not None
            matched = bool(condition.pattern.fullmatch(target, timeout=REGEX_TIMEOUT_SECONDS))
        else:
            assert condition.pattern is not None
            matched = bool(condition.pattern.search(target, timeout=REGEX_TIMEOUT_SECONDS))
    except TimeoutError as exc:
        raise RuleEvaluationError(
            f"Regular expression timed out for {payload.target}; simplify the pattern."
        ) from exc
    return not matched if payload.negate else matched


def _target_value(resource: WebResource, target: str) -> str:
    if target == "filename":
        if not resource.path or resource.path.endswith("/"):
            return ""
        return PurePosixPath(resource.path).name
    value = getattr(resource, target)
    return value or ""
