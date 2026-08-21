from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy.orm import Session

from app.browser.capture import BrowserRenderer, CaptureResult
from app.browser.config import validate_render_config
from app.crawler.scope import ScopeConfig
from app.crawler.static_crawler import StaticPageCrawler
from app.models import Scan
from app.services.rendered_capture import (
    create_observation,
    persist_capture,
    select_render_candidates,
)
from app.storage.artifact_store import LocalArtifactStore
from app.storage.content_store import LocalContentStore


class ProgressContext(Protocol):
    def check_cancelled(self) -> bool: ...
    def progress(
        self,
        *,
        phase: str,
        current_operation: str | None = None,
        current: int | None = None,
        total: int | None = None,
        unit: str | None = None,
        counters: dict[str, int] | None = None,
    ) -> None: ...


@dataclass(frozen=True)
class ScanExecutionSummary:
    status: str
    static_errors: bool
    rendered_failures: int


class ScanExecutionCoordinator:
    def __init__(
        self,
        db: Session,
        content_store: LocalContentStore,
        artifact_store: LocalArtifactStore,
        context: ProgressContext,
    ):
        self.db = db
        self.content_store = content_store
        self.artifact_store = artifact_store
        self.context = context

    async def execute(self, scan: Scan) -> ScanExecutionSummary:
        config = ScopeConfig.from_dict(scan.scope_config)
        validate_render_config(config.to_dict())
        self.context.progress(phase="preparing", current_operation="Preparing scan")
        renderer: BrowserRenderer | None = None
        if config.render_mode != "none":
            renderer = BrowserRenderer(config, scan.starting_url, scan.url_normalization_version)
            await renderer.__aenter__()
        try:
            scan.status = "running"
            scan.started_at = datetime.now(UTC)
            self.db.commit()
            crawler = StaticPageCrawler(
                self.db,
                self.content_store,
                should_cancel=self.context.check_cancelled,
                progress_callback=lambda active: self.context.progress(
                    phase="crawling",
                    current_operation="Crawling pages",
                    current=active.fetched_count,
                    total=active.discovered_count or None,
                    unit="pages",
                    counters={
                        "discovered": active.discovered_count,
                        "queued": active.queued_count,
                        "fetched": active.fetched_count,
                        "failed": active.failed_count,
                        "skipped": active.skipped_count,
                    },
                ),
                retry_progress_callback=lambda current, total: self.context.progress(
                    phase="retrying_errors",
                    current_operation="Retrying transient fetch errors",
                    current=current,
                    total=total,
                    unit="pages",
                ),
            )
            static = await crawler.collect(scan)
            if static.fatal_error:
                scan.status = "failed"
                scan.fatal_error_message = static.fatal_error
                return self._finish(scan, static.stop_reason, static.had_errors, 0)
            if static.cancelled or self.context.check_cancelled():
                scan.status = "cancelled"
                return self._finish(scan, "cancelled_by_user", static.had_errors, 0)
            self.context.progress(
                phase="selecting_rendered_pages", current_operation="Selecting browser captures"
            )
            selected = select_render_candidates(self.db, scan, config)
            rendered_stop_reason: str | None = None
            scan.rendered_selected_count = len(selected)
            if config.render_mode == "starting_page" and not selected:
                scan.rendered_skipped_count = 1
                rendered_stop_reason = "starting_page_not_render_eligible"
            self.db.commit()
            rendered_failures = 0
            if renderer:
                for index, snapshot in enumerate(selected, 1):
                    if self.context.check_cancelled():
                        scan.status = "cancelled"
                        return self._finish(
                            scan, "cancelled_by_user", static.had_errors, rendered_failures
                        )
                    observation = create_observation(self.db, snapshot, config)
                    scan.rendered_attempted_count += 1
                    self.db.commit()
                    self.context.progress(
                        phase="rendering",
                        current_operation=snapshot.final_url or snapshot.requested_url,
                        current=index,
                        total=len(selected),
                        unit="pages",
                        counters=self._render_counters(scan),
                    )
                    result = await self._bounded_capture(
                        renderer, snapshot.final_url or snapshot.requested_url, config
                    )
                    if result is None:
                        observation.capture_state = "cancelled"
                        observation.error_type = "cancelled"
                        observation.error_message = "Capture cancelled by user."
                        observation.finished_at = datetime.now(UTC)
                        scan.status = "cancelled"
                        return self._finish(
                            scan, "cancelled_by_user", static.had_errors, rendered_failures
                        )
                    saved = persist_capture(
                        self.db, observation.id, result, renderer, self.artifact_store
                    )
                    scan.rendered_blocked_request_count += saved.blocked_request_count
                    scan.rendered_artifact_count += len(saved.artifacts)
                    if saved.capture_state == "failed":
                        scan.rendered_failed_count += 1
                        rendered_failures += 1
                    else:
                        scan.rendered_completed_count += 1
                        if saved.capture_state == "completed_with_warnings" and saved.error_type:
                            rendered_failures += 1
                    self.db.commit()
            scan.status = (
                "completed_with_errors" if static.had_errors or rendered_failures else "completed"
            )
            return self._finish(
                scan,
                rendered_stop_reason or static.stop_reason,
                static.had_errors,
                rendered_failures,
            )
        finally:
            if renderer:
                await renderer.__aexit__(None, None, None)

    def _finish(
        self, scan: Scan, reason: str, static_errors: bool, rendered_failures: int
    ) -> ScanExecutionSummary:
        self.context.progress(phase="finalizing", current_operation="Finalizing scan")
        scan.stop_reason = reason
        scan.finished_at = datetime.now(UTC)
        self.db.commit()
        return ScanExecutionSummary(scan.status, static_errors, rendered_failures)

    @staticmethod
    def _render_counters(scan: Scan) -> dict[str, int]:
        return {
            "selected": scan.rendered_selected_count,
            "attempted": scan.rendered_attempted_count,
            "completed": scan.rendered_completed_count,
            "failed": scan.rendered_failed_count,
            "skipped": scan.rendered_skipped_count,
            "blocked_requests": scan.rendered_blocked_request_count,
            "captured_artifacts": scan.rendered_artifact_count,
        }

    async def _bounded_capture(
        self, renderer: BrowserRenderer, url: str, config: ScopeConfig
    ) -> CaptureResult | None:
        task = asyncio.create_task(renderer.capture(url))
        deadline = time.monotonic() + config.render_max_page_duration_seconds
        while not task.done():
            if self.context.check_cancelled():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                return None
            if time.monotonic() >= deadline:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                return CaptureResult(
                    state="failed",
                    error_type="capture_timeout",
                    error_message="Browser capture exceeded the configured Page duration.",
                    duration_ms=int(config.render_max_page_duration_seconds * 1000),
                )
            await asyncio.sleep(0.25)
        return await task
