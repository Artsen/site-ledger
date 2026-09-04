# Domain Map

Snapshot: `main@3dcdcfa410f7ed5b956b2f779178083a0927c7a6`.

This file is generated from `graph.json`. Source code remains authoritative.

## Product & Workspace (`product`)

Local-first website intelligence workspace centered on persistent Sites, Pages, evidence history, derived intelligence, and actionable Findings.

**Type:** `community`
**State layer:** `mixed`

**Canonical paths:**
- `README.md`
- `docs/product-vision.md`
- `docs/workspace-navigation.md`
- `docs/page-workspaces.md`

**Relevant invariants:**
- `evidence-not-workspace`
- `derived-state-rebuildable`
- `independent-evidence-clocks`

## Truth Model (`truth-model`)

Separate authoritative evidence, mutable workspace identity/state, rebuildable derived state, and operational execution state.

**Type:** `concept`
**State layer:** `mixed`

**Canonical paths:**
- `docs/architecture.md`
- `AGENTS.md`

**Relevant invariants:**
- `evidence-not-workspace`
- `derived-state-rebuildable`
- `independent-evidence-clocks`
- `source-inventory-not-historical-evidence`

## Site / Page / Resource Identity (`site-identity`)

WebsiteProperty scopes work; SitePage is persistent workspace membership; WebResource is normalized resource identity; observations attach history without replacing identity.

**Type:** `domain`
**State layer:** `workspace`

**Canonical paths:**
- `backend/app/models/resources.py`
- `backend/app/services/site_pages.py`
- `backend/app/services/repositories.py`
- `docs/page-history-and-reuse.md`
- `docs/url-identity-contract.md`

**Relevant invariants:**
- `evidence-not-workspace`
- `frozen-universes-deterministic`

## URL Identity (`url-identity`)

Normalized resource identity is explicitly versioned; historical identities are not silently reinterpreted.

**Type:** `invariant-area`
**State layer:** `platform`

**Canonical paths:**
- `backend/app/services/url_identity.py`
- `backend/app/crawler/url_normalizer.py`
- `docs/url-identity-contract.md`
- `docs/url-identity-reconciliation.md`

**Relevant invariants:**
- `url-identity-versioned`

## Static Scan (`static-scan`)

Deterministic static crawl records durable fetch attempts, snapshots, occurrences, resource identities, Page membership, and Render target-selection provenance.

**Type:** `domain`
**State layer:** `evidence`

**Canonical paths:**
- `backend/app/services/scan_execution.py`
- `backend/app/crawler/static_crawler.py`
- `backend/app/services/scan_queries.py`
- `backend/app/services/scan_render_authority.py`
- `backend/app/models/resources.py`

**Landmark symbols:**
- `ScanExecutionCoordinator`
- `StaticPageCrawler`

**Relevant invariants:**
- `evidence-not-workspace`
- `job-write-ownership`
- `recovered-job-zombie-worker`
- `network-destinations-hostile`
- `url-identity-versioned`

## Crawler Network Security (`network-security`)

Treat destinations as hostile: validate schemes, DNS answers, redirects, and pinned connections; private networks are denied by default.

**Type:** `invariant-area`
**State layer:** `platform`

**Canonical paths:**
- `backend/app/crawler/security.py`
- `backend/app/crawler/secure_transport.py`
- `backend/app/crawler/safe_fetch.py`
- `docs/network-security.md`
- `backend/tests/test_network_security.py`

**Relevant invariants:**
- `network-destinations-hostile`

## Source Definitions & Current Inventory (`sources`)

UrlSource definitions, current UrlSourceEntry inventory, manual declarations, robots/sitemap discovery, and AI Document Source configuration provide mutable source/workspace truth and collection entry points; they are not historical sitemap evidence.

**Type:** `domain`
**State layer:** `mixed`

**Canonical paths:**
- `backend/app/services/source_management.py`
- `backend/app/services/source_refresh.py`
- `backend/app/services/source_queries.py`
- `docs/architecture.md`
- `docs/resource-inventory.md`
- `docs/ai-document-sources.md`

**Relevant invariants:**
- `evidence-not-workspace`
- `url-identity-versioned`
- `job-write-ownership`
- `source-inventory-not-historical-evidence`

## Immutable Source Evidence (`source-evidence`)

SourceRefresh is the immutable collection envelope. Sitemap urlset refreshes persist duplicate-preserving SourceEntryObservation rows and sitemapindex refreshes retain ordered exact child-refresh topology so historical membership can be reconstructed without mutable inventory state.

**Type:** `evidence-domain`
**State layer:** `evidence`

**Canonical paths:**
- `backend/app/models/resources.py`
- `backend/app/services/source_refresh.py`
- `backend/app/services/finding_evaluations.py`
- `backend/alembic/versions/202609030032_sitemap_finding_evidence.py`
- `docs/architecture.md`
- `docs/findings.md`
- `backend/tests/test_sources.py`
- `backend/tests/test_findings.py`

**Landmark symbols:**
- `SourceRefresh`
- `SourceEntryObservation`
- `_build_evidence_manifest`

