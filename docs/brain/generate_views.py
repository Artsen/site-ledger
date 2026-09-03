#!/usr/bin/env python3
"""Generate human-readable Site Ledger second-brain views from graph.json."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load_graph() -> dict:
    return json.loads((HERE / "graph.json").read_text(encoding="utf-8"))


def render_graph_md(data: dict) -> str:
    lines = [
        "# Site Ledger Knowledge Graph",
        "",
        f"Canonical snapshot: `main@{data['base_commit']}` ({data['generated_at']}).",
        "",
        "This is a generated human-readable projection of `graph.json`. Edit `graph.json`, then regenerate this file.",
        "",
        "```mermaid",
        "flowchart LR",
    ]
    aliases = {}
    for node in data["nodes"]:
        alias = node["id"].replace("-", "_")
        aliases[node["id"]] = alias
        label = node["label"].replace('"', "'")
        lines.append(f'    {alias}["{label}"]')
    for edge in data["edges"]:
        lines.append(
            f"    {aliases[edge['source']]} -->|{edge['relation']}| {aliases[edge['target']]}"
        )
    lines.extend(["```", ""])
    return "\n".join(lines)


def render_domains_md(data: dict) -> str:
    lines = [
        "# Domain Map",
        "",
        f"Snapshot: `main@{data['base_commit']}`.",
        "",
        "This file is generated from `graph.json`. Source code remains authoritative.",
        "",
    ]
    for node in data["nodes"]:
        lines.extend([
            f"## {node['label']} (`{node['id']}`)",
            "",
            node["summary"],
            "",
            f"**Type:** `{node['type']}`  ",
            f"**State layer:** `{node.get('state_layer', 'unspecified')}`",
            "",
            "**Canonical paths:**",
        ])
        for path in node.get("source_paths", []):
            lines.append(f"- `{path}`")
        if node.get("symbols"):
            lines.extend(["", "**Landmark symbols:**"])
            for symbol in node["symbols"]:
                lines.append(f"- `{symbol}`")
        if node.get("invariants"):
            lines.extend(["", "**Relevant invariants:**"])
            for invariant in node["invariants"]:
                lines.append(f"- `{invariant}`")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="fail if generated views are stale")
    args = parser.parse_args()
    data = load_graph()
    expected = {
        HERE / "GRAPH.md": render_graph_md(data),
        HERE / "DOMAINS.md": render_domains_md(data),
    }
    stale = []
    for path, content in expected.items():
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != content:
                stale.append(path.name)
        else:
            path.write_text(content, encoding="utf-8")
    if stale:
        raise SystemExit("Generated second-brain views are stale: " + ", ".join(stale))
    if not args.check:
        print("Generated GRAPH.md and DOMAINS.md from graph.json")
    else:
        print("OK: generated second-brain views are current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
