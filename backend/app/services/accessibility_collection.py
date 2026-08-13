from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.accessibility.audit import AccessibilityAuditResult, audit_page
from app.accessibility.engine import (
    ACCESSIBILITY_INTEGRATION_VERSION,
    ACCESSIBILITY_NORMALIZATION_VERSION,
    AXE_BUNDLE_SHA256,
    AXE_CORE_VERSION,
    PROFILES,
    RULESET_PROFILE,
    RULESET_SHA256,
    normalize_axe_result,
    ruleset_metadata,
)
from app.browser.capture import BrowserRenderer
from app.config import get_settings
from app.crawler.scope import ScopeConfig
from app.models import (
    AccessibilityNodeEvidence,
    AccessibilityObservation,
    AccessibilityRuleEvidence,
    AccessibilityRun,
    SitePage,
    WebResource,
    WebsiteProperty,
)
from app.schemas.accessibility import AccessibilityRunCreate
from app.storage.accessibility_store import LocalAccessibilityPayloadStore


@dataclass(frozen=True)
class AccessibilityTask:
    resource_id: int
    url: str
    profile: str


def create_accessibility_run(
    db: Session, site_id: int, payload: AccessibilityRunCreate
) -> AccessibilityRun:
    settings = get_settings()
    site = db.get(WebsiteProperty, site_id)
    if site is None:
        raise ValueError("Site not found.")
    if len(payload.resource_ids) > settings.accessibility_hard_page_limit:
        raise ValueError(
            f"An Accessibility run supports at most {settings.accessibility_hard_page_limit} Pages."
        )
    if len(payload.resource_ids) > settings.accessibility_default_page_limit:
        raise ValueError(
            f"An Accessibility run is configured for at most "
            f"{settings.accessibility_default_page_limit} Pages."
        )
    pages = list(
        db.execute(
            select(SitePage.resource_id)
            .join(WebResource, WebResource.id == SitePage.resource_id)
            .where(
                SitePage.website_property_id == site_id,
                SitePage.resource_id.in_(payload.resource_ids),
                WebResource.resource_type == "page",
            )
        )
    )
    if len(pages) != len(payload.resource_ids):
        raise ValueError("One or more selected Pages do not belong to this Site.")
    profiles = sorted(payload.profiles)
    resource_ids = sorted(payload.resource_ids)
    metadata = ruleset_metadata()
    run = AccessibilityRun(
        website_property_id=site_id,
        status="queued",
        trigger=payload.trigger,
        configuration_json={"resource_ids": resource_ids, "profiles": profiles},
        target_count=len(resource_ids),
        observation_count=len(resource_ids) * len(profiles),
        axe_core_version=AXE_CORE_VERSION,
        detector_bundle_sha256=AXE_BUNDLE_SHA256,
        integration_version=ACCESSIBILITY_INTEGRATION_VERSION,
        normalization_version=ACCESSIBILITY_NORMALIZATION_VERSION,
        ruleset_profile=RULESET_PROFILE,
        ruleset_rule_count=len(metadata["rules"]),
        ruleset_sha256=RULESET_SHA256,
    )
    db.add(run)
    db.flush()
    return run


async def execute_accessibility_run(
    session_factory: Callable[[], Session],
    run_id: int,
    *,
    should_cancel: Callable[[], bool],
    progress: Callable[[int, int, dict[str, int]], None],
) -> AccessibilityRun:
    settings = get_settings()
    with session_factory() as db:
        run = db.get(AccessibilityRun, run_id)
        if run is None:
            raise ValueError("Accessibility run not found.")
        if run.status in {"completed", "completed_with_errors", "cancelled"}:
            return run
        site = db.get(WebsiteProperty, run.website_property_id)
        if site is None:
            raise ValueError("Accessibility run Site not found.")
        run.status = "running"
        run.started_at = run.started_at or datetime.now(UTC)
        tasks = _tasks(db, run)
        scope = ScopeConfig.from_dict(site.scope_config)
        db.commit()
    async with BrowserRenderer(scope, site.normalized_base_url) as renderer:
        for task in tasks:
            if should_cancel():
                return _mark_cancelled(session_factory, run_id)
            with session_factory() as db:
                exists = db.scalar(
                    select(AccessibilityObservation.id).where(
                        AccessibilityObservation.accessibility_run_id == run_id,
                        AccessibilityObservation.web_resource_id == task.resource_id,
                        AccessibilityObservation.profile == task.profile,
                    )
                )
            if exists is None:
                result = await audit_page(
                    renderer,
                    task.url,
                    task.profile,
                    max_payload_bytes=settings.accessibility_max_payload_bytes,
                )
                _persist_result(session_factory, run_id, task, result)
            counters = _refresh_counts(session_factory, run_id)
            progress(counters["completed"], len(tasks), counters)
    with session_factory() as db:
        run = db.get(AccessibilityRun, run_id)
        assert run is not None
        run.status = "completed_with_errors" if run.failed_count else "completed"
        run.finished_at = datetime.now(UTC)
        db.commit()
        db.refresh(run)
        return run