**Relevant invariants:**
- `evidence-not-workspace`
- `url-identity-versioned`
- `job-write-ownership`
- `independent-evidence-clocks`
- `frozen-universes-deterministic`
- `source-inventory-not-historical-evidence`
- `recursive-sitemap-topology-frozen`

## Durable Background Jobs (`background-jobs`)

BackgroundJob provides queued/running/terminal execution, leases, recovery, retries, ownership fencing, and an exhaustive typed lifecycle contract for durable domain mutation.

**Type:** `domain`
**State layer:** `operational`

**Canonical paths:**
- `backend/app/services/background_jobs.py`
- `backend/app/services/job_lifecycle.py`
- `backend/app/services/job_handlers.py`
- `backend/app/worker.py`
- `docs/background-jobs.md`

**Landmark symbols:**
- `claim_next_job`
- `JobLifecycleSpec`
- `lifecycle_for`
- `JobExecutionContext.fence_domain_mutation`
- `guard_execution_ownership`

**Relevant invariants:**
- `job-write-ownership`
- `recovered-job-zombie-worker`
- `required-followups-recoverable`

## Required Follow-ups (`job-followups`)

Terminal domain work schedules idempotent required downstream work such as scan projection and category reconciliation.

**Type:** `domain`
**State layer:** `operational`

**Canonical paths:**
- `backend/app/services/job_followups.py`
- `backend/app/services/job_handlers.py`

**Landmark symbols:**
- `ensure_terminal_scan_followups`
- `ensure_required_followups`

**Relevant invariants:**
- `required-followups-recoverable`

## Rendered Evidence (`render`)

RenderRun owns modern browser execution lifecycle, outcomes, and observations on an independent clock; historical Scan-owned browser evidence remains readable.

**Type:** `evidence-domain`
**State layer:** `evidence`

**Canonical paths:**
- `backend/app/services/render_runs.py`
- `backend/app/services/rendered_capture.py`
- `backend/app/services/rendered_queries.py`
- `backend/app/services/scan_render_authority.py`
- `docs/browser-rendered-observations.md`

**Relevant invariants:**
- `independent-evidence-clocks`
- `job-write-ownership`
- `network-destinations-hostile`

## Performance Evidence (`performance`)

Performance observations are collected in native runs with their own compatibility and freshness semantics.

**Type:** `evidence-domain`
**State layer:** `evidence`

**Canonical paths:**
- `backend/app/services/performance_collection.py`
- `backend/app/services/performance_queries.py`
- `docs/performance-observations.md`

**Relevant invariants:**
- `independent-evidence-clocks`
- `job-write-ownership`

## Accessibility Evidence (`accessibility`)

Accessibility observations use the hardened browser stack and remain a separately collected evidence domain.

**Type:** `evidence-domain`
**State layer:** `evidence`

**Canonical paths:**
- `backend/app/services/accessibility_collection.py`
- `backend/app/services/accessibility_queries.py`
- `docs/accessibility-observations.md`

**Relevant invariants:**
- `independent-evidence-clocks`
- `job-write-ownership`
- `network-destinations-hostile`

## Structured Content (`structured-content`)

Versioned structured extraction and canonical document rendering derive semantic content from retained page evidence.

**Type:** `derived-domain`
**State layer:** `derived`

**Canonical paths:**
- `backend/app/services/structured_content.py`
- `backend/app/services/structured_content_queries.py`
- `backend/app/crawler/structured_content.py`
- `docs/structured-page-content.md`

**Relevant invariants:**
- `derived-state-rebuildable`
- `independent-evidence-clocks`

## Scan Projections (`scan-projections`)

Versioned deterministic materialization turns authoritative Scan evidence into queryable current derived state using staged build, checksum, validation, and atomic activation.

**Type:** `derived-domain`
**State layer:** `derived`

**Canonical paths:**
- `backend/app/services/scan_projections.py`
- `backend/app/services/projection_queries.py`
- `backend/app/models/projections.py`
- `docs/scan-projections.md`

**Landmark symbols:**
- `current_projection_build`
- `create_projection_build`
- `execute_projection_build`

**Relevant invariants:**
- `derived-state-rebuildable`
- `projection-activation-atomic`

## Scan Comparisons (`comparisons`)

Comparisons pin exact baseline and target projection builds and compute deterministic deltas without rewriting source history.

**Type:** `derived-domain`
**State layer:** `derived`

**Canonical paths:**
- `backend/app/services/scan_comparisons.py`
- `backend/app/services/comparison_queries.py`
- `backend/app/models/comparisons.py`
- `docs/scan-comparisons.md`

**Landmark symbols:**
- `create_comparison_build`

**Relevant invariants:**
- `derived-state-rebuildable`
- `comparisons-pin-exact-inputs`

## Findings (`findings`)

Versioned detector bundles evaluate a frozen active-Page universe plus explicit retained evidence manifests. V5 correlates static Scan evidence with immutable recursive sitemap Source evidence while preserving tri-state lifecycle and typed provenance. History is durable by default; explicit administrative deletion/reset can discard rebuildable interpretation state without deleting evidence.

**Type:** `derived-domain`
**State layer:** `derived`

