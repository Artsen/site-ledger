from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TypedDict

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import (
    Finding,
    FindingAssessment,
    FindingEvaluation,
    FindingEvidenceReference,
    ResourceOccurrence,
    ResourceSnapshot,
    Scan,
    SitePage,
    WebsiteProperty,
)
from app.services.finding_detectors import (
    CURRENT_FINDING_DETECTOR_MANIFEST_SHA256,
    CURRENT_FINDING_DETECTORS,
    PAGE_HTTP_ERROR_KEY_VERSION,
    PAGE_HTTP_ERROR_TYPE,
    DetectorContext,
    DetectorEvidence,
    DetectorResult,
    FindingDetector,
    build_snapshot_url_index,
)
from app.services.scan_projections import TERMINAL_SCAN_STATUSES

FINDING_EVALUATOR_VERSION = "finding-evaluator-v2"
FINDING_DETECTOR_BUNDLE_IDENTITY = "finding-detectors-v4"


class DetectorSummary(TypedDict):
    detector_identity: str
    detected: int
    clear: int
    unknown: int
    reason_counts: dict[str, int]


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
    detector_summary: dict[str, DetectorSummary]


@dataclass(frozen=True)
class _Candidate:
    resource_id: int
    detector: FindingDetector
    result: DetectorResult
    observed_at: datetime


