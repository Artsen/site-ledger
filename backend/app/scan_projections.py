from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Scan
from app.services.scan_projections import (
    SCAN_PROJECTION_VERSION,
    TERMINAL_SCAN_STATUSES,
    create_projection_build,
    current_projection_build,
    execute_projection_build,
    verify_projection_build,
)


def _progress(phase: str, current: int, total: int) -> None:
    print(f"  {phase}: {current}/{total}", flush=True)


def _build(scan_id: int, *, force: bool) -> bool:
    with SessionLocal() as db:
        try:
            build = create_projection_build(db, scan_id, force=force)
            if build.status == "ready":
                print(
                    f"Scan {scan_id}: projection {build.id} is already ready "
                    f"({build.projection_version})."
                )
                return True
            db.commit()
            build_id = build.id
            print(f"Scan {scan_id}: building projection {build_id}.", flush=True)
            ready = execute_projection_build(db, build_id, progress=_progress)
            print(
                f"Scan {scan_id}: ready build {ready.id}, "
                f"{ready.page_count} Pages, {ready.resource_count} Resources, "
                f"{ready.link_edge_count} links, {ready.build_duration_ms} ms."
            )
            return True
        except Exception as exc:
            db.rollback()
            print(f"Scan {scan_id}: failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return False


def _missing_scan_ids(limit: int | None) -> list[int]:
    with SessionLocal() as db:
        statement = select(Scan.id).where(Scan.status.in_(TERMINAL_SCAN_STATUSES)).order_by(Scan.id)
        scan_ids = list(db.scalars(statement))
        missing = [scan_id for scan_id in scan_ids if current_projection_build(db, scan_id) is None]
        return missing[:limit] if limit is not None else missing


def _verify(scan_id: int) -> bool:
    with SessionLocal() as db:
        try:
            result = verify_projection_build(db, scan_id)
        except Exception as exc:
            print(f"Scan {scan_id}: verification failed: {exc}", file=sys.stderr)
            return False
    print(f"Scan {scan_id}: verified {result['projection_version']}.")
    print(f"  checksum: {result['checksum_sha256']}")
    print(
        "  rows: "
        f"{result['projected_page_count']} Pages, "
        f"{result['projected_resource_count']} Resources, "
        f"{result['projected_link_edge_count']} links"
    )
    return True


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=f"Build durable Scan projections ({SCAN_PROJECTION_VERSION})."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="Build one terminal Scan if it is missing.")
    build.add_argument("scan_id", type=int)
    rebuild = commands.add_parser("rebuild", help="Force a new build for one terminal Scan.")
    rebuild.add_argument("scan_id", type=int)
    verify = commands.add_parser("verify", help="Verify the current compatible build.")
    verify.add_argument("scan_id", type=int)
    missing = commands.add_parser(
        "build-missing", help="Build terminal Scans missing the current projection version."
    )
    missing.add_argument("--limit", type=int, help="Maximum Scans to attempt in this run.")
    missing.add_argument(
        "--stop-on-error",
        action="store_true",
        help="Stop after the first failed Scan instead of continuing.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "build":
        return 0 if _build(args.scan_id, force=False) else 1
    if args.command == "rebuild":
        return 0 if _build(args.scan_id, force=True) else 1
    if args.command == "verify":
        return 0 if _verify(args.scan_id) else 1

    scan_ids = _missing_scan_ids(args.limit)
    print(f"Found {len(scan_ids)} terminal Scan(s) to build.")
    failed = 0
    for index, scan_id in enumerate(scan_ids, 1):
        print(f"[{index}/{len(scan_ids)}] Scan {scan_id}")
        if not _build(scan_id, force=False):
            failed += 1
            if args.stop_on_error:
                break
    print(f"Completed with {failed} failure(s).")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
