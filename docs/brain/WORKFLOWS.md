# Workflow Traces

These traces are compressed navigation maps. Follow the paths into source for implementation detail.

## Scan to intelligence

1. **User/API starts a Scan**
   - FastAPI scan routes create native Scan state and enqueue a `BackgroundJob`.
2. **Worker claims job**
   - `backend/app/worker.py`
   - `background_jobs.claim_next_job()`
3. **Scan handler executes**
   - `backend/app/services/job_handlers.py` → `ScanJobHandler`
   - `backend/app/services/scan_execution.py` → `ScanExecutionCoordinator`
4. **Static crawl**
   - `backend/app/crawler/static_crawler.py` → `StaticPageCrawler`
   - safe network path via `safe_fetch.py`, `security.py`, `secure_transport.py`
5. **Persist authoritative evidence**
   - resource identity, snapshots/fetch attempts, occurrences, Page membership
   - job-owned writes are fenced before commit
6. **Terminal follow-ups**
   - `job_followups.ensure_terminal_scan_followups()`
   - queues/reconciles required versioned derivations such as Scan Projection and category rules
7. **Derived views**
   - `scan_projections.py`
   - optional comparisons / structured content / Findings evaluations
8. **Cross-domain read model**
   - `site_intelligence.get_site_intelligence()`
9. **Frontend**
   - `SiteIntelligenceOverview.tsx` and related Site workspace surfaces

## Lease loss and recovery

1. Worker A claims a job with lease token A.
2. Worker A begins slow work.
3. Lease expires or heartbeat ownership is lost.
4. Worker B legitimately recovers the same durable job with a new lease token B.
5. Worker A may still return from network/browser/computation work.
6. Before Worker A can make a durable domain mutation:
   - `JobExecutionContext.fence_domain_mutation(db)`
   - `guard_execution_ownership(...)`
7. The transaction verifies job id/status/lease token.
8. Token A is stale → mutation fails/rolls back.
9. Worker B remains the only writer with valid ownership.

**Core idea:** lease recovery permits duplicate *execution*, but fencing prevents duplicate *authority*.

## Projection build

1. Terminal Scan is authoritative input.
2. Create/stage a projection build with explicit algorithm identity.
3. Derive deterministic rows from retained Scan evidence.
4. Write in bounded batches.
5. Compute/verify checksums and build metadata.
6. Atomically activate the valid build as current.
7. Supersede older current derived state without altering Scan evidence.

## Comparison

1. Select baseline Scan and target Scan.
2. Resolve exact compatible current projection builds for both.
3. Persist the build’s exact projection identities/checksums.
4. Compute deterministic Page/resource/link deltas.
5. Query/present the comparison.
6. Site Intelligence orders site chronology by the target observation, not by “when this comparison happened to be rebuilt.”

## Finding evaluation

1. Select the current terminal static Scan and freeze the ordered active Page universe.
2. Select active configured/robots-discovered sitemap roots; never promote persistent `sitemap_index_discovered` descendants to independent roots.
3. Freeze each selected root's exact recursive `SourceRefresh` tree, including document type, terminal status, membership materialization, and ordered child-refresh IDs.
4. Persist `finding-evidence-manifest-v1`, evaluator version, detector-bundle identity/manifest, evidence horizon, and the complete input fingerprint.
5. At execution, validate the frozen refresh tree against retained immutable Source evidence; do not consult later mutable Inventory to reinterpret it.
6. Batch-load static snapshots, occurrences, and usable sitemap `SourceEntryObservation` membership leaves.
7. Run deterministic detectors against the frozen composite input. Each detector returns `detected`, `clear`, or `unknown`.
8. Reconcile durable Finding lifecycle:
   - first detection → open
   - clear after prior detection → resolved
   - later detection → reopened
   - unknown → do not falsely resolve
9. Persist typed evidence references so a user can trace exact Scan and Source evidence independently.
10. Same Scan + newer Source tree, or newer Scan + same Source tree, produces a distinct evaluation fingerprint without rewriting prior evidence.
11. A later completed same-bundle evaluation prevents an older queued frozen manifest from mutating current Findings.

## Collection Plan

1. Freeze active Page universe in stable order.
2. For one requested evidence domain, determine compatible coverage, latest compatible observation
   timestamps, and equivalent active collection independently.
3. `missing_current` selects uncovered eligible Pages; `refresh_current` selects all eligible Pages
   for Performance, Accessibility, or Render. Both exclude equivalent active collection.
4. Persist deterministic target selection/checksums, reason counts, and each selected Page's reason
   and prior compatible observation timestamp.
5. Batch target IDs into existing collector run limits.
6. Enqueue normal Render/Performance/Accessibility/Structured Content work.
7. Aggregate plan progress from those native runs.
8. Cancellation preserves atomicity between queued native state and corresponding background jobs.
9. Structured Content remains missing-current only because currentness follows retained HTML and
   extractor identity rather than wall-clock age.

## Finding administrative deletion and reset

1. Individual deletion verifies Site ownership and that no Finding evaluation is queued/running.
2. It deletes one Finding, its assessments, typed references, and acknowledgement while retaining
   the frozen evaluation, detector summary, terminal job history, and all collected evidence.
3. Full Site reset requires explicit confirmation and independently checks active
   `FindingEvaluation` and `BackgroundJob` state so drift fails closed.
4. In one transaction it deletes Site Findings, assessments/references, evaluations, and terminal
   Finding-evaluation jobs/events only.
5. Scans, snapshots, occurrences, content, recursive `SourceRefresh` topology,
   `SourceEntryObservation`, and every independent evidence domain remain untouched.
6. With the prior evaluation fingerprint and job dedupe key removed, the same retained composite
   evidence can create and execute a deterministic new evaluation.

## Source refresh

1. User/configured Source defines sitemap/manual/AI provenance; `UrlSourceEntry` represents mutable current Inventory, not historical proof.
2. Refresh executes through durable background work and the hardened network boundary.
3. For sitemap XML, persist `SourceRefresh.sitemap_document_type` and reset ordered child-refresh topology for this exact execution.
4. For a `urlset`:
   - reconcile mutable `UrlSourceEntry` current Inventory,
   - persist one immutable duplicate-preserving `SourceEntryObservation` per declaration position,
   - retain exact normalization/validation/scope provenance,
   - mark membership materialized.
5. For a `sitemapindex`:
   - create/reuse persistent child Source identities,
   - create exact child `SourceRefresh` rows for this execution,
   - recurse,
   - retain ordered exact child-refresh IDs on the parent refresh,
   - do not treat the index container itself as Page-membership evidence.
6. All authoritative Source evidence/topology persists under the same job ownership fence/transaction semantics as the Source refresh mutation.
7. Scan seed selection may use current Inventory, while later Finding evaluation may freeze immutable Source evidence; neither rewrites the other's history.
