# Codex Instructions

## Project Identity

This repository contains **Site Ledger**.

- Repository: https://github.com/Artsen/site-ledger
- Product tagline: A historical record of your website.
- Repository slug: site-ledger
- Python distribution: site-ledger-backend
- Frontend package: site-ledger-frontend

Site Ledger is a local-first website intelligence platform that inventories Sites, preserves crawl
evidence, and tracks Page observations over time. It is larger than a crawler: the crawler is one
collection subsystem inside a persistent Site, Page, observation, source, graph, evidence, and
Activity model.

Use Site Ledger in user-facing prose. Use site-ledger for repository and distribution slugs. Use
site_ledger only when an underscore-based technical identifier is required. Do not rename the
Python app package.

## Product Vocabulary

- **Site:** A saved website property with reusable scope and configuration. The internal model is
  WebsiteProperty.
- **Page:** A persistent normalized URL identity represented by WebResource.
- **Observation:** One scan-specific ResourceSnapshot of a Page.
- **Scan:** One bounded collection run that produces observations.
- **Source:** A sitemap, robots-discovered sitemap, manual URL source, or AI Document Source.
- **Inventory:** Current URL candidates declared by Sources; this is input provenance, not observed
  Resource evidence.
- **Resource Inventory:** Observed or HTML-referenced non-HTML WebResource evidence and references.
- **Graph:** A scan-specific representation of observed Pages and stored links.
- **Activity:** Durable background execution and worker status.
- **Evidence:** Stored responses, metadata, links, redirects, source provenance, and reuse
  provenance that support an observation.
- **Rendered observation:** Browser-derived evidence associated with a Page observation, distinct
  from retained static HTML.
- **Scan projection:** A deterministic, versioned, rebuildable index derived from one terminal
  Scan's immutable evidence. It is never the original evidence.
- **Comparison:** A deterministic relationship and versioned build comparing two terminal Scans
  from one Site while preserving coverage semantics and immutable evidence provenance.
- **Structured content:** A ContentBlob-scoped, versioned deterministic derivative representing
  source-derived heading and section structure with direct text.

Use Page instead of WebResource in product copy. Use Observation where Snapshot would be
unnecessarily technical. Internal classes, API fields, routes, and developer documentation may use
their exact technical names.

## Current Product Boundary

Implemented capabilities include:

- Saved Sites and reusable scope.
- Static HTML scans.
- Durable background jobs.
- Sitemap, robots-discovered sitemap, and manual URL Sources.
- Nested AI Document Sources with immutable refresh, reference, and exact text evidence.
- URL Inventory and scan-seed provenance.
- Persistent Pages and Page observation history.
- Site-scoped Page workspaces, categories, owner labels, workflow status, and plain-text notes.
- Deterministic Page Category Rules, assignment support provenance, and automatic exclusions.
- Optional IANA Site display timezone with UTC evidence semantics.
- Deterministic occurrence-specific link roles and classification provenance.
- Exact retained HTML evidence, conditional HTTP revalidation, and parse-artifact reuse.
- ContentBlob-scoped `structured-content-v1` heading, hierarchy, region, and direct-text evidence,
  with observation/Page inspection and historical preparation.
- Resource Inventory for observed and referenced non-HTML Resources without general Resource-body
  storage.
- Inbound and outgoing link provenance.
- Optional bounded browser-rendered observations, screenshots, rendered DOM, network, console, and
  Page-error artifacts associated with static observations.
- Scan-specific 2D and 3D topology graphs.
- Immutable, versioned Scan projections for terminal result reads.
- Deterministic same-Site Scan Comparison over Pages, Resources, and Links, including coverage,
  exact/normalized source, document-content, metadata, technical states, exact drill-down, and
  persistent Page Change History.
- Scan, source, Site, and Activity lifecycle management.

Findings and investigation records, PageSpeed/CrUX, accessibility observations, GA4/Search Console,
section-level comparison, structured-content full-text search, Resource/PDF body extraction,
rendered-DOM structured extraction, environment or cross-Site comparison, scheduling and
notifications, embeddings, RAG, and semantic/LLM interpretation are future areas. Describe them as
planned or designed to support, never as current behavior.

## Required Stack

