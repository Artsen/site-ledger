from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import SessionLocal
from app.models import Scan, ScanComparison, WebsiteProperty
from app.services.scan_comparisons import (
    SCAN_COMPARISON_VERSION,
    create_comparison,
    create_comparison_build,
    execute_comparison_build,
    verify_comparison_build,
)
from app.services.scan_projections import (
    create_projection_build,
    current_projection_build,
    execute_projection_build,
)
from app.storage.content_store import LocalContentStore


def _progress(phase: str, current: int, total: int) -> None:
    print(f"  {phase}: {current}/{total}", flush=True)


def _prepare_scan(db: Session, scan_id: int) -> None:
    if current_projection_build(db, scan_id):
        return
    build = create_projection_build(db, scan_id)
    db.commit()
    execute_projection_build(db, build.id, progress=_progress)


def _build_pair(baseline_id: int, target_id: int, *, force: bool) -> bool:
    store = LocalContentStore(get_settings().html_storage_root)
    with SessionLocal() as db:
        try:
            baseline = db.get(Scan, baseline_id)
            target = db.get(Scan, target_id)
            if baseline is None or target is None or baseline.website_property_id is None:
                raise ValueError("Baseline or Target saved-Site Scan was not found.")
            _prepare_scan(db, baseline.id)
            _prepare_scan(db, target.id)
            comparison = create_comparison(db, baseline.website_property_id, baseline.id, target.id)
            build = create_comparison_build(db, comparison.id, force=force)
            if build.status == "ready":
                print(f"Comparison {comparison.id}: build {build.id} is already ready.")
                return True
            db.commit()
            ready = execute_comparison_build(db, build.id, progress=_progress, store=store)
            print(
                f"Comparison {comparison.id}: ready build {ready.id}, "
                f"{ready.page_result_count} Pages, {ready.resource_result_count} Resources, "
                f"{ready.link_result_count} links, {ready.build_duration_ms} ms."
            )
            print(f"  checksum: {ready.comparison_checksum_sha256}")
            return True
        except Exception as exc:
            db.rollback()
            print(
                f"Comparison {baseline_id}->{target_id}: failed: {type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
            return False


def _rebuild(comparison_id: int) -> bool:
    with SessionLocal() as db:
        comparison = db.get(ScanComparison, comparison_id)
        if comparison is None:
            print("Comparison not found.", file=sys.stderr)
            return False
        pair = comparison.baseline_scan_id, comparison.target_scan_id
    return _build_pair(*pair, force=True)


def _verify(comparison_id: int) -> bool:
    with SessionLocal() as db:
        try:
            result = verify_comparison_build(db, comparison_id)
        except Exception as exc:
            print(f"Comparison {comparison_id}: verification failed: {exc}", file=sys.stderr)
            return False
    print(f"Comparison {comparison_id}: verified {SCAN_COMPARISON_VERSION}.")
    print(f"  checksum: {result['checksum_sha256']}")
    return True


def _adjacent_pairs(site_id: int | None, limit: int | None) -> list[tuple[int, int]]:
    with SessionLocal() as db:
        site_ids = (
            [site_id]
            if site_id is not None
            else list(db.scalars(select(WebsiteProperty.id).order_by(WebsiteProperty.id)))
        )
        pairs: list[tuple[int, int]] = []
        for current_site_id in site_ids:
            scans = list(
                db.scalars(
                    select(Scan)
                    .where(
                        Scan.website_property_id == current_site_id,
                        Scan.status.in_({"completed", "completed_with_errors"}),
                    )
                    .order_by(Scan.created_at, Scan.id)
                )
            )
            pairs.extend(
                (before.id, after.id) for before, after in zip(scans, scans[1:], strict=False)
            )
        return pairs[:limit] if limit is not None else pairs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=f"Build durable Scan comparisons ({SCAN_COMPARISON_VERSION})."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build", help="Build one directional Scan pair.")
    build.add_argument("baseline_scan_id", type=int)
    build.add_argument("target_scan_id", type=int)
    rebuild = commands.add_parser("rebuild", help="Rebuild one logical comparison.")
    rebuild.add_argument("comparison_id", type=int)
    verify = commands.add_parser("verify", help="Verify one current comparison build.")
    verify.add_argument("comparison_id", type=int)
    adjacent = commands.add_parser("build-adjacent", help="Build adjacent successful Scan pairs.")
    adjacent.add_argument("--site-id", type=int)
    adjacent.add_argument("--all-sites", action="store_true")
    adjacent.add_argument("--limit", type=int)
    adjacent.add_argument("--stop-on-error", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "build":
        return 0 if _build_pair(args.baseline_scan_id, args.target_scan_id, force=False) else 1
    if args.command == "rebuild":
        return 0 if _rebuild(args.comparison_id) else 1
    if args.command == "verify":
        return 0 if _verify(args.comparison_id) else 1
    if not args.site_id and not args.all_sites:
        print("Choose --site-id or --all-sites.", file=sys.stderr)
        return 2
    pairs = _adjacent_pairs(args.site_id, args.limit)
    print(f"Found {len(pairs)} adjacent Scan pair(s).")
    failed = 0
    for index, (baseline_id, target_id) in enumerate(pairs, 1):
        print(f"[{index}/{len(pairs)}] {baseline_id}->{target_id}")
        if not _build_pair(baseline_id, target_id, force=False):
            failed += 1
            if args.stop_on_error:
                break
    print(f"Completed with {failed} failure(s).")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
