import asyncio
from collections.abc import Callable

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.models import Scan
from app.storage.content_store import LocalContentStore


class ScanRunner:
    def __init__(self, session_factory: Callable[[], Session], store: LocalContentStore):
        self.session_factory = session_factory
        self.store = store
        self.tasks: dict[int, asyncio.Task[None]] = {}

    async def queue(self, scan_id: int) -> None:
        if scan_id in self.tasks:
            return
        task = asyncio.create_task(self._run(scan_id))
        self.tasks[scan_id] = task
        task.add_done_callback(lambda _task: self.tasks.pop(scan_id, None))

    async def cancel(self, scan_id: int) -> None:
        with self.session_factory() as db:
            scan = db.get(Scan, scan_id)
            if scan and scan.status in {"queued", "running"}:
                scan.status = "cancelled"
                db.commit()
        task = self.tasks.get(scan_id)
        if task:
            task.cancel()

    def mark_interrupted(self) -> None:
        with self.session_factory() as db:
            db.execute(
                update(Scan)
                .where(Scan.status == "running")
                .values(status="interrupted", stop_reason="application_restart")
            )
            db.commit()

    async def _run(self, scan_id: int) -> None:
        from app.crawler.static_crawler import StaticPageCrawler

        with self.session_factory() as db:
            scan = db.get(Scan, scan_id)
            if scan is None:
                return
            crawler = StaticPageCrawler(db, self.store)
            try:
                await crawler.run(scan)
            except asyncio.CancelledError:
                scan.status = "cancelled"
                scan.stop_reason = "cancelled_by_user"
                db.commit()
                raise
            except Exception as exc:
                scan.status = "failed"
                scan.fatal_error_message = str(exc)
                db.commit()
