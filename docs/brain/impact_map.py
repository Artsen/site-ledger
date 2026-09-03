#!/usr/bin/env python3
"""Map changed repository paths to Site Ledger second-brain nodes and invariants."""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent


def repo_root(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).resolve()
    proc = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=HERE, text=True, capture_output=True)
    if proc.returncode != 0:
        raise SystemExit("Could not find Git repository. Pass --repo-root.")
    return Path(proc.stdout.strip()).resolve()


def changed_paths(root: Path, base: str, head: str) -> list[str]:
    proc = subprocess.run(
        ["git", "diff", "--name-only", f"{base}...{head}"],
        cwd=root,
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        raise SystemExit(proc.stderr.strip() or "git diff failed")
    return [line.strip().replace("\\", "/") for line in proc.stdout.splitlines() if line.strip()]


def owns(path: str, source_path: str) -> bool:
    source_path = source_path.rstrip("/")
    return path == source_path or path.startswith(source_path + "/")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="origin/main")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--repo-root")
    parser.add_argument("paths", nargs="*", help="optional explicit changed paths instead of git diff")
    args = parser.parse_args()
    root = repo_root(args.repo_root)
    data = json.loads((HERE / "graph.json").read_text(encoding="utf-8"))
    paths = [p.replace("\\", "/") for p in args.paths] or changed_paths(root, args.base, args.head)

    touched = []
    for node in data["nodes"]:
        matches = sorted({p for p in paths for s in node.get("source_paths", []) if owns(p, s)})
        if matches:
            touched.append((node, matches))

    touched_ids = {node["id"] for node, _ in touched}
    crossed = [
        edge for edge in data["edges"]
        if edge["source"] in touched_ids and edge["target"] in touched_ids
    ]
    invariants = sorted({inv for node, _ in touched for inv in node.get("invariants", [])})

    print(f"Changed paths: {len(paths)}")
    for path in paths:
        print(f"  {path}")
    print("\nTouched nodes:")
    if not touched:
        print("  (none mapped; inspect manually)")
    for node, matches in touched:
        print(f"  {node['id']} [{node.get('state_layer', 'unspecified')}] — {node['label']}")
        for match in matches:
            print(f"    {match}")
    print("\nEdges inside touched set:")
    if not crossed:
        print("  (none)")
    for edge in crossed:
        print(f"  {edge['source']} --{edge['relation']}--> {edge['target']}")
    print("\nRelevant invariant IDs:")
    if not invariants:
        print("  (none mapped; inspect INVARIANTS.md manually)")
    for invariant in invariants:
        print(f"  {invariant}")
    print("\nReminder: this is a deterministic routing aid, not a complete semantic impact analysis.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