def mark_accessibility_run_failed(db: Session, run_id: int, exc: Exception) -> None:
    run = db.get(AccessibilityRun, run_id)
    if run is None:
        return
    run.status = "failed"
    run.finished_at = datetime.now(UTC)
    run.error_summary = f"{type(exc).__name__}: {str(exc)[:800]}"
    db.commit()


def _tasks(db: Session, run: AccessibilityRun) -> list[AccessibilityTask]:
    config = run.configuration_json
    pages = list(
        db.execute(
            select(WebResource.id, WebResource.normalized_url)
            .where(WebResource.id.in_(config["resource_ids"]))
            .order_by(WebResource.id)
        )
    )
    return [
        AccessibilityTask(resource_id, url, profile)
        for resource_id, url in pages
        for profile in config["profiles"]
    ]


def _persist_result(
    session_factory: Callable[[], Session],
    run_id: int,
    task: AccessibilityTask,
    result: AccessibilityAuditResult,
) -> None:
    with session_factory() as db:
        run = db.get(AccessibilityRun, run_id)
        assert run is not None
        blob = None
        normalized = None
        if result.payload is not None:
            blob = LocalAccessibilityPayloadStore(
                get_settings().accessibility_payload_storage_root
            ).put(db, result.payload)
            normalized = normalize_axe_result(json.loads(result.payload))
        observation = AccessibilityObservation(
            accessibility_run_id=run_id,
            website_property_id=run.website_property_id,
            web_resource_id=task.resource_id,
            payload_blob_id=blob.id if blob else None,
            requested_url=task.url,
            final_url=result.final_url,
            profile=task.profile,
            outcome=result.outcome,
            observed_at=datetime.now(UTC),
            axe_core_version=AXE_CORE_VERSION,
            detector_bundle_sha256=AXE_BUNDLE_SHA256,
            integration_version=ACCESSIBILITY_INTEGRATION_VERSION,
            normalization_version=ACCESSIBILITY_NORMALIZATION_VERSION,
            ruleset_profile=RULESET_PROFILE,
            ruleset_sha256=RULESET_SHA256,
            browser_version=result.browser_version,
            playwright_version=result.playwright_version,
            profile_json=PROFILES[task.profile],
            violation_rule_count=normalized.violation_rule_count if normalized else 0,
            violation_node_count=normalized.violation_node_count if normalized else 0,
            incomplete_rule_count=normalized.incomplete_rule_count if normalized else 0,
            incomplete_node_count=normalized.incomplete_node_count if normalized else 0,
            pass_rule_count=normalized.pass_rule_count if normalized else 0,
            inapplicable_rule_count=normalized.inapplicable_rule_count if normalized else 0,
            normalized_sha256=normalized.sha256 if normalized else None,
            error_type=result.error_type,
            error_message=result.error_message,
        )
        db.add(observation)
        db.flush()
        if normalized:
            for rule in normalized.rules:
                row = AccessibilityRuleEvidence(
                    accessibility_observation_id=observation.id,
                    position=rule.position,
                    rule_id=rule.rule_id,
                    result_type=rule.result_type,
                    impact=rule.impact,
                    description=rule.description,
                    help=rule.help,
                    help_url=rule.help_url,
                    tags_json=rule.tags,
                    node_count=len(rule.nodes),
                    rule_evidence_sha256=rule.sha256,
                )
                db.add(row)
                db.flush()
                for node in rule.nodes:
                    db.add(
                        AccessibilityNodeEvidence(
                            accessibility_rule_evidence_id=row.id,
                            position=node.position,
                            impact=node.impact,
                            target_json=node.target,
                            html_snippet=node.html,
                            html_original_length=node.html_original_length,
                            html_truncated=node.html_truncated,
                            failure_summary=node.failure_summary,
                            node_evidence_sha256=node.sha256,
                        )
                    )
        db.commit()


def _refresh_counts(session_factory: Callable[[], Session], run_id: int) -> dict[str, int]:
    with session_factory() as db:
        rows = db.execute(
            select(AccessibilityObservation.outcome, func.count())
            .where(AccessibilityObservation.accessibility_run_id == run_id)
            .group_by(AccessibilityObservation.outcome)
        ).all()
        counts = {outcome: count for outcome, count in rows}
        run = db.get(AccessibilityRun, run_id)
        assert run is not None
        run.ready_count = counts.get("ready", 0)
        run.failed_count = counts.get("failed", 0)
        run.completed_count = run.ready_count + run.failed_count
        db.commit()
        return {
            "completed": run.completed_count,
            "ready": run.ready_count,
            "failed": run.failed_count,
        }


def _mark_cancelled(session_factory: Callable[[], Session], run_id: int) -> AccessibilityRun:
    with session_factory() as db:
        run = db.get(AccessibilityRun, run_id)
        assert run is not None
        run.status = "cancelled"
        run.finished_at = datetime.now(UTC)
        db.commit()
        db.refresh(run)
        return run
