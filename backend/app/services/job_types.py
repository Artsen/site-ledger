from typing import Literal

JobType = Literal[
    "scan",
    "source_refresh",
    "scan_projection_build",
    "scan_comparison_build",
    "category_rule_evaluation",
]
JobStatus = Literal[
    "queued",
    "running",
    "completed",
    "completed_with_errors",
    "failed",
    "cancelled",
    "interrupted",
]

JOB_TYPE_SCAN: JobType = "scan"
JOB_TYPE_SOURCE_REFRESH: JobType = "source_refresh"
JOB_TYPE_SCAN_PROJECTION_BUILD: JobType = "scan_projection_build"
JOB_TYPE_SCAN_COMPARISON_BUILD: JobType = "scan_comparison_build"
JOB_TYPE_CATEGORY_RULE_EVALUATION: JobType = "category_rule_evaluation"

JOB_TYPE_LABELS: dict[JobType, str] = {
    JOB_TYPE_SCAN: "Scan",
    JOB_TYPE_SOURCE_REFRESH: "Source refresh",
    JOB_TYPE_SCAN_PROJECTION_BUILD: "Scan results index",
    JOB_TYPE_SCAN_COMPARISON_BUILD: "Scan comparison",
    JOB_TYPE_CATEGORY_RULE_EVALUATION: "Category Rule evaluation",
}

JOB_STATUS_QUEUED: JobStatus = "queued"
JOB_STATUS_RUNNING: JobStatus = "running"
JOB_STATUS_COMPLETED: JobStatus = "completed"
JOB_STATUS_COMPLETED_WITH_ERRORS: JobStatus = "completed_with_errors"
JOB_STATUS_FAILED: JobStatus = "failed"
JOB_STATUS_CANCELLED: JobStatus = "cancelled"
JOB_STATUS_INTERRUPTED: JobStatus = "interrupted"

TERMINAL_JOB_STATUSES: set[str] = {
    JOB_STATUS_COMPLETED,
    JOB_STATUS_COMPLETED_WITH_ERRORS,
    JOB_STATUS_FAILED,
    JOB_STATUS_CANCELLED,
    JOB_STATUS_INTERRUPTED,
}

ACTIVE_JOB_STATUSES: set[str] = {JOB_STATUS_QUEUED, JOB_STATUS_RUNNING}

LEGAL_TRANSITIONS: dict[str, set[str]] = {
    JOB_STATUS_QUEUED: {JOB_STATUS_RUNNING, JOB_STATUS_CANCELLED},
    JOB_STATUS_RUNNING: {
        JOB_STATUS_COMPLETED,
        JOB_STATUS_COMPLETED_WITH_ERRORS,
        JOB_STATUS_FAILED,
        JOB_STATUS_CANCELLED,
        JOB_STATUS_INTERRUPTED,
        JOB_STATUS_QUEUED,
    },
    JOB_STATUS_FAILED: {JOB_STATUS_QUEUED},
    JOB_STATUS_COMPLETED: set(),
    JOB_STATUS_COMPLETED_WITH_ERRORS: set(),
    JOB_STATUS_CANCELLED: set(),
    JOB_STATUS_INTERRUPTED: set(),
}


def ensure_transition(current: str, target: str) -> None:
    if target not in LEGAL_TRANSITIONS.get(current, set()):
        raise ValueError(f"Invalid job transition: {current} -> {target}")
