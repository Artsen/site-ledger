# Architectural Invariants

These are the highest-value facts to preserve when changing Site Ledger. They are more important than any one class or module.

Each invariant has a stable `ID` referenced by `graph.json`. Rename the prose freely when needed; change an ID only when the invariant itself is replaced.

## 1. Evidence is not workspace state
**ID:** `evidence-not-workspace`

Observed evidence is historical truth. Persistent Site/Page organization is mutable workspace truth. Do not overwrite historical observations merely because a Page, category, or current inventory state changes.

**Read:** `docs/architecture.md`, `docs/page-history-and-reuse.md`, `backend/app/models/resources.py`.

## 2. Derived state must remain rebuildable
**ID:** `derived-state-rebuildable`

Scan projections, comparisons, structured content, Findings evaluations, and other interpretation layers should be reproducible from explicit retained inputs and version identities. A rebuild must not rewrite the historical evidence that produced it.

**Read:** `docs/scan-projections.md`, `docs/scan-comparisons.md`, `docs/findings.md`.

## 3. Job write ownership
**ID:** `job-write-ownership`

A worker lease is advisory until durable writes are fenced. Before a job-owned durable domain mutation commits, the transaction must prove that the job is still running under the same lease token.

Landmarks:

- `JobExecutionContext.fence_domain_mutation()`
- `background_jobs.guard_execution_ownership()`

The ownership check and domain mutation belong in the **same database transaction**.

## 4. A recovered job may coexist with a zombie worker
**ID:** `recovered-job-zombie-worker`

Never assume lease expiry kills the previous process. The old worker can wake up. Recovery correctness depends on fencing stale writes, not on hoping the old worker disappeared.

**Read:** `backend/tests/test_execution_ownership_fencing.py`, `backend/tests/test_worker_resilience.py`.

## 5. URL identity is versioned
**ID:** `url-identity-versioned`

Resource identity is derived through an explicit normalization version. Historical identities must not silently change when normalization rules evolve.

**Read:** `docs/url-identity-contract.md`.

## 6. Network destinations are hostile
**ID:** `network-destinations-hostile`

Every externally supplied crawl target is attacker-controlled. Scheme, userinfo, DNS results, redirects, and actual connection destination must preserve the network safety contract. Private/non-global destinations remain denied by default.

**Read:** `docs/network-security.md`, `backend/app/crawler/security.py`, `backend/app/crawler/secure_transport.py`.

## 7. Static and browser evidence are different clocks
**ID:** `independent-evidence-clocks`

Do not pretend that a fresh Scan means Render, Performance, Accessibility, Structured Content, Source, or other independently collected evidence is equally fresh. Site Intelligence intentionally exposes independent clocks.

## 8. Projection activation is atomic
**ID:** `projection-activation-atomic`

A projection build is not “current” because rows exist. It becomes current only after staged derivation, checksum/validation, and activation. Consumers should resolve the current compatible build rather than partial build state.

## 9. Comparisons pin exact inputs
**ID:** `comparisons-pin-exact-inputs`

A comparison is a statement about a specific baseline projection and target projection, including their versions/checksums. Rebuilding an old comparison later must not masquerade as a newer site observation.

## 10. Findings are tri-state
**ID:** `findings-tristate`

`detected`, `clear`, and `unknown` are semantically distinct. Missing/incompatible evidence is not proof that a problem is fixed. `unknown` must not silently resolve an existing Finding.

## 11. Finding history is durable
**ID:** `finding-history-durable`

Finding lifecycle is historical product state and is durable by default. Deleting source evidence
may make a reference unavailable; it must not erase the Finding history that once referred to it.
Explicit administrative deletion may intentionally discard one logical Finding while preserving
its frozen evaluation. Explicit Site reset may atomically discard the entire rebuildable
Finding/evaluation interpretation layer while preserving all collected evidence and enabling a
deterministic rerun. Both remain distinct from normal evidence deletion and are blocked while Site
Finding evaluation work is active.

## 12. Collection Plans orchestrate existing collectors
**ID:** `collection-plans-use-native-collectors`

A Collection Plan selects targets and batches native collectors. It should not create a parallel evidence model.

## 13. Frozen universes are deterministic
**ID:** `frozen-universes-deterministic`

Whenever a run says “these Pages were evaluated/targeted,” the Page universe and relevant context should be frozen or fingerprinted so later mutable Site state cannot reinterpret an earlier result.

## 14. Required follow-ups are idempotent/recoverable
**ID:** `required-followups-recoverable`

If terminal work requires downstream projection/category/comparison work, retries and recovery must be safe. “Terminal state committed” must not mean required follow-ups can be silently lost.

## 15. SQLite is an intentional architecture choice
**ID:** `sqlite-intentional`

Do not introduce distributed infrastructure merely to look production-like. The current durability model is deliberately engineered around SQLite/WAL/local-first constraints. Revisit when deployment or scale requirements actually change.

## 16. Mutable Source inventory is not historical Source evidence
**ID:** `source-inventory-not-historical-evidence`

`UrlSourceEntry` is mutable current Inventory. A later refresh may update or reactivate the same row, so it cannot prove what an earlier Source refresh declared. Historical sitemap membership uses immutable `SourceEntryObservation` rows attached to an exact `SourceRefresh`; pre-migration membership is unavailable rather than reconstructed from current Inventory.

**Read:** `docs/architecture.md`, `docs/findings.md`, `backend/app/models/resources.py`, `backend/app/services/source_refresh.py`.

## 17. Recursive sitemap topology is refresh-scoped and frozen
**ID:** `recursive-sitemap-topology-frozen`

A sitemap index is a container, not a Page-membership leaf. Each exact `SourceRefresh` retains its sitemap document type and ordered exact child-refresh IDs. Finding evaluation freezes configured/robots-discovered sitemap roots and recursively selected refresh trees; persistent discovered-child Source state must not make stale membership current. Presence may be proven by any usable leaf, but absence is clear only when every required frozen branch is complete and usable.

**Read:** `docs/findings.md`, `backend/app/services/finding_evaluations.py`, `backend/tests/test_findings.py`, `backend/tests/test_sources.py`.

## 18. Compatibility is not freshness
**ID:** `compatibility-not-freshness`

Compatible evidence, explicit freshness policy, and equivalent active collection are separate
states. Current-compatible evidence remains covered while a refresh is active. Nothing is stale or
due without an explicit frozen policy and cutoff, and refresh collection always creates new native
evidence rather than rewriting prior observations.

**Read:** `docs/collection-plans.md`, `backend/app/services/collection_plans.py`.
