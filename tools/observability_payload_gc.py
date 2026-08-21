from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import get_settings  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.services.observability_payload_gc import (  # noqa: E402
    collect_accessibility_payload_gc,
    collect_performance_payload_gc,
)
from app.storage.accessibility_store import LocalAccessibilityPayloadStore  # noqa: E402
from app.storage.performance_store import LocalPerformancePayloadStore  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit or collect orphan observability payloads.")
    parser.add_argument("--domain", choices=("performance", "accessibility", "all"), default="all")
    parser.add_argument("--apply", action="store_true", help="Apply safe orphan cleanup.")
    args = parser.parse_args()
    settings = get_settings()
    reports = []
    with SessionLocal() as db:
        if args.domain in {"performance", "all"}:
            reports.append(
                collect_performance_payload_gc(
                    db,
                    LocalPerformancePayloadStore(settings.performance_payload_storage_root),
                    apply=args.apply,
                )
            )
        if args.domain in {"accessibility", "all"}:
            reports.append(
                collect_accessibility_payload_gc(
                    db,
                    LocalAccessibilityPayloadStore(settings.accessibility_payload_storage_root),
                    apply=args.apply,
                )
            )
    print(json.dumps([asdict(report) for report in reports], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