- Backend: Python, FastAPI, SQLAlchemy 2, Alembic, SQLite, HTTPX, and lxml.
- Frontend: React, TypeScript, Vite, TanStack Query, and Tailwind CSS.
- Backend tests: pytest.
- Frontend tests: Vitest and Testing Library.
- End-to-end tests: Playwright.
- Python quality: Ruff and mypy.
- Frontend quality: ESLint and TypeScript.

SQLite is the initial database. Prefer normal portable SQLAlchemy solutions over SQLite-only
behavior. Keep storage behind the existing content-store abstraction.

## Architecture Boundaries

- crawler.url_normalizer owns URL normalization.
- crawler.scope owns deterministic scope decisions.
- crawler.security and crawler.safe_fetch own the SSRF and bounded-fetch boundary.
- crawler.html_parser owns best-effort static HTML extraction.
- crawler.static_crawler owns breadth-first collection and observation persistence.
- storage.content_store owns exact compressed response evidence.
- services.background_jobs owns queue, lease, heartbeat, progress, cancellation, and worker health.
- services.job_handlers adapts jobs to domain execution.
- services.site_* owns saved-Site behavior and queries.
- services.source_* owns Sources, refresh, and Inventory.
- parsers.ai_documents and storage.ai_document_store own deterministic AI index parsing and exact
  AI-document evidence; this evidence never uses ResourceSnapshot or Resource Inventory bodies.
- services.scan_* owns scan inputs, queries, and deletion.
- services.source_comparison owns exact/normalized source analysis and versioned deterministic
  document-content extraction; these layers must remain distinct.
- services.scan_projections owns versioned builds, validation, atomic activation, and fallback
  metadata. services.projection_queries owns projection-backed Page, Resource, and graph reads.
- models.comparisons, services.scan_comparisons, services.comparison_queries, and
  api.comparison_routes own deterministic Comparison builds, materialized results, coverage,
  drill-down, and Page Change History.
- crawler.structured_content, services.structured_content,
  services.structured_content_queries, api.structured_content_routes,
  HtmlStructuredContentArtifact, and HtmlStructuredContentSection own structured Page content.
- browser.*, models.rendered, services.rendered_capture, services.rendered_queries, and api.routes
  own bounded browser
  capture, rendered observations, and rendered artifacts.
- crawler.resource_classification, ResourceSnapshot/WebResource resource fields,
  ResourceReferenceOccurrence, and services.resource_queries own Resource Inventory classification,
  evidence, and reads.
- services.page_queries owns persistent Page catalogs and observation history.
- services.site_pages, services.page_categories, and services.notes own Site-scoped Page workflow.
- services.category_rules and services.category_rule_evaluator own automatic Category provenance,
  preview, reconciliation, and evaluation history.
- crawler.link_roles owns pure deterministic link-role classification.
- services.cache_policy and services.parse_artifacts own conservative reuse.
- services.graph_config owns graph capabilities and limits.
- services.graph_queries owns scan-specific topology queries and aggregation.
- app.api.routes exposes typed APIs.

Keep graph adapters and renderers separate. Keep network, parsing, normalization, scope,
persistence, and storage concerns separate. Do not introduce speculative plugin systems or unused
abstractions.

## Domain Stability

Do not rename these models or their tables for branding:

- WebsiteProperty
- WebResource
- ResourceSnapshot
- ResourceOccurrence
- ContentBlob
- HtmlParseArtifact
- Scan
- BackgroundJob
- RenderedObservation
- RenderedArtifact
- HtmlStructuredContentArtifact
- HtmlStructuredContentSection
- PageCategoryRule
- ScanProjectionBuild
- ScanProjectionState
- ScanComparison
- ScanComparisonBuild
- UrlSource

WebResource is the persistent Page identity. ResourceSnapshot is one Page observation. Reused
responses still create new observations and current-scan link occurrences.

Do not rename API paths, background job types, blob keys, migration IDs, stored directories, query
parameters, database filenames, or local-storage keys solely for product language.

No Alembic migration should be added for a branding-only change. For all model changes, keep Alembic
migrations synchronized with models and verify both upgrade and alembic check.

## Compatibility Identifiers

The following legacy technical identifiers are intentionally retained:

- SCANNER_ environment-variable prefix.
- sqlite:///../data/scanner.db default database URL.
- WebsiteScanner/0.1 default crawler user agent.
- website-scanner.scan.preferences frontend local-storage key.
- Historical migration names that contain scanner.

