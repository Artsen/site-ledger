from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.observability_deletion_benchmark import run_benchmark  # noqa: E402

if __name__ == "__main__":
    print(json.dumps(run_benchmark(), indent=2, sort_keys=True))
