# Agent Retrieval Guide

This brain is designed to reduce context load while keeping source code authoritative.

## Retrieval algorithm

When given a Site Ledger task:

1. **Classify the task** into one or more node IDs in `graph.json`.
2. Read that node's `summary`, `source_paths`, and `symbols`.
3. Read the matching section in `CONTEXT_PACKS.md`.
4. Read all relevant invariants in `INVARIANTS.md` **before proposing a change**.
5. Traverse only the graph edges that represent a real boundary crossed by the requested change.
6. Inspect the actual current source files before editing.
7. Check `FRONTIER.md` for unmerged work that may invalidate assumptions.
8. After editing, update this brain only if a domain boundary, workflow, invariant, or context pack changed.

## Maintenance contract

This checked-in brain is maintained repository documentation, but it is never source-code
authority. Update only the affected files when a PR materially changes a domain boundary, durable
invariant, major workflow, semantic graph relationship, architecture-relevant compatibility
identity, or minimum context pack:

- `graph.json` and generated `GRAPH.md` for semantic relationships;
- generated `DOMAINS.md` for ownership, summaries, and canonical paths;
- `WORKFLOWS.md` for major end-to-end lifecycle changes;
- `INVARIANTS.md` only for durable constraints;
- `CONTEXT_PACKS.md` when minimum authoritative file sets change;
- this guide when retrieval or maintenance policy changes;
- `FRONTIER.md` when the active product/architecture frontier materially changes;
- `DESIGN_NOTES.md` when the context-map design philosophy changes;
- `README.md` when orientation or provenance changes.

Ordinary bug fixes and internal refactors do not require mechanical graph churn. Current source,
migrations, and tests always win.

## Retrieval priorities

Use this order:

1. **Exact implementation** — current source/migrations/tests.
2. **Invariant docs** — why the implementation is constrained.
3. **Domain docs** — broader semantics and product behavior.
4. **This second brain** — navigation/compression.
5. **README/product copy** — orientation, not architectural authority.

## Good graph expansion

Question: “Add a Finding for broken canonical links.”

Start:
`findings`

Likely expand:
`findings → static-scan`
`findings → structured-content` if canonical extraction comes from that layer
`findings → background-jobs` only if execution/lifecycle changes

Do **not** automatically load:
performance, accessibility, graph UI, all migrations, every route.

## Another example

Question: “Make the crawler concurrent.”

Start:
`static-scan`

Expand:
- `network-security` because connection behavior changes
- `background-jobs` because interruption/fencing must still hold
- `site-identity` because deterministic admission/order may affect durable identity/evidence
- `testing`

Then inspect whether projection/checksum expectations depend on crawl ordering.

## Cross-stream Source example

Question: “Change sitemap-based Finding semantics.”

Start:
`findings`

Expand:
- `source-evidence` because immutable `SourceRefresh` / `SourceEntryObservation` provenance changes
- `sources` only when current Source/Inventory selection or refresh behavior changes
- `static-scan` when the static side of the correlation changes
- `background-jobs` when ownership/terminalization semantics change

Never substitute mutable `UrlSourceEntry` rows for historical Source evidence.


## Output discipline for agents

Before implementation, state:
- nodes touched,
- invariants touched,
- authoritative files inspected,
- whether the change alters evidence, derived state, workspace state, or operational state.

This forces architectural changes to be explicit.


## PR impact check

For an existing branch/PR, run:

```bash
python docs/brain/impact_map.py --base origin/main --head HEAD
```

Use the output as a **starting impact set**, not as proof that untouched neighboring domains are irrelevant. Path matching is deterministic but cannot infer every semantic dependency; expand through graph edges when the change crosses a real boundary.

`graph.json` is the machine-readable semantic source of truth. `GRAPH.md` and `DOMAINS.md` are generated views.