**Canonical paths:**
- `backend/app/services/finding_detectors.py`
- `backend/app/services/finding_evaluations.py`
- `backend/app/services/findings.py`
- `backend/app/services/finding_deletion.py`
- `backend/app/api/findings_routes.py`
- `backend/app/models/findings.py`
- `docs/findings.md`
- `backend/tests/test_findings.py`
- `frontend/src/pages/site-workspace/SiteFindingsWorkspace.tsx`

**Landmark symbols:**
- `execute_evaluation`
- `delete_finding`
- `reset_site_findings`

**Relevant invariants:**
- `derived-state-rebuildable`
- `findings-tristate`
- `finding-history-durable`
- `frozen-universes-deterministic`
- `independent-evidence-clocks`
- `source-inventory-not-historical-evidence`
- `recursive-sitemap-topology-frozen`

## Site Intelligence (`site-intelligence`)

Cross-domain overview summarizes coverage/currentness while preserving independent evidence clocks rather than inventing one fake site timestamp.

**Type:** `read-model`
**State layer:** `derived`

**Canonical paths:**
- `backend/app/services/site_intelligence.py`
- `backend/app/api/site_intelligence_routes.py`
- `frontend/src/pages/site-workspace/SiteIntelligenceOverview.tsx`
- `docs/site-intelligence.md`

**Landmark symbols:**
- `get_site_intelligence`

**Relevant invariants:**
- `independent-evidence-clocks`

## Collection Plans (`collection-plans`)

Plans freeze deterministic missing-current or explicit refresh-current selections and batch existing native collectors without becoming evidence or freshness policy.

**Type:** `orchestration-domain`
**State layer:** `operational`

**Canonical paths:**
- `backend/app/services/collection_plans.py`
- `backend/app/models/collection_plans.py`
- `frontend/src/pages/site-workspace/CollectionPlansWorkspace.tsx`
- `docs/collection-plans.md`

**Landmark symbols:**
- `build_selection`
- `create_collection_plan`

**Relevant invariants:**
- `collection-plans-use-native-collectors`
- `frozen-universes-deterministic`
- `compatibility-not-freshness`

## Page Categories & Rules (`categories`)

Mutable organizational state classifies persistent Pages independently from immutable scan evidence.

**Type:** `workspace-domain`
**State layer:** `workspace`

**Canonical paths:**
- `backend/app/services/page_categories.py`
- `backend/app/services/category_rules.py`
- `backend/app/services/category_rule_evaluator.py`
- `docs/page-category-rules.md`

**Relevant invariants:**
- `evidence-not-workspace`

## Website Graph (`website-graph`)

Scan-specific graph representation of Pages/resources/links for exploration; it is a view over stored evidence, not the source of truth.

**Type:** `read-model`
**State layer:** `derived`

**Canonical paths:**
- `backend/app/services/graph_queries.py`
- `backend/app/services/graph_filters.py`
- `backend/app/services/graph_config.py`
- `docs/website-graph.md`
- `docs/graph-performance.md`

**Relevant invariants:**
- `derived-state-rebuildable`

## Frontend Workspace (`frontend`)

React/TanStack Query workspace routes expose site intelligence, Findings, collection plans, Pages, graph, and evidence-detail surfaces.

**Type:** `community`
**State layer:** `platform`

**Canonical paths:**
- `frontend/src/main.tsx`
- `frontend/src/pages/site-workspace/SiteWorkspaceLayout.tsx`
- `frontend/src/pages/site-workspace/SiteWorkspacePages.tsx`
- `frontend/src/pages/site-workspace/SiteFindingsWorkspace.tsx`

## Persistence (`persistence`)

SQLite/WAL plus SQLAlchemy/Alembic store durable identity, evidence, derived state, and job state; filesystem stores content/artifacts where appropriate.

**Type:** `platform`
**State layer:** `platform`

**Canonical paths:**
- `backend/app/database.py`
- `backend/alembic`
- `backend/app/storage/content_store.py`

**Relevant invariants:**
- `sqlite-intentional`

## Invariant-focused Testing (`testing`)

Unit/integration tests stress concurrency, migrations, security, deterministic derivation, and a real full-stack Golden Path.

**Type:** `platform`
**State layer:** `platform`

**Canonical paths:**
- `backend/tests/test_execution_ownership_fencing.py`
- `backend/tests/test_worker_resilience.py`
- `backend/tests/test_network_security.py`
- `backend/tests/test_collection_plans.py`
- `backend/tests/test_findings.py`
- `frontend/tests-full-stack/site-ledger-golden-path.spec.ts`
- `docs/full-stack-testing.md`

## HTTP API (`api`)

FastAPI route modules expose domain operations and read models while service modules retain domain behavior.

**Type:** `platform`
**State layer:** `platform`

**Canonical paths:**
- `backend/app/api/routes.py`
- `backend/app/api/dependencies.py`
- `backend/app/api/scan_routes.py`
- `backend/app/api/source_routes.py`
- `backend/app/api/page_routes.py`
- `backend/app/api/resource_routes.py`
- `backend/app/main.py`