def _hash(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def finding_fingerprint(
    site_id: int,
    resource_id: int,
    *,
    finding_type: str = PAGE_HTTP_ERROR_TYPE,
    logical_key_version: str = PAGE_HTTP_ERROR_KEY_VERSION,
    subject_kind: str = "web_resource",
) -> str:
    return _hash(
        {
            "finding_type": finding_type,
            "logical_key_version": logical_key_version,
            "site_id": site_id,
            "subject_kind": subject_kind,
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
            "detector_bundle_manifest_sha256": CURRENT_FINDING_DETECTOR_MANIFEST_SHA256,
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
    if (
        evaluation.evaluator_version != FINDING_EVALUATOR_VERSION
        or evaluation.detector_bundle_identity != FINDING_DETECTOR_BUNDLE_IDENTITY
    ):
        raise ValueError("Historical Finding evaluations cannot run under the current evaluator.")
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
    scan = db.get(Scan, evaluation.source_scan_id)
    if scan is None:
        raise ValueError("The source Scan is no longer retained.")
    if check_ownership:
        check_ownership()
    evaluation.status = "running"
    evaluation.started_at = datetime.now(UTC)

    all_snapshots: dict[int, ResourceSnapshot] = {}
    for snapshot in db.scalars(
        select(ResourceSnapshot)
        .where(ResourceSnapshot.scan_id == evaluation.source_scan_id)
        .order_by(ResourceSnapshot.id.desc())
    ):
        all_snapshots.setdefault(snapshot.resource_id, snapshot)
    source_resource_by_snapshot_id = {
        snapshot.id: resource_id for resource_id, snapshot in all_snapshots.items()
    }
    occurrences_by_source_resource_id: dict[int, list[ResourceOccurrence]] = {}
    for occurrence in db.scalars(
        select(ResourceOccurrence)
        .where(ResourceOccurrence.source_snapshot_id.in_(source_resource_by_snapshot_id or {-1}))
        .order_by(ResourceOccurrence.normalized_target_url.asc(), ResourceOccurrence.id.asc())
    ):
        source_resource_id = source_resource_by_snapshot_id.get(occurrence.source_snapshot_id)
        if source_resource_id is not None:
            occurrences_by_source_resource_id.setdefault(source_resource_id, []).append(occurrence)
    context = DetectorContext(
        scan=scan,
        snapshots_by_resource_id=all_snapshots,
        snapshots_by_normalized_url=build_snapshot_url_index(scan, all_snapshots),
        occurrences_by_source_resource_id={
            resource_id: tuple(items)
            for resource_id, items in occurrences_by_source_resource_id.items()
        },
    )
    detector_keys = [
        (detector.finding_type, detector.logical_key_version)
        for detector in CURRENT_FINDING_DETECTORS
    ]
    existing = {
        (item.finding_type, item.logical_key_version, item.web_resource_id): item
        for item in db.scalars(
            select(Finding).where(
                Finding.website_property_id == evaluation.website_property_id,
                or_(
                    *[
                        (
                            (Finding.finding_type == finding_type)
                            & (Finding.logical_key_version == key_version)
                        )
                        for finding_type, key_version in detector_keys
                    ]
                ),
            )
        )
    }

    counts = {"detected": 0, "clear": 0, "unknown": 0}
    detector_summary: dict[str, DetectorSummary] = {
        detector.finding_type: {
            "detector_identity": detector.detector_identity,
            "detected": 0,
            "clear": 0,
            "unknown": 0,
            "reason_counts": {},
        }
        for detector in CURRENT_FINDING_DETECTORS
    }
    candidates: list[_Candidate] = []
    outcome_hashes: list[str] = []
    new_findings: list[Finding] = []
    for resource_id in evaluation.active_page_resource_ids_json:
        subject_snapshot = all_snapshots.get(resource_id)
        observed_at = (
            subject_snapshot.fetched_at
            if subject_snapshot is not None and subject_snapshot.fetched_at is not None
            else evaluation.evidence_horizon_at
        )
        for detector in CURRENT_FINDING_DETECTORS:
            detector_result = detector.evaluate(subject_snapshot, context)
            counts[detector_result.outcome] += 1
            summary = detector_summary[detector.finding_type]
            summary[detector_result.outcome] += 1
            if detector_result.reason_code:
                reason_counts = summary["reason_counts"]
                reason_counts[detector_result.reason_code] = (
                    reason_counts.get(detector_result.reason_code, 0) + 1
                )
            outcome_hashes.append(
                _hash(
                    {
                        "details": detector_result.details,
                        "detector_identity": detector.detector_identity,
                        "evidence": [
                            {
                                "evidence_id": _detector_evidence_id(item),
                                "evidence_kind": _detector_evidence_kind(item),
                                "role": item.role,
                            }
                            for item in detector_result.evidence
                        ],
                        "outcome": detector_result.outcome,
                        "resource_id": resource_id,
                        "severity": detector_result.severity,
                    }
                )
            )
            identity = (detector.finding_type, detector.logical_key_version, resource_id)
            finding = existing.get(identity)
            if finding is None and detector_result.outcome != "detected":
                continue
            if finding is None:
                finding = Finding(
                    website_property_id=evaluation.website_property_id,
                    web_resource_id=resource_id,
                    finding_type=detector.finding_type,
                    logical_key_version=detector.logical_key_version,
                    fingerprint_sha256=finding_fingerprint(
                        evaluation.website_property_id,
                        resource_id,
                        finding_type=detector.finding_type,
                        logical_key_version=detector.logical_key_version,
                        subject_kind=detector.subject_kind,
                    ),
                    condition_state="detected",
                    current_severity=detector_result.severity,
                    first_detected_at=observed_at,
                    last_detected_at=observed_at,
                    last_evaluated_evidence_at=observed_at,
                )
                db.add(finding)
                new_findings.append(finding)
                existing[identity] = finding
            candidates.append(_Candidate(resource_id, detector, detector_result, observed_at))

    if check_ownership:
        check_ownership()
    db.flush()
    resolved = 0
    reopened = 0
    assessments: list[tuple[FindingAssessment, _Candidate]] = []
    new_ids = {item.id for item in new_findings}
    for candidate in candidates:
        identity = (
            candidate.detector.finding_type,
            candidate.detector.logical_key_version,
            candidate.resource_id,
        )
        finding = existing[identity]
        prior_state = finding.condition_state
        prior_acknowledged_at = finding.acknowledged_at
        is_new = finding.id in new_ids
        is_reopen = (
            not is_new
            and candidate.result.outcome == "detected"
            and finding.resolved_at is not None
            and finding.resolved_at >= finding.last_detected_at
        )
        details = {
            **candidate.result.details,
            "detector_identity": candidate.detector.detector_identity,
            "source_scan_id": evaluation.source_scan_id,
            "transition": (f"{prior_state}->{_state_for_outcome(candidate.result.outcome)}"),
        }
        if is_reopen and prior_acknowledged_at is not None:
            details["prior_acknowledged_at"] = prior_acknowledged_at.isoformat()
        assessment_hash = _hash(
            {
                "details": details,
                "evaluation_fingerprint": evaluation.input_fingerprint_sha256,
                "evidence_observed_at": candidate.observed_at.isoformat(),
                "finding_fingerprint": finding.fingerprint_sha256,
                "outcome": candidate.result.outcome,
                "severity": candidate.result.severity,
            }
        )
        assessment = FindingAssessment(
            finding_id=finding.id,
            finding_evaluation_id=evaluation.id,
            outcome=candidate.result.outcome,
            severity=candidate.result.severity,
            evidence_observed_at=candidate.observed_at,
            details_json=details,
            assessment_sha256=assessment_hash,
        )
        db.add(assessment)
        assessments.append((assessment, candidate))

        finding.last_evaluated_evidence_at = candidate.observed_at
        if candidate.result.outcome == "detected":
            finding.condition_state = "detected"
            finding.current_severity = candidate.result.severity
            finding.last_detected_at = candidate.observed_at
            if is_reopen:
                finding.reopened_at = candidate.observed_at
                finding.acknowledged_at = None
                reopened += 1
        elif candidate.result.outcome == "clear":
            finding.condition_state = "resolved"
            finding.current_severity = None
            if prior_state != "resolved":
                finding.resolved_at = candidate.observed_at
                resolved += 1
        else:
            finding.condition_state = "unknown"
            finding.current_severity = None

    db.flush()
    for assessment, candidate in assessments:
        finding = existing[
            (
                candidate.detector.finding_type,
                candidate.detector.logical_key_version,
                candidate.resource_id,
            )
        ]
        finding.current_assessment_id = assessment.id
        for position, item in enumerate(candidate.result.evidence):
            evidence_kind = _detector_evidence_kind(item)
            evidence_id = _detector_evidence_id(item)
            observed_at = candidate.observed_at
            metadata: dict[str, object] = {}
            if item.snapshot is not None:
                observed_at = item.snapshot.fetched_at or candidate.observed_at
                metadata = {"resource_id": item.snapshot.resource_id}
            elif item.occurrence is not None:
                observed_at = item.occurrence.discovered_at or candidate.observed_at
                metadata = {
                    "source_snapshot_id": item.occurrence.source_snapshot_id,
                    "target_resource_id": item.occurrence.target_resource_id,
                    "normalized_target_url": item.occurrence.normalized_target_url,
                }
            db.add(
                FindingEvidenceReference(
                    finding_assessment_id=assessment.id,
                    position=position,
                    role=item.role,
                    evidence_kind=evidence_kind,
                    evidence_id=evidence_id,
                    evidence_observed_at=observed_at,
                    metadata_json=metadata,
                )
            )
        db.add(
            FindingEvidenceReference(
                finding_assessment_id=assessment.id,
                position=len(candidate.result.evidence),
                role="evaluation_horizon",
                evidence_kind="scan",
                evidence_id=evaluation.source_scan_id,
                evidence_observed_at=evaluation.evidence_horizon_at,
                metadata_json={},
            )
        )

    evaluation.detected_count = counts["detected"]
    evaluation.clear_count = counts["clear"]
    evaluation.unknown_count = counts["unknown"]
    evaluation.detector_summary_json = detector_summary
    evaluation.created_finding_count = len(new_findings)
    evaluation.resolved_finding_count = resolved
    evaluation.reopened_finding_count = reopened
    evaluation.assessment_count = len(assessments)
    evaluation.evaluation_checksum_sha256 = _hash(
        {"detector_summary": detector_summary, "outcomes": sorted(outcome_hashes)}
    )
    evaluation.status = "completed"
    evaluation.finished_at = datetime.now(UTC)
    if check_ownership:
        check_ownership()
    db.flush()
    return _result(evaluation)


def _detector_evidence_kind(item: DetectorEvidence) -> str:
    if item.snapshot is not None and item.occurrence is None:
        return "resource_snapshot"
    if item.occurrence is not None and item.snapshot is None:
        return "resource_occurrence"
    raise ValueError("Detector evidence must contain exactly one typed evidence object.")


def _detector_evidence_id(item: DetectorEvidence) -> int:
    evidence = item.snapshot or item.occurrence
    if evidence is None or evidence.id is None:
        raise ValueError("Detector evidence must be persisted before evaluation.")
    return evidence.id


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


def _state_for_outcome(outcome: str) -> str:
    return {"detected": "detected", "clear": "resolved", "unknown": "unknown"}[outcome]


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
        detector_summary=evaluation.detector_summary_json or {},
    )
