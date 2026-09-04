#!/usr/bin/env python3
"""Validate the checked-in Site Ledger second-brain graph and generated views."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ALLOWED_NODE_TYPES = {
    "community", "concept", "derived-domain", "domain", "evidence-domain",
    "invariant-area", "orchestration-domain", "platform", "read-model", "workspace-domain",
}
ALLOWED_STATE_LAYERS = {"evidence", "workspace", "derived", "operational", "platform", "mixed"}
ALLOWED_RELATIONS = {
    "adjacent_to", "built_by", "declares_candidates_for", "depends_on", "derived_from",
    "derives_from", "enqueues", "evaluated_by", "evaluates", "executed_by", "exposes",
    "freezes_active_page_universe", "guarded_by", "leases_and_fences_in", "normalizes_with",
    "organized_by", "pins", "presented_by", "reads", "reconciles", "records",
    "refresh_executed_by", "renders", "scoped_by", "stress_tests", "summarizes", "surfaces",
    "orchestrates_missing_or_refresh_current", "targets_missing_current", "terminalizes_into",
    "triggers", "verifies",
}


def parse_invariant_ids() -> set[str]:
    text = (HERE / "INVARIANTS.md").read_text(encoding="utf-8")
    return set(re.findall(r"\*\*ID:\*\* `([^`]+)`", text))


def discover_repo_root(explicit: str | None) -> Path | None:
    if explicit:
        return Path(explicit).resolve()
    proc = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=HERE, text=True, capture_output=True)
    if proc.returncode == 0:
        return Path(proc.stdout.strip()).resolve()
    return None


def check_git_snapshot(root: Path, base_commit: str, errors: list[str], warnings: list[str]) -> None:
    proc = subprocess.run(["git", "cat-file", "-e", f"{base_commit}^{{commit}}"], cwd=root, capture_output=True)
    if proc.returncode != 0:
        errors.append(f"base_commit {base_commit!r} is not present in this Git repository")
        return
    proc = subprocess.run(["git", "merge-base", "--is-ancestor", base_commit, "HEAD"], cwd=root)
    if proc.returncode == 1:
        warnings.append(f"base_commit {base_commit} is not an ancestor of HEAD; brain may target another branch/history")
    elif proc.returncode != 0:
        warnings.append("could not determine whether base_commit is an ancestor of HEAD")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", help="repository root used to validate source_paths and Git snapshot")
    parser.add_argument("--skip-source-paths", action="store_true")
    args = parser.parse_args()

    data = json.loads((HERE / "graph.json").read_text(encoding="utf-8"))
    errors: list[str] = []
    warnings: list[str] = []
    node_ids = [node.get("id") for node in data.get("nodes", [])]
    if len(node_ids) != len(set(node_ids)):
        errors.append("duplicate node ids")
    known = set(node_ids)
    invariant_ids = parse_invariant_ids()

    seen_edges: set[tuple[str, str, str]] = set()
    for i, edge in enumerate(data.get("edges", [])):
        source, target, relation = edge.get("source"), edge.get("target"), edge.get("relation")
        if source not in known:
            errors.append(f"edge {i} has unknown source {source!r}")
        if target not in known:
            errors.append(f"edge {i} has unknown target {target!r}")
        if relation not in ALLOWED_RELATIONS:
            errors.append(f"edge {i} has unknown relation {relation!r}")
        key = (str(source), str(target), str(relation))
        if key in seen_edges:
            errors.append(f"duplicate edge {key!r}")
        seen_edges.add(key)

    for node in data.get("nodes", []):
        node_id = node.get("id", "<missing>")
        if node.get("type") not in ALLOWED_NODE_TYPES:
            errors.append(f"node {node_id!r} has unknown type {node.get('type')!r}")
        if node.get("state_layer") not in ALLOWED_STATE_LAYERS:
            errors.append(f"node {node_id!r} has invalid state_layer {node.get('state_layer')!r}")
        if not node.get("summary"):
            errors.append(f"node {node_id!r} has no summary")
        if not node.get("source_paths"):
            errors.append(f"node {node_id!r} has no source paths")
        for invariant in node.get("invariants", []):
            if invariant not in invariant_ids:
                errors.append(f"node {node_id!r} references unknown invariant {invariant!r}")

    root = discover_repo_root(args.repo_root)
    if root is None:
        warnings.append("repository root not detected; source path and Git snapshot checks skipped")
    else:
        if not args.skip_source_paths:
            for node in data.get("nodes", []):
                for source_path in node.get("source_paths", []):
                    if not (root / source_path).exists():
                        errors.append(f"node {node['id']!r} source path does not exist: {source_path}")
        check_git_snapshot(root, data["base_commit"], errors, warnings)

    # Generated view consistency.
    proc = subprocess.run([sys.executable, str(HERE / "generate_views.py"), "--check"], cwd=HERE, text=True, capture_output=True)
    if proc.returncode != 0:
        errors.append(proc.stderr.strip() or proc.stdout.strip() or "generated views are stale")

    manifest = json.loads((HERE / "manifest.json").read_text(encoding="utf-8"))
    for name in manifest.get("canonical_files", []):
        if not (HERE / name).exists():
            errors.append(f"manifest file is missing: {name}")

    for warning in warnings:
        print(f"WARNING: {warning}")
    if errors:
        raise SystemExit("\n".join(f"ERROR: {e}" for e in errors))
    print(
        f"OK: {len(data['nodes'])} nodes, {len(data['edges'])} edges, "
        f"{len(invariant_ids)} invariants, schema={data['schema']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