Preserve these unless a dedicated compatibility migration is explicitly designed. A rename must
never make existing local data appear missing or silently discard saved preferences.

Current deterministic compatibility identifiers include `html-parser-v3-resource-references`,
`structured-content-v1` with `default-v1`, `document-content-v2`, `scan-comparison-v2`, and
`scan-projection-v1`. Treat identity changes as explicit versioned compatibility changes, not
incidental refactors.

## Crawl Behavior

The crawler performs breadth-first HTTP GET traversal. It must:

- Never submit forms or execute JavaScript.
- Preserve redirect chains and re-evaluate scope after each redirect.
- Validate each destination against SSRF protections.
- Record nofollow and noindex without treating either as an automatic crawl exclusion.
- Save partial observations when individual Pages fail.
- Deduplicate fetches by normalized URL.
- Keep raw discovered, normalized, requested, and final URLs distinct.
- Enforce Page, depth, timeout, redirect, response-size, and delay limits.
- Record external and excluded links without queueing them.
- Preserve duplicate link occurrences and anchor provenance.
- Treat HTTP error statuses as observations rather than crawler exceptions.

A scan with Page-level failures normally completes with errors rather than failing as a whole.

Conditional requests must use the same safe fetcher, redirect checks, scope checks, limits, and SSRF
protections as full requests. Parse artifact identity includes content blob, parser version, parser
configuration, and URL resolution base.

Do not change crawler behavior as part of a product rebrand.

## Security Requirements

Treat crawling and source refresh as SSRF boundaries:

- Allow only HTTP and HTTPS.
- Block loopback, link-local, and private network destinations by default.
- Recheck resolved destinations after redirects.
- Never forward browser cookies or credentials.
- Public crawling requires a positive globally routable complete-answer policy. Static destination
  validation must remain bound to the actual socket target.
- Never restore ambient HTTP(S) or ALL_PROXY inheritance for untrusted fetches.
- Private-network opt-in permits destinations; it never disables URL, credential, redirect, or
  response safety.
- Browser byte limits use observed transfer, not declared Content-Length alone. Bump browser policy
  or capture-schema provenance when their semantics change.
- Never claim Chromium DNS pinning unless the actual browser connection is constrained. Keep
  hostile-network cases in focused lower-level tests rather than the Golden Path.
- Enforce timeout, redirect, response-size, Page, depth, and source-expansion limits.
- Parse sitemap XML without networked DTD or entity loading.
- Bound compressed-source decompression.
- Never execute scanned HTML.
- Return stored HTML as escaped text or text/plain.

Authenticated and private-network crawling require explicit future design. Do not weaken these
boundaries for local convenience.

## Persistence And Lifecycle

Exact HTML bytes are SHA-256 addressed, gzip-compressed, and deduplicated through the content store.
Do not put large HTML bodies directly into observation rows.

Deletion is reference-aware. Preserve blobs and WebResource rows referenced by another observation,
occurrence, source entry, or scan seed. Commit database cleanup before deleting physical blob files.
Reject deletion while active background jobs can still mutate the target.

Saved-site scans copy effective scope. Editing a Site must not mutate historical scans. Inventory is
input provenance, not a replacement for scan observations.

## Deterministic Derivative Rules

Raw retained HTML remains authoritative evidence. Structured content is derived from exact
ContentBlob identity under a versioned extractor/configuration identity. It is not mutable Site or
Page metadata, does not replace HtmlParseArtifact, and does not apply comparison normalization.
RequestId and TimeStamp values preserved by structured content therefore remain distinct from the
narrow `document-content-v2` operational-template semantics.

Structured section database IDs are artifact-local, not stable cross-Scan identities. Do not add
section-level comparison by silently changing `scan-comparison-v2`; any future section comparison
must define and version its deterministic identity and matching semantics explicitly.

Comparison never rewrites evidence. Exact evidence remains exact, normalization remains narrow and
versioned, and absence means "Not observed in Target", not automatic removal. Technical change is
distinct from substantive document-content change. Comparison is deterministic interpretation of
evidence, not an LLM Finding; Findings and AI interpretation must remain downstream.

## Graph Rules

The Graph is read-only and scan-specific. Nodes represent observations, with optional distinct
unfetched Page boundary nodes. Edges aggregate stored page_link occurrences, while detailed
occurrences remain duplicate-preserving and paginated.

