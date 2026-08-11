from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from app.config import get_settings
from app.database import SessionLocal
from app.models import ContentBlob
from app.services.structured_content import (
    build_missing_structured_content,
    compatible_structured_artifact,
    get_or_create_structured_artifact,
    rebuild_structured_artifact,
    verify_structured_artifact,
)
from app.storage.content_store import LocalContentStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare deterministic structured Page content.")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("build", "rebuild", "verify"):
        command = commands.add_parser(name)
        command.add_argument("content_blob_id", type=int)
    missing = commands.add_parser("build-missing")
    missing.add_argument("--site-id", type=int)
    missing.add_argument("--scan-id", type=int)
    missing.add_argument("--limit", type=int)
    missing.add_argument("--stop-on-error", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    store = LocalContentStore(get_settings().html_storage_root)
    with SessionLocal() as db:
        if args.command == "build-missing":
            result = build_missing_structured_content(
                db,
                store,
                site_id=args.site_id,
                scan_id=args.scan_id,
                limit=args.limit,
                stop_on_error=args.stop_on_error,
                progress=lambda current, total, counts: print(
                    f"[{current}/{total}] {json.dumps(counts, sort_keys=True)}", flush=True
                ),
            )
            print(json.dumps(result, indent=2, sort_keys=True))
            return 1 if result["failed"] else 0

        blob = db.get(ContentBlob, args.content_blob_id)
        if blob is None:
            print(f"ContentBlob {args.content_blob_id} not found.", file=sys.stderr)
            return 1
        if args.command == "build":
            artifact, reused = get_or_create_structured_artifact(db, blob, store=store)
            db.commit()
            print(f"Artifact {artifact.id}: {artifact.extraction_state}; reused={reused}")
            return 0
        if args.command == "rebuild":
            artifact = rebuild_structured_artifact(db, blob, store)
            db.commit()
            print(f"Artifact {artifact.id}: {artifact.extraction_state}")
            return 0
        verified_artifact = compatible_structured_artifact(db, blob.id)
        if verified_artifact is None:
            print("Compatible structured content is not prepared.", file=sys.stderr)
            return 1
        verify_structured_artifact(db, verified_artifact)
        print(
            f"Artifact {verified_artifact.id} verified with "
            f"{verified_artifact.section_count} sections."
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
