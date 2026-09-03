# Site Ledger Second Brain

**Repository:** `Artsen/site-ledger`  
**Canonical code snapshot:** `main@6e17e08e641b48660a7ed7a13d9227b288fcafc6`  
**Generated:** 2026-09-03  
**Recommended location:** `docs/brain/`

This adopted snapshot was reviewed against post-PR #51 `main` at the commit above and updated in
PR #52 for Findings administrative deletion/reset semantics and the current development frontier.

This directory is a **context map**, not a substitute for the codebase.

Its purpose is to let a human or coding agent answer four questions quickly:

1. **Where am I?** — which domain/community owns this concept?
2. **What is connected to it?** — what upstream evidence, downstream derivations, jobs, UI, and tests matter?
3. **What must never be broken?** — which architectural invariants constrain a change?
4. **What should I read next?** — the smallest context pack that gets from a concept to authoritative code.

## Authority and generated files

`graph.json` is the canonical machine-readable semantic graph.

- `GRAPH.md` is generated from `graph.json`.
- `DOMAINS.md` is generated from `graph.json`.
- Source code, migrations, and tests remain authoritative over the entire second brain.
- Active/unmerged work lives in `FRONTIER.md` and is deliberately not canonical graph truth.

When this second brain disagrees with current code: **the code wins**.

## Start here

- [`GRAPH.md`](GRAPH.md) — generated visual semantic graph.
- [`graph.json`](graph.json) — canonical machine-readable nodes, edges, truth layers, and invariant references.
- [`DOMAINS.md`](DOMAINS.md) — generated domain/community summaries with canonical code paths.
- [`WORKFLOWS.md`](WORKFLOWS.md) — end-to-end execution traces.
- [`INVARIANTS.md`](INVARIANTS.md) — stable architecture constraints referenced by graph nodes.
- [`CONTEXT_PACKS.md`](CONTEXT_PACKS.md) — minimum file bundles to load for common tasks.
- [`AGENT_GUIDE.md`](AGENT_GUIDE.md) — retrieval protocol for AI/coding agents.
- [`FRONTIER.md`](FRONTIER.md) — active/unmerged work.
- [`DESIGN_NOTES.md`](DESIGN_NOTES.md) — why this brain is structured this way.

## Mental model

> **Persistent website identity + immutable/versioned evidence + rebuildable intelligence + durable orchestration.**

| Layer | Meaning | Examples |
|---|---|---|
| Authoritative evidence | What Site Ledger actually observed at a point in time | `ResourceSnapshot`, `ResourceOccurrence`, `SourceEntryObservation`, Render/Performance/Accessibility observations |
| Persistent workspace state | User/site identity and organization that survives individual observations | `WebsiteProperty`, `SitePage`, categories, notes, workflow metadata |
| Derived/rebuildable state | Versioned interpretations built from retained evidence | projections, comparisons, structured content, Findings, Site Intelligence |
| Operational state | Who is doing work and whether it still owns the right to mutate | `BackgroundJob`, leases, native runs, Collection Plans |
| Platform/cross-cutting | Infrastructure supporting or exposing the other layers | persistence, API, frontend, security, testing |

If a change blurs these layers, inspect it carefully.

## Core flow

`Source definition → refresh → current Inventory + immutable Source evidence`

`Scan → immutable static evidence`

`frozen evidence manifest → deterministic Findings / other derivatives → Site Intelligence → user action → later evidence verifies change`

Cross-cutting every job-owned durable mutation:

`BackgroundJob lease → ownership fence → domain mutation in the same transaction`

## Repository integration

This directory is checked in at `docs/brain/`. Root `AGENTS.md` points here rather than copying the
entire package into global agent context:

```text
For unfamiliar or cross-domain work, use docs/brain/AGENT_GUIDE.md to retrieve
minimum safe context before editing. The second brain is a navigation layer only;
current source, migrations, and tests remain authoritative.
```

## Validate and regenerate

From the repository root:

```bash
python docs/brain/validate_graph.py --repo-root .
python docs/brain/generate_views.py --check
```

After intentionally changing `graph.json`:

```bash
python docs/brain/generate_views.py
python docs/brain/validate_graph.py --repo-root .
```

For a PR/branch impact summary:

```bash
python docs/brain/impact_map.py --base origin/main --head HEAD
```

## Update policy

Update this brain when a change alters:

- a first-class domain boundary,
- a durable invariant,
- a major workflow stage,
- a graph relationship,
- a truth/state-layer classification,
- or the minimum context pack for future work.

Do **not** churn it for local helper renames, ordinary same-domain refactors, cosmetic frontend changes, or tests that add coverage without changing semantics.