services.graph_config is authoritative for limits and capabilities. Filter, rank, aggregate, and
limit in SQL before loading large object collections. Avoid one query per node or edge.

Do not persist force-layout coordinates, camera state, selection, exports, or presentation settings.
Keep 2D and 3D renderers lazy and isolated from shared graph state. Browser-rendered evidence stays
separate from graph topology; semantic layouts remain future work and are not reasons to alter
current topology semantics.

## Frontend Rules

Keep the dashboard restrained, dense, and operational. Reuse existing components and styling.
Maintain visible focus states, sufficient contrast, meaningful document titles, accessible
navigation labels, and non-canvas alternatives for graph exploration.

Stored or scanned text must be rendered as escaped React text. Do not use dangerouslySetInnerHTML
for captured content.

Preserve URL-backed tab, filter, pagination, graph, and presentation state. Preserve the existing
local-storage preference key unless a read-old/write-new migration is implemented.

## Testing

Add focused automated coverage with behavior changes.

Backend coverage should include URL normalization, scope, safe redirects, response limits, HTML
parsing, content storage, scan lifecycle, Sites, Sources, Inventory, jobs, graph queries, Page
history, and reuse.

Frontend coverage should include form validation, navigation, pagination, loading/error/empty
states, Page and observation details, source workflow, worker states, graph controls, accessibility,
and document titles. Playwright should keep major workflows reachable.

The Golden Path is the canonical real-stack regression test. It must use a deterministic local
fixture and must not mock Site Ledger APIs, persistence, jobs, crawling, projections, or comparisons.
Never use production data or a public fixture. Keep the workflow small and stable; cover expensive
edge cases at lower levels when possible. Core lifecycle changes should evaluate whether Golden Path
expectations need updating, and full-stack failures must be debugged rather than hidden with retries.

Run relevant checks before completion:

~~~powershell
cd backend
uv sync --extra dev --locked
uv run --extra dev --locked pytest
uv run --extra dev --locked ruff check .
uv run --extra dev --locked ruff format --check .
uv run --extra dev --locked mypy app
uv run --extra dev --locked alembic upgrade head
uv run --extra dev --locked alembic check
~~~

~~~powershell
cd frontend
npm ci
npm run lint
npm run typecheck
npm run test
npm run build
npm run e2e
~~~

Do not disable checks or weaken tests to force passing results.

## Reproducible Tooling

- `backend/pyproject.toml` declares compatible direct requirements; `backend/uv.lock` is the
  authoritative resolved environment for development and CI. Update both intentionally when a
  direct requirement changes, and use `uv run` for repository automation.
- `frontend/package.json` declares requirements; `frontend/package-lock.json` plus `npm ci` is the
  authoritative frontend environment. New dependencies require the corresponding lock update.
- GitHub Actions enforces the stable `Backend`, `Frontend`, `Playwright`, and disposable full-stack
  `Golden Path` checks on pull requests to `main` and pushes to `main`.
- CI must use disposable databases and storage, require no production data or secrets, and avoid
  public-network crawl evidence. Benchmarks remain manual diagnostics.

## Working Rules

- Read this file and inspect the repository before editing.
- Prefer existing patterns and typed boundaries.
- Make the smallest complete change that satisfies the request.
- Avoid unrelated refactors and dependency upgrades.
- Do not create fake data, placeholder APIs, or controls that do nothing.
- Preserve database and local-data compatibility.
- Keep `WebResource` as normalized URL identity; representation kind belongs to Scan evidence.
- Do not treat successful non-HTML responses as crawl failures or store their response bodies.
- Keep Graph topology Page-link based and rendered capture evidence separate from static parsing.
- Keep deterministic Scan comparisons versioned above immutable Scan projections; never label crawl
  absence as website removal.
- Update README and focused documentation when behavior or architecture changes.
- Any PR that materially changes the implemented product boundary, architecture ownership, or
  compatibility/version identifiers documented here must update `AGENTS.md` in the same PR.
- Never commit secrets, credentials, local databases, captured HTML, build output, or dependency
  caches.
- Use the Artsen repository-local Git identity for commits in this repository.

## Pull Request Format

Pull requests should describe:

- Summary.
- User-visible behavior.
- Architecture and data-model impact.
- Compatibility and security considerations.
- Tests and checks run.
- Known limitations.
- Explicitly excluded follow-up work.
