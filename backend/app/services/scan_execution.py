from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy.orm import Session

from app.browser.config import validate_render_config
from app.crawler.config import ScopeConfigValidationError, validate_starting_url_length
from app.crawler.scope import ScopeConfig
from app.crawler.static_crawler import StaticPageCrawler
from app.models import Scan
from app.services.background_jobs import enqueue_render_run_job
from app.services.render_runs import create_scan_render_run
from app.services.rendered_capture import select_render_candidates
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
        try:
            validate_starting_url_length(scan.starting_url)
            config = ScopeConfig.from_dict(scan.scope_config)
            validate_render_config(config.to_dict())
        except (ScopeConfigValidationError, ValueError) as exc:
            return self._fail_invalid_config(scan, exc)
        self.context.progress(phase="preparing", current_operation="Preparing scan")
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
        elif selected:
            render_run = create_scan_render_run(self.db, scan, selected)
            enqueue_render_run_job(self.db, render_run)
        scan.status = "completed_with_errors" if static.had_errors else "completed"
        return self._finish(
            scan,
            rendered_stop_reason or static.stop_reason,
            static.had_errors,
            0,
        )

    def _finish(
        self, scan: Scan, reason: str, static_errors: bool, rendered_failures: int
    ) -> ScanExecutionSummary:
        self.context.progress(phase="finalizing", current_operation="Finalizing scan")
        scan.stop_reason = reason
        scan.finished_at = datetime.now(UTC)
        self.db.commit()
        return ScanExecutionSummary(scan.status, static_errors, rendered_failures)

    def _fail_invalid_config(self, scan: Scan, exc: ValueError) -> ScanExecutionSummary:
        scan.status = "failed"
        scan.stop_reason = "invalid_scope_config"
        scan.fatal_error_message = f"Invalid Scan configuration: {exc}"
        scan.finished_at = datetime.now(UTC)
        self.db.commit()
        return ScanExecutionSummary(scan.status, False, 0)
