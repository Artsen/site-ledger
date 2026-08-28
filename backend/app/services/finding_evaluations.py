from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Finding,
    FindingAssessment,
    FindingEvaluation,
    FindingEvidenceReference,
    ResourceSnapshot,
    Scan,
    SitePage,
    WebsiteProperty,
)
from app.services.scan_projections import TERMINAL_SCAN_STATUSES

FINDING_EVALUATOR_VERSION = "finding-evaluator-v1"
FINDING_DETECTOR_BUNDLE_IDENTITY = "finding-detectors-v1"
PAGE_HTTP_ERROR_DETECTOR_IDENTITY = "page-http-error-v1"
PAGE_HTTP_ERROR_TYPE = "page_http_error"
PAGE_HTTP_ERROR_KEY_VERSION = "page-http-error-key-v1"


class FindingEvaluationChronologyError(RuntimeError):
    pass


@dataclass(frozen=True)
class FindingEvaluationResult:
    evaluation_id: int
    detected: int
    clear: int
    unknown: int
    created_findings: int
    resolved_findings: int
    reopened_findings: int
    assessments: int
    checksum_sha256: str


def _hash(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def finding_fingerprint(site_id: int, resource_id: int) -> str:
    return _hash(
        {
            "finding_type": PAGE_HTTP_ERROR_TYPE,
            "logical_key_version": PAGE_HTTP_ERROR_KEY_VERSION,
            "site_id": site_id,
            "subject_kind": "web_resource",
            "web_resource_id": resource_id,
        }
    )


def create_evaluation(db: Session, site_id: int) -> tuple[FindingEvaluation, bool]:
    if db.get(WebsiteProperty, site_id) is None:
        raise ValueError("Site not found.")
    scan = db.scalar(
        select(Scan)
        .where(Scan.website_property_id == site_id, Scan.status.in_(TERMINAL_SCAN_STATUSES))
        .order_by(Scan.created_at.desc(), Scan.id.desc())
        .limit(1)
    )
    if scan is None:
        raise ValueError("No terminal Scan is available for Finding evaluation.")
    resource_ids = list(
        db.scalars(
            select(SitePage.resource_id)
            .where(
                SitePage.website_property_id == site_id,
                SitePage.workspace_state == "active",
            )
            .order_by(SitePage.resource_id)
        )
    )
    universe_hash = _hash(resource_ids)
    horizon = scan.finished_at or scan.created_at
    fingerprint = _hash(
        {
            "active_page_universe_sha256": universe_hash,
            "detector_bundle_identity": FINDING_DETECTOR_BUNDLE_IDENTITY,
            "evaluator_version": FINDING_EVALUATOR_VERSION,
            "site_id": site_id,
            "source_scan_id": scan.id,
        }
    )
    existing = db.scalar(
        select(FindingEvaluation).where(FindingEvaluation.input_fingerprint_sha256 == fingerprint)
    )
    if existing is not None:
        return existing, False
    evaluation = FindingEvaluation(
        website_property_id=site_id,
        source_scan_id=scan.id,
        evaluator_version=FINDING_EVALUATOR_VERSION,
        detector_bundle_identity=FINDING_DETECTOR_BUNDLE_IDENTITY,
        input_fingerprint_sha256=fingerprint,
        evidence_horizon_at=horizon,
        active_page_count=len(resource_ids),
        active_page_universe_sha256=universe_hash,
        active_page_resource_ids_json=resource_ids,
        status="queued",
    )
    db.add(evaluation)
    db.flush()
    return evaluation, True


def execute_evaluation(
    db: Session,
    evaluation_id: int,
    *,
    check_ownership: Callable[[], None] | None = None,
) -> FindingEvaluationResult:
    evaluation = db.get(FindingEvaluation, evaluation_id)
    if evaluation is None:
        raise ValueError("Finding evaluation not found.")
    if evaluation.status == "completed":
        return _result(evaluation)
    if evaluation.source_scan_id is None:
        raise ValueError("The source Scan is no longer retained.")
    newer = db.scalar(
        select(FindingEvaluation.id)
        .where(
            FindingEvaluation.website_property_id == evaluation.website_property_id,
            FindingEvaluation.detector_bundle_identity == evaluation.detector_bundle_identity,
            FindingEvaluation.status == "completed",
            FindingEvaluation.evidence_horizon_at > evaluation.evidence_horizon_at,
        )
        .limit(1)
    )
    if newer is not None:
        raise FindingEvaluationChronologyError(
            "A newer evidence horizon has already been applied to this Site."
        )
    if check_ownership:
        check_ownership()
    evaluation.status = "running"
    evaluation.started_at = datetime.now(UTC)

    resource_ids = list(evaluation.active_page_resource_ids_json)
    snapshots: dict[int, ResourceSnapshot] = {}
    for chunk in _chunks(resource_ids, 500):
        rows = db.scalars(
            select(ResourceSnapshot)
            .where(
                ResourceSnapshot.scan_id == evaluation.source_scan_id,
                ResourceSnapshot.resource_id.in_(chunk),
            )
            .order_by(ResourceSnapshot.id.desc())
        )
        for snapshot_row in rows:
            snapshots.setdefault(snapshot_row.resource_id, snapshot_row)
    existing = {
        item.web_resource_id: item
        for item in db.scalars(
            select(Finding).where(
                Finding.website_property_id == evaluation.website_property_id,
                Finding.finding_type == PAGE_HTTP_ERROR_TYPE,
                Finding.logical_key_version == PAGE_HTTP_ERROR_KEY_VERSION,
            )
        )
    }

    candidates: list[tuple[int, str, str | None, datetime, ResourceSnapshot | None]] = []
    counts = {"detected": 0, "clear": 0, "unknown": 0}
    new_findings: list[Finding] = []
    for resource_id in resource_ids:
        candidate_snapshot = snapshots.get(resource_id)
        outcome, severity = _classify(candidate_snapshot)
        counts[outcome] += 1
        finding = existing.get(resource_id)
        if finding is None and outcome != "detected":
            continue
        observed_at = (
            candidate_snapshot.fetched_at
            if candidate_snapshot is not None and candidate_snapshot.fetched_at is not None
            else evaluation.evidence_horizon_at
        )
        if finding is None:
            finding = Finding(
                website_property_id=evaluation.website_property_id,
                web_resource_id=resource_id,
                finding_type=PAGE_HTTP_ERROR_TYPE,
                logical_key_version=PAGE_HTTP_ERROR_KEY_VERSION,
                fingerprint_sha256=finding_fingerprint(evaluation.website_property_id, resource_id),
                condition_state="detected",
                current_severity=severity,
                first_detected_at=observed_at,
                last_detected_at=observed_at,
                last_evaluated_evidence_at=observed_at,
            )
            db.add(finding)
            new_findings.append(finding)
            existing[resource_id] = finding
        candidates.append((resource_id, outcome, severity, observed_at, candidate_snapshot))

    if check_ownership:
        check_ownership()
    db.flush()
    resolved = 0
    reopened = 0
    assessment_hashes: list[str] = []
    assessments: list[tuple[FindingAssessment, Finding, ResourceSnapshot | None]] = []
    new_ids = {item.id for item in new_findings}
    for resource_id, outcome, severity, observed_at, candidate_snapshot in candidates:
        finding = existing[resource_id]
        prior_state = finding.condition_state
        prior_acknowledged_at = finding.acknowledged_at
        is_new = finding.id in new_ids
        is_reopen = (
            not is_new
            and outcome == "detected"
            and finding.resolved_at is not None
            and finding.resolved_at >= finding.last_detected_at
        )
        details = {
            "detector_identity": PAGE_HTTP_ERROR_DETECTOR_IDENTITY,
            "fetch_state": candidate_snapshot.fetch_state if candidate_snapshot else None,
            "http_status": candidate_snapshot.http_status if candidate_snapshot else None,
            "source_scan_id": evaluation.source_scan_id,
            "transition": f"{prior_state}->{_state_for_outcome(outcome)}",
        }
        if is_reopen and prior_acknowledged_at is not None:
            details["prior_acknowledged_at"] = prior_acknowledged_at.isoformat()
        assessment_hash = _hash(
            {
                "details": details,
                "evaluation_fingerprint": evaluation.input_fingerprint_sha256,
                "evidence_observed_at": observed_at.isoformat(),
                "finding_fingerprint": finding.fingerprint_sha256,
                "outcome": outcome,
                "severity": severity,
            }
        )
        assessment = FindingAssessment(
            finding_id=finding.id,
            finding_evaluation_id=evaluation.id,
            outcome=outcome,
            severity=severity,
            evidence_observed_at=observed_at,
            details_json=details,
            assessment_sha256=assessment_hash,
        )
        db.add(assessment)
        assessments.append((assessment, finding, candidate_snapshot))
        assessment_hashes.append(assessment_hash)

        finding.last_evaluated_evidence_at = observed_at
        if outcome == "detected":
            finding.condition_state = "detected"
            finding.current_severity = severity
            finding.last_detected_at = observed_at
            if is_reopen:
                finding.reopened_at = observed_at
                finding.acknowledged_at = None
                reopened += 1
        elif outcome == "clear":
            finding.condition_state = "resolved"
            finding.current_severity = None
            if prior_state != "resolved":
                finding.resolved_at = observed_at
                resolved += 1
        else:
            finding.condition_state = "unknown"
            finding.current_severity = None

    db.flush()
    for assessment, finding, evidence_snapshot in assessments:
        finding.current_assessment_id = assessment.id
        if evidence_snapshot is not None:
            db.add(
                FindingEvidenceReference(
                    finding_assessment_id=assessment.id,
                    position=0,
                    role="primary",
                    evidence_kind="resource_snapshot",
                    evidence_id=evidence_snapshot.id,
                    evidence_observed_at=assessment.evidence_observed_at,
                    metadata_json={"resource_id": evidence_snapshot.resource_id},
                )
            )
        db.add(
            FindingEvidenceReference(
                finding_assessment_id=assessment.id,
                position=1 if evidence_snapshot is not None else 0,
                role="evaluation_horizon",
                evidence_kind="scan",
                evidence_id=evaluation.source_scan_id,
                evidence_observed_at=evaluation.evidence_horizon_at,
                metadata_json={},
            )
        )

    checksum = _hash(sorted(assessment_hashes))
    evaluation.detected_count = counts["detected"]
    evaluation.clear_count = counts["clear"]
    evaluation.unknown_count = counts["unknown"]
    evaluation.created_finding_count = len(new_findings)
    evaluation.resolved_finding_count = resolved
    evaluation.reopened_finding_count = reopened
    evaluation.assessment_count = len(assessments)
    evaluation.evaluation_checksum_sha256 = checksum
    evaluation.status = "completed"
    evaluation.finished_at = datetime.now(UTC)
    if check_ownership:
        check_ownership()
    db.flush()
    return _result(evaluation)


def mark_evaluation_terminal(
    db: Session,
    evaluation_id: int,
    status: str,
    *,
    error_type: str | None = None,
    error_message: str | None = None,
) -> None:
    evaluation = db.get(FindingEvaluation, evaluation_id)
    if evaluation is None or evaluation.status == "completed":
        return
    now = datetime.now(UTC)
    evaluation.status = status
    if status == "failed":
        evaluation.failed_at = now
    else:
        evaluation.finished_at = now
    evaluation.error_type = error_type
    evaluation.error_message = error_message


def _classify(snapshot: ResourceSnapshot | None) -> tuple[str, str | None]:
    if snapshot is None or snapshot.fetch_state != "fetched" or snapshot.http_status is None:
        return "unknown", None
    if 500 <= snapshot.http_status <= 599:
        return "detected", "high"
    if 400 <= snapshot.http_status <= 499:
        return "detected", "medium"
    return "clear", None


def _state_for_outcome(outcome: str) -> str:
    return {"detected": "detected", "clear": "resolved", "unknown": "unknown"}[outcome]


def _chunks(values: list[int], size: int) -> list[list[int]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def _result(evaluation: FindingEvaluation) -> FindingEvaluationResult:
    return FindingEvaluationResult(
        evaluation_id=evaluation.id,
        detected=evaluation.detected_count,
        clear=evaluation.clear_count,
        unknown=evaluation.unknown_count,
        created_findings=evaluation.created_finding_count,
        resolved_findings=evaluation.resolved_finding_count,
        reopened_findings=evaluation.reopened_finding_count,
        assessments=evaluation.assessment_count,
        checksum_sha256=evaluation.evaluation_checksum_sha256 or "",
    )
