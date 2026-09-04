# Context Packs

Use these as **minimum viable context** for a task. `graph.json` remains the canonical semantic map; these packs are curated retrieval shortcuts. Add graph neighbors only when the requested change crosses a boundary.

## Background jobs / worker reliability

Read first:
- `backend/app/services/background_jobs.py`
- `backend/app/services/job_lifecycle.py`
- `backend/app/services/job_handlers.py`
- `backend/app/worker.py`
- `docs/background-jobs.md`
- `backend/tests/test_execution_ownership_fencing.py`
- `backend/tests/test_worker_resilience.py`
- `backend/tests/test_job_lifecycle_registry.py`

Then, for a specific job type, add that domain's service/model/tests.

## Static crawler / scan evidence

- `backend/app/services/scan_execution.py`
- `backend/app/crawler/static_crawler.py`
- `backend/app/crawler/safe_fetch.py`
- `backend/app/services/repositories.py`
- `backend/app/models/resources.py`
- `docs/architecture.md`
- `docs/page-history-and-reuse.md`
- relevant `backend/tests/test_static_crawler.py`

## Network / SSRF / private destination rules

- `backend/app/crawler/security.py`
- `backend/app/crawler/secure_transport.py`
- `backend/app/crawler/safe_fetch.py`
- `docs/network-security.md`
- `backend/tests/test_network_security.py`

Do not modify this area from UI assumptions alone.

## URL identity

- `backend/app/services/url_identity.py`
- `backend/app/crawler/url_normalizer.py`
- `backend/app/services/repositories.py`
- `docs/url-identity-contract.md`
- `docs/url-identity-reconciliation.md`

## Scan projections

- `backend/app/services/scan_projections.py`
- `backend/app/services/projection_queries.py`
- `backend/app/models/projections.py`
- `docs/scan-projections.md`
- projection-focused tests

## Comparisons

- `backend/app/services/scan_comparisons.py`
- `backend/app/services/comparison_queries.py`
- `backend/app/models/comparisons.py`
- `docs/scan-comparisons.md`
- `backend/tests/test_scan_comparisons.py`

## Findings

- `backend/app/services/finding_detectors.py`
- `backend/app/services/finding_evaluations.py`
- `backend/app/services/findings.py`
- `backend/app/services/finding_deletion.py` for administrative delete/reset behavior
- `backend/app/api/findings_routes.py`
- `backend/app/models/findings.py`
- `docs/findings.md`
- `backend/tests/test_findings.py`
- `frontend/src/pages/site-workspace/SiteFindingsWorkspace.tsx` when changing UI/API presentation

Always check the tri-state and evidence-retention invariants before adding a detector. For
deletion/reset changes, also inspect `backend/app/services/job_types.py`, Site Intelligence, and the
recursive Source-evidence tests; reset owns derived interpretation state, never collected evidence.

## Site Intelligence

- `backend/app/services/site_intelligence.py`
- `backend/app/api/site_intelligence_routes.py`
- `docs/site-intelligence.md`
- `frontend/src/pages/site-workspace/SiteIntelligenceOverview.tsx`
- `backend/tests/test_site_intelligence.py`
- `backend/tests/test_site_intelligence_benchmark.py`

If adding a domain, preserve independent clocks.

## Collection Plans

- `backend/app/services/collection_plans.py`
- `backend/app/models/collection_plans.py`
- `backend/app/schemas/collection_plans.py`
- `backend/app/api/collection_plan_routes.py`
- `docs/collection-plans.md`
- `backend/tests/test_collection_plans.py`
- `frontend/src/pages/site-workspace/CollectionPlansWorkspace.tsx`

Treat the Plan as orchestration over native collectors, not evidence. Keep compatibility, latest
compatible observation time, and equivalent active collection separate.

## Source definitions / current inventory / AI Documents

- `backend/app/services/source_management.py`
- `backend/app/services/source_refresh.py`
- `backend/app/services/source_queries.py`
- `backend/app/services/ai_document_sources.py` when relevant
- `backend/app/models/resources.py`
- `docs/architecture.md`
- `docs/resource-inventory.md`
- `docs/ai-document-sources.md`

Treat `UrlSourceEntry` as mutable current Inventory. Do not use it as historical sitemap evidence.

## Immutable sitemap Source evidence / cross-stream Findings

- `backend/app/models/resources.py` (`SourceRefresh`, `SourceEntryObservation`)
- `backend/app/services/source_refresh.py`
- `backend/app/services/finding_evaluations.py`
- `backend/app/services/finding_detectors.py`
- `backend/app/models/findings.py`
- `backend/alembic/versions/202609030032_sitemap_finding_evidence.py`
- `docs/findings.md`
- `backend/tests/test_sources.py`
- `backend/tests/test_findings.py`
- `backend/tests/test_sitemap_finding_evidence_migration.py` when changing persistence compatibility

Always check `source-inventory-not-historical-evidence`, `recursive-sitemap-topology-frozen`, `independent-evidence-clocks`, and Finding tri-state semantics.

## Frontend Site workspace

- `frontend/src/main.tsx`
- `frontend/src/pages/site-workspace/SiteWorkspaceLayout.tsx`
- the target `site-workspace/*` surface
- its domain API client/types
- associated frontend tests

Prefer existing domain boundaries over inventing a new frontend architecture.

## Database / migrations

- target model module under `backend/app/models/`
- newest Alembic revisions
- `backend/app/database.py`
- migration-specific tests
- any deletion/retention service affected

Validate fresh upgrade, populated upgrade/downgrade when semantics matter, one head, and foreign keys.

## Full-stack behavior

- `docs/full-stack-testing.md`
- `frontend/tests-full-stack/site-ledger-golden-path.spec.ts`
- then follow the exact domain paths touched by the scenario
