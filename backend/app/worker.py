from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import uuid
from collections.abc import Callable
from contextlib import suppress

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import SessionLocal, is_transient_database_lock
from app.product import PRODUCT_NAME
from app.services import background_jobs
from app.services.job_handlers import build_handler_registry, run_claimed_job
from app.storage.content_store import LocalContentStore

logger = logging.getLogger("site_ledger.worker")


class WorkerService:
    def __init__(
        self,
        *,
        session_factory: Callable[[], Session],
        worker_id: str,
        concurrency: int,
        poll_interval_seconds: float,
        heartbeat_seconds: float,
        lease_seconds: float,
        store: LocalContentStore,
    ):
        self.session_factory = session_factory
        self.worker_id = worker_id
        self.concurrency = concurrency
        self.poll_interval_seconds = poll_interval_seconds
        self.heartbeat_seconds = heartbeat_seconds
        self.lease_seconds = lease_seconds
        self.registry = build_handler_registry(session_factory, store)
        self._stop = asyncio.Event()
        self._running: set[asyncio.Task[None]] = set()

    async def run(self, *, once: bool = False, recover_only: bool = False) -> None:
        self._register()
        self._recover()
        if recover_only:
            self._stop_worker()
            return
        heartbeat_task = asyncio.create_task(self._heartbeat_loop())
        try:
            while not self._stop.is_set():
                self._running = {task for task in self._running if not task.done()}
                while len(self._running) < self.concurrency:
                    claimed = self._claim()
                    if claimed is None:
                        break
                    task = asyncio.create_task(
                        run_claimed_job(
                            session_factory=self.session_factory,
                            registry=self.registry,
                            claimed_job=claimed,
                            lease_seconds=self.lease_seconds,
                        )
                    )
                    self._running.add(task)
                if once:
                    if self._running:
                        await asyncio.gather(*self._running)
                    return
                await asyncio.sleep(self.poll_interval_seconds)
                self._recover_if_idle()
        finally:
            heartbeat_task.cancel()
            await asyncio.gather(heartbeat_task, return_exceptions=True)
            if self._running:
                await asyncio.gather(*self._running, return_exceptions=True)
            self._stop_worker()

    def request_stop(self) -> None:
        self._stop.set()

    def _register(self) -> None:
        with self.session_factory() as db:
            background_jobs.register_worker(
                db,
                worker_id=self.worker_id,
                concurrency=self.concurrency,
                metadata={"kind": "local"},
            )
        logger.info("worker registered", extra={"worker_id": self.worker_id})

    def _recover(self) -> None:
        try:
            with self.session_factory() as db:
                recovered = background_jobs.recover_expired_jobs(db)
        except OperationalError as exc:
            if not is_transient_database_lock(exc):
                raise
            logger.warning("job recovery delayed by database lock")
            return
        if recovered:
            logger.warning("recovered expired jobs", extra={"recovered": recovered})

    def _recover_if_idle(self) -> None:
        if not self._running:
            self._recover()

    def _claim(self) -> background_jobs.ClaimedJob | None:
        try:
            with self.session_factory() as db:
                claimed = background_jobs.claim_next_job(
                    db,
                    worker_id=self.worker_id,
                    lease_seconds=self.lease_seconds,
                )
        except OperationalError as exc:
            if not is_transient_database_lock(exc):
                raise
            logger.warning("job claim delayed by database lock")
            return None
        if claimed:
            logger.info(
                "claimed job",
                extra={"job_id": claimed.job.id, "job_type": claimed.job.job_type},
            )
        return claimed

    async def _heartbeat_loop(self) -> None:
        while True:
            try:
                with self.session_factory() as db:
                    background_jobs.heartbeat_worker(db, self.worker_id)
            except OperationalError as exc:
                if not is_transient_database_lock(exc):
                    raise
                logger.warning("worker heartbeat delayed by database lock")
            await asyncio.sleep(self.heartbeat_seconds)

    def _stop_worker(self) -> None:
        with self.session_factory() as db:
            background_jobs.stop_worker(db, self.worker_id)
        logger.info("worker stopped", extra={"worker_id": self.worker_id})


def main() -> None:
    parser = argparse.ArgumentParser(description=f"Run the {PRODUCT_NAME} background worker.")
    parser.add_argument("--once", action="store_true", help="Process at most one polling cycle.")
    parser.add_argument(
        "--recover-only",
        action="store_true",
        help="Run expired lease recovery and exit without claiming jobs.",
    )
    parser.add_argument("--worker-id", default=f"worker-{uuid.uuid4().hex[:12]}")
    parser.add_argument("--concurrency", type=int, default=None)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = get_settings()
    store = LocalContentStore(settings.html_storage_root)
    worker = WorkerService(
        session_factory=SessionLocal,
        worker_id=args.worker_id,
        concurrency=args.concurrency or settings.job_worker_concurrency,
        poll_interval_seconds=settings.job_poll_interval_seconds,
        heartbeat_seconds=settings.job_worker_heartbeat_seconds,
        lease_seconds=settings.job_lease_seconds,
        store=store,
    )

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    for signame in ("SIGINT", "SIGTERM"):
        sig = getattr(signal, signame, None)
        if sig is not None:
            with suppress(NotImplementedError):
                loop.add_signal_handler(sig, worker.request_stop)
    loop.run_until_complete(worker.run(once=args.once, recover_only=args.recover_only))


if __name__ == "__main__":
    main()
