# Design Notes: Why This Second Brain Looks Like This

The goal is **easy context mapping**, not graph maximalism.

## Patterns reviewed

### Aider repository map

Aider compresses a repository into important files, classes, functions, signatures, and relationships so an LLM can understand how the code it is editing fits the rest of the codebase. The key idea is **token-efficient global orientation**, not copying the repository into a second representation.

Reference: https://aider.chat/docs/repomap.html  
Background: https://aider.chat/2023/10/22/repomap.html

**Borrowed here:** landmark symbols, small source-path sets, whole-repo orientation.

### Sourcegraph Code Graph / Cody context

Sourcegraph treats definitions, references, symbols, and structural relationships as code graph data, then combines graph traversal with search/context retrieval. The graph improves discovery of *related* code; actual source remains authoritative.

References:
- https://sourcegraph.com/docs/cody/core-concepts/code-graph
- https://sourcegraph.com/docs/cody/core-concepts/context

**Borrowed here:** relationship-first navigation and “expand the neighborhood only when relevant.”

### Microsoft GraphRAG

GraphRAG extracts entities/relationships and then builds community summaries at multiple levels. Local queries fan out around an entity; global queries use community summaries. The valuable lesson for a codebase brain is the **two-level view**: compact community summaries plus local graph traversal.

References:
- https://github.com/microsoft/graphrag/blob/main/docs/index.md
- https://github.com/microsoft/graphrag/blob/main/docs/index/default_dataflow.md

**Borrowed here:** domain/community nodes, summaries, machine-readable relationships.

### Second-brain / Maps-of-Content style

Human second brains work best when index notes act as maps into smaller notes rather than attempting one giant hierarchy. In a repository, existing domain docs already behave like strong atomic notes, so this layer should be a Map of Content over them.

**Borrowed here:** `README.md` as a start-here map and domain-specific context packs.

## What this deliberately does not do

### It does not create one node per class/function

That would duplicate IDE/LSP/tree-sitter capabilities and become stale quickly.

### It does not embed every source file

Embeddings can be useful for retrieval, but Site Ledger already has exact code search and strongly named domains. A checked-in graph should remain deterministic, diffable, inspectable, and cheap.

### It does not declare generated summaries to be truth

Every node points back to canonical files. This protects against a stale “AI summary layer” becoming more trusted than code.

### It does not include unmerged PR semantics as canonical truth

Active work lives in `FRONTIER.md`. Once merged, the graph can be updated in the merge/next maintenance PR.

## Recommended maintenance policy

Update the graph when:
- a new first-class domain is introduced,
- evidence ownership changes,
- a durable invariant changes,
- a workflow gains/loses a major stage,
- a relationship between domains materially changes,
- or the minimum context pack for a task changes.

Do not update it for:
- renaming a local helper,
- ordinary refactors inside one node,
- cosmetic frontend changes,
- additional tests that do not change semantics.

This keeps the brain low-entropy.

Maintenance is file-specific rather than all-or-nothing. Semantic edges live in `graph.json`;
domain ownership is projected into `DOMAINS.md`; workflows and invariants change only when their
corresponding concepts change; context packs track minimum retrieval sets; and `FRONTIER.md` keeps
unimplemented direction out of canonical graph truth. A normal internal refactor should not touch
every file merely to signal that documentation was considered.


## Deterministic maintenance additions

### `graph.json` is the semantic source of truth

`GRAPH.md` and `DOMAINS.md` are generated projections. This prevents the human and machine maps from drifting independently.

### Truth/state layers are machine-readable

Each node declares `state_layer` (`evidence`, `workspace`, `derived`, `operational`, `platform`, or `mixed`). This makes dangerous boundary crossings visible to tooling and agents rather than leaving the truth model only in prose.

### Invariant references are machine-readable

Nodes carry stable invariant IDs from `INVARIANTS.md`. Retrieval can therefore load exact constraints instead of relying only on model inference.

### Impact mapping is deliberately conservative

`impact_map.py` maps changed paths to owning semantic nodes and their invariants. It is a routing aid, not a semantic proof system; agents must still traverse graph edges when a real boundary is crossed.
