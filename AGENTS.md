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
- **Source entry observation:** One immutable, duplicate-preserving URL declaration from an exact
  sitemap Source refresh, including URL-normalization provenance.
- **Resource Inventory:** Observed or HTML-referenced non-HTML WebResource evidence and references.
- **Graph:** A scan-specific representation of observed Pages and stored links.
- **Activity:** Durable background execution and worker status.
- **Evidence:** Stored responses, metadata, links, redirects, source provenance, and reuse
  provenance that support an observation.
- **Render Run:** One durable, bounded browser-evidence collection over a frozen set of Pages.
- **Rendered observation:** Immutable browser-derived evidence for one Render Run target, with
  optional historical Scan/snapshot provenance and distinct from retained static HTML.
- **Scan projection:** A deterministic, versioned, rebuildable index derived only from one terminal
  Scan's immutable static evidence. It is never the original evidence and never embeds Render
  evidence.
- **Comparison:** A deterministic relationship and versioned build comparing two terminal Scans
  from one Site while preserving coverage semantics and immutable evidence provenance.
- **Structured content:** A ContentBlob-scoped, versioned deterministic derivative representing
  source-derived heading and section structure with direct text.
- **Findings:** Persistent deterministic logical conditions with immutable assessments, typed
  evidence pointers, evidence-time lifecycle, and separate acknowledgement workflow.
- **Site Intelligence:** A read-only, non-persisted composition of current Site workspace state,
  deterministic derivatives, evidence coverage, independent domain clocks, and active work.
- **Collection Plan:** Durable orchestration provenance for one frozen, deterministic selection of
  active Pages missing compatible current evidence in exactly one collection context. It owns
  batches of native Runs/jobs but is not itself evidence, a Run, a job type, or a scheduler.

Use Page instead of WebResource in product copy. Use Observation where Snapshot would be
unnecessarily technical. Internal classes, API fields, routes, and developer documentation may use
their exact technical names.

## Current Product Boundary

Implemented capabilities include:

- Saved Sites and reusable scope.
- Static HTML scans.
- Durable background jobs.
- Sitemap, robots-discovered sitemap, and manual URL Sources.
- Immutable refresh-scoped sitemap membership evidence and composite Scan + sitemap Finding
  manifests.
- Nested AI Document Sources with immutable refresh, reference, and exact text evidence.
- URL Inventory and scan-seed provenance.
- Persistent Pages and Page observation history.
- Site-scoped Page workspaces, categories, owner labels, workflow status, and plain-text notes.
- Deterministic Page Category Rules, assignment support provenance, and automatic exclusions.
- Optional IANA Site display timezone with UTC evidence semantics.
- Deterministic occurrence-specific link roles and classification provenance.
- Exact retained HTML evidence, conditional HTTP revalidation, and parse-artifact reuse.
- ContentBlob-scoped `structured-content-v2 | canonical-document-v1` canonical document evidence,
  deterministic `structured-markdown-v1`, observation/Page inspection, and historical preparation.
- Resource Inventory for observed and referenced non-HTML Resources without general Resource-body
  storage.
- Inbound and outgoing link provenance.
- First-class bounded Render Runs with Scan-triggered, Site/Page manual, and selected-rerender
  workflows plus screenshots, rendered DOM, network, console, and Page-error evidence.
- Scan-specific 2D and 3D topology graphs.
- Immutable, versioned Scan projections for terminal result reads.
- Deterministic same-Site Scan Comparison over Pages, Resources, and Links, including coverage,
  exact/normalized source, document-content, metadata, technical states, exact drill-down, and
  persistent Page Change History.
- Scan, source, Site, and Activity lifecycle management.
- A Site Intelligence Overview with explicit active-Page denominators and independent static,
  Render, Performance, Accessibility, Structured Content, Source, and Comparison provenance.
- Current-evidence Collection Plans for Performance, Accessibility, Render, and Structured Content,
  with deterministic target checksums, fixed native batching, cancellation, and Plan history.
- First-class deterministic static Page Findings for HTTP/fetch failures, noindex directives,
  conflicting indexability, missing titles, canonical validity/cardinality/target failures, and
  current non-HTML representations. Evaluation history persists complete per-detector diagnostics
  even though clean and unknown logical outcomes remain sparsely persisted.

Additional cross-domain Finding evidence beyond static Scan and immutable sitemap Source evidence,
investigation records, GA4/Search Console, section-level comparison, structured-content full-text
search, Resource/PDF body extraction,
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
- crawler.config owns authoritative static/general Scan bounds and runtime validation.
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
- crawler.canonical_document, services.structured_content,
  services.structured_content_queries, api.structured_content_routes,
  HtmlStructuredContentArtifact, HtmlStructuredContentNode, and historical
  HtmlStructuredContentSection own structured Page content.
- browser.*, models.rendered, services.render_runs, services.rendered_capture,
  services.rendered_queries, and api.render_routes own bounded browser capture, durable Render Runs,
  rendered observations, and rendered artifacts.
- crawler.resource_classification, ResourceSnapshot/WebResource resource fields,
  ResourceReferenceOccurrence, and services.resource_queries own Resource Inventory classification,
  evidence, and reads.
- services.page_queries owns persistent Page catalogs and observation history.
- schemas.site_intelligence, services.site_intelligence, and api.site_intelligence_routes own the
  read-only Site Intelligence composition model. It must use active SitePages as the operational
  Page denominator, retain independent evidence clocks, and never prepare or persist derivatives.
- models.collection_plans, services.collection_plans, schemas.collection_plans, and
  api.collection_plan_routes own missing-current selection and orchestration provenance. Selectors
  are shared with Site Intelligence. Plans must queue existing native collectors and job types;
  they must not become evidence, duplicate collection logic, or introduce scheduling semantics.
- services.site_pages, services.page_categories, and services.notes own Site-scoped Page workflow.
- services.category_rules and services.category_rule_evaluator own automatic Category provenance,
  preview, reconciliation, and evaluation history.
- crawler.link_roles owns pure deterministic link-role classification.
- services.cache_policy and services.parse_artifacts own conservative reuse.
- Content-addressed and globally unique get-or-create paths must isolate insert races in nested
  savepoints, reload the committed winner, and never roll back unrelated caller work. Local blob
  files must be deterministically encoded, atomically published, and leave no temporary files.
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
- RenderRun
- RenderRunTarget
- HtmlStructuredContentArtifact
- HtmlStructuredContentSection
- HtmlStructuredContentNode
- PageCategoryRule
- ScanProjectionBuild
- ScanProjectionState
- ScanComparison
- ScanComparisonBuild
- UrlSource

WebResource is the persistent Page identity. ResourceSnapshot is one Page observation. Reused
responses still create new observations and current-scan link occurrences.

An active non-completed URL identity migration, missing active migration provenance, or an
inconsistent identity state places product runtime in fail-closed maintenance mode. Runtime
identity creation must never fall back to V1, normal API traffic must remain unavailable, and
workers must not claim jobs until explicit recovery completes. Migration status/recovery tooling
remains available. New resource-creation and job-claim paths must not bypass these guards.

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

Current deterministic compatibility identifiers include `html-parser-v4-rel-token-semantics`,
`structured-content-v2` with `canonical-document-v1`, `structured-markdown-v1`,
`document-content-v2`, `scan-comparison-v3`, and
`scan-projection-v2`. Treat identity changes as explicit versioned compatibility changes, not
incidental refactors.

Structured-content identity describes the ContentBlob-scoped canonical representation. Relative
URLs remain unresolved; DOM paths are provenance; Markdown is a renderer rather than canonical
truth. Preserve V1 artifacts as historical derivative evidence and never relabel or bulk rewrite
them when a new current representation is introduced.

Scan projection algorithm provenance describes projection computation. Do not encode upstream
evidence-producer versions when those versions are already preserved on their own artifacts. Keep
historical projection identities readable through explicit compatibility rules rather than
rewriting or rebuilding retained projections merely to rename provenance.

Current Scan projections derive only from static Scan evidence. RenderRun completion, rerender, or
evidence deletion must not change projection rows or checksums. Scan Page reads may compose current
retained Render evidence at query time. Current Scan comparisons and Scan-based Page Change History
must not interpret independent Render lifecycle differences as Scan changes. Historical projection
and comparison builds remain stored under their original versions and are never relabelled.

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
- Reject out-of-policy configuration without clamping; API and runtime must use the same policy.
- Revalidate persisted configuration before network or browser work. Historical reads remain
  available without rewriting or revalidating retained Scan evidence.
- Record external and excluded links without queueing them.
- Preserve duplicate link occurrences and anchor provenance.
- Treat HTTP error statuses as observations rather than crawler exceptions.

New schedulers, agents, CLI commands, and internal callers must not bypass crawl or browser policy
validation. See `docs/scan-configuration-policy.md`.

A scan with Page-level failures normally completes with errors rather than failing as a whole.

Conditional requests must use the same safe fetcher, redirect checks, scope checks, limits, and SSRF
protections as full requests. Parse artifact identity includes content blob, parser version, parser
configuration, and URL resolution base.

HTML `rel` attributes are case-insensitive token lists for derived semantics. Equivalent token sets
must produce deterministic results independent of source token order and `PYTHONHASHSEED`; never
choose semantic output by iterating an unordered set. Preserve raw `rel` strings as evidence. Parser
semantic corrections require a parser-version bump, and historical artifacts must never be silently
reinterpreted under a newer parser contract.

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
- Treat browser technical success and requested-Page success as separate outcomes. Classify the
  final main-document response before collecting normal Page screenshots or DOM. HTTP errors retain
  exact status and bounded diagnostics but receive no normal Page artifacts by default.
- Rate limiting is one HTTP non-success subtype. Repeated explicit throttling must use a bounded,
  host-scoped policy; circuit-skipped targets must be retained as not attempted and must not receive
  copied status, network, or artifact evidence. Browser failures never invalidate valid static Scan
  evidence.
- Renderer semantic changes require versioned new observations. Never rewrite historical rendered
  observations or counters to apply a newer outcome policy.
- A Render Run freezes its targets and effective configuration before execution. Each target may
  produce at most one terminal immutable observation; rerendering always creates a new Run.
- Standalone Render Runs have no Scan snapshot provenance. Scan provenance is optional, while the
  frozen WebResource and requested URL remain authoritative target identity.
- A Scan-triggered Render Run may be Site-less only while its ad-hoc source Scan remains its durable
  owner. Saved-Site Runs survive Scan deletion; Site-less Runs are deleted with their source Scan
  using reference-aware artifact cleanup. Never leave an ownerless Site-less Run.
- `renderer-v2` remains the capture contract. Rate-limit circuits are Run-local, and later SitePage
  suppression must not rewrite or hide retained Render Run evidence.
- New manual targets must resolve to active Site Pages. URL identity reconciliation must include
  Render Run targets and observations, and artifact deletion must remain reference-aware.
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

`WebResource` is persistent global URL identity; changing normalization semantics is a compatibility
change. Current behavior is named `url-normalization-v1`. Never change URL identity in an incidental
refactor or casually decode reserved percent-encoded delimiters into structural delimiters.
Site-specific query suppression is policy and must remain distinct from generic syntax
normalization. Provider-returned URLs never redefine Site Ledger identity. Any normalization change
requires retained-data impact analysis before migration: immutable evidence may be mechanically
attributable, but splitting a Page can make mutable SitePage workspace metadata ambiguous.
Rebuildable projections and comparisons are not authoritative migration evidence. See
[URL identity contract](docs/url-identity-contract.md).

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
section-level comparison by silently changing `scan-comparison-v3`; any future section comparison
must define and version its deterministic identity and matching semantics explicitly.

Comparison never rewrites evidence. Exact evidence remains exact, normalization remains narrow and
versioned, and absence means "Not observed in Target", not automatic removal. Technical change is
distinct from substantive document-content change. Comparison is deterministic interpretation of
evidence, not an LLM Finding; Findings and AI interpretation must remain downstream.

Finding version identities are semantic contracts. Change `detector_identity` for detector
semantics, `logical_key_version` for logical Finding identity, `detector_bundle_identity` for
production detector membership or ordering, and `evaluator_version` for evaluator execution
semantics. Unchanged identities after a semantic change are a compatibility bug. The deterministic
detector manifest checksum is a second safety boundary included in evaluation input identity; it
does not replace explicit bundle versioning and must never be derived from source-code hashes.

Finding topology uses immutable, duplicate-preserving `ResourceOccurrence` anchor evidence and
same-Scan target snapshots. Eligibility must preserve frozen scope decisions and link roles;
detectors must not fetch, infer redirect-mediated edges, substitute historical targets, or include
external and embedded-resource references. Persist only a fixed deterministic occurrence/target
sample, with explicit total counts and truncation metadata. Scan deletion tombstones typed evidence
reads without deleting Finding or assessment history.

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

AppShell owns global layout and navigation, not feature data. Site-scoped product areas belong
under the Site workspace and use the typed declarative Site navigation model; navigation reflects
implemented features only. Feature pages must not recreate global or Site navigation. Detail pages
preserve their parent product-area context, while Scan-specific evidence remains in Scan context
and persistent Pages remain visibly distinct from Scan Observations. Add a Site navigation entry
deliberately when a major Site capability becomes real. Extract components by responsibility, not
an arbitrary line-count threshold. Keep UI-only navigation preferences local rather than storing
them as evidence or domain state.

Stored or scanned text must be rendered as escaped React text. Do not use dangerouslySetInnerHTML
for captured content.

Performance evidence is external provider evidence, not Scan evidence. Keep PageSpeed Lab and CrUX
Field distinct; exact provider payloads are authoritative and normalized metrics are versioned
derivatives. Performance observations are immutable historical records. Provider URL normalization
must not rewrite `WebResource`, and unavailable CrUX data is not automatically a failure. Never
persist or expose provider keys in evidence, logs, checksums, or APIs. New provider adapters require
fixed trusted endpoints, bounded networking, and sanitized failures. Performance does not modify
`scan-comparison-v3`; Findings, regressions, and scheduling remain downstream work.

Provider HTTP success is not equivalent to usable normalized evidence. PageSpeed adapter v2 requires
at least one recognized Performance metric for `ready`; a parseable response with none is
`failed/no_usable_performance_metrics`. Retain raw provider payloads and parsed provenance on failed
evidence. Provider contract changes require adapter-version provenance and must never silently
rewrite observations produced under an earlier adapter version.

Accessibility observations are independent evidence collected at their own time, not Scan browser
evidence. Automated results do not establish WCAG conformance and must never produce a compliance
boolean or score. Keep axe-core version, exact detector checksum, effective ruleset identity,
responsive profile, and browser provenance with every observation. Exact raw detector payloads are
authoritative; violation and incomplete rows are versioned normalized detector evidence, not Site
Ledger Findings. Preserve Needs Review separately from violations and Desktop separately from
Mobile. Detector updates create later evidence and never rewrite history. Accessibility must reuse
the hardened browser networking policy, never load detector code from a runtime CDN, belongs to
persistent Page history rather than Scan Observation, and must not alter `scan-comparison-v3`.

Raw Performance and Accessibility evidence is authoritative but is not the default result view.
Human-readable details must be deterministic, read-time traceable derivatives and must retain exact
raw routes. CrUX unavailable means insufficient qualifying provider data, not collection failure;
URL and origin scope must remain distinct, and origin context must be labeled. Frontend workload
previews never replace backend validation. Performance presentation never mutates payloads.
Accessibility Violations and Needs Review remain distinct detector evidence, not Findings.

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
- For unfamiliar or cross-domain work, start with `docs/brain/CONTEXT_PACKS.md` and the relevant
  entries in `docs/brain/INVARIANTS.md`. The checked-in Site Ledger second brain is a maintained
  context/navigation layer, not authoritative source code; current source, migrations, and tests
  win when they disagree.
- Update affected second-brain files in the same PR when a change materially alters a domain
  boundary, durable architectural invariant, major workflow, semantic graph relationship,
  architecture-relevant compatibility/version identity, or recommended context-pack assumptions.
  Ordinary internal refactors and bug fixes do not require mechanical graph churn. Update
  `GRAPH.md`/`graph.json` for semantic relationships, `DOMAINS.md` for ownership and canonical paths,
  `WORKFLOWS.md` for major lifecycles, `INVARIANTS.md` only for durable constraints,
  `CONTEXT_PACKS.md` for minimum authoritative file sets, `AGENT_GUIDE.md` for retrieval policy,
  `FRONTIER.md` for material roadmap changes, `DESIGN_NOTES.md` for context-map design, and the
  brain `README.md` for orientation/provenance.
- Prefer existing patterns and typed boundaries.
- Make the smallest complete change that satisfies the request.
- Never run substantial synchronous job-domain computation directly on the asyncio worker event
  loop, and never pass a live SQLAlchemy Session across an `asyncio.to_thread` boundary.
- Successful authenticated job progress must renew the current lease atomically. Expired-job
  recovery must revalidate current running/expiry state before taking terminal recovery ownership.
- A stale lease token may never heartbeat, report progress, complete, or fail a job. Job and worker
  heartbeats are operational liveness state, not permanent event spam. Confirmed lease loss also
  removes authority over domain execution: blocking work must stop at its next bounded checkpoint
  without replacing recovery's domain state. Execution ownership governs every durable domain
  mutation, not only terminalization. After external work, fence ownership and apply its domain
  mutation in the same transaction before commit. Domain and BackgroundJob terminalization must
  likewise share a guarded ownership transaction.
- Scan, Source Refresh (including recursive sitemap and AI Document execution), Scan Projection,
  Scan Comparison, Category Rule, Structured Content, Performance, Accessibility, and Render
  persistence fence each job-owned transaction. Finding evaluation uses its equivalent guarded
  single-transaction ownership check. New durable job handlers must preserve one of these patterns.
- Keep `UrlSourceEntry` as mutable current Inventory state. Historical Source evidence must use an
  immutable refresh-scoped observation and a frozen evaluation manifest; never present a current
  Inventory row as evidence for an earlier refresh.
- Recursive sitemap evidence must retain ordered child refresh IDs on the exact parent refresh.
  Finding manifests select explicit roots and freeze those refresh trees; mutable discovered-child
  Source state must not determine historical or current membership.
- Finding history is durable by default. Explicit individual deletion may discard one Finding's
  lifecycle while retaining its completed evaluation; explicit Site reset may discard the complete
  rebuildable Finding/evaluation layer while preserving all collected evidence. Both operations
  must fail closed while Site Finding evaluation work is queued or running.
- Queued native cancellation must commit BackgroundJob and native terminal state together. Required
  post-success work may use an idempotent recovery protocol when its domain terminal commit is an
  earlier transaction; recovery must ensure that work before reconciling the BackgroundJob.
- Do not compensate for event-loop starvation by merely increasing job lease timeout defaults.
- Avoid unrelated refactors and dependency upgrades.
- Do not create fake data, placeholder APIs, or controls that do nothing.
- Configuration surfaces must distinguish enforced controls from compatibility-only or inactive
  settings. New work must reject a requested safety behavior when the runtime cannot enforce it.
- Static request timeout means one aggregate wall-clock budget across redirects and body streaming,
  not a fresh timeout for each network operation.
- Never silently truncate parser anchors or resource-reference evidence. A future fanout bound
  requires explicit persisted truncation state and counts before it may drop occurrences.
- Preserve database and local-data compatibility.
- Keep `WebResource` as normalized URL identity; representation kind belongs to Scan evidence.
- Do not treat successful non-HTML responses as crawl failures or store their response bodies.
- Keep Graph topology Page-link based and rendered capture evidence separate from static parsing.
- Keep deterministic Scan comparisons versioned above immutable static Scan projections; never
  include independent Render evidence or label crawl absence as website removal.
- Update README and focused documentation when behavior or architecture changes.
- Any PR that materially changes the implemented product boundary, architecture ownership, or
  compatibility/version identifiers documented here must update `AGENTS.md` in the same PR.
- Never commit secrets, credentials, local databases, captured HTML, build output, or dependency
  caches.
- Use the Artsen repository-local Git identity for commits in this repository.
- Global WebResource identity is `(normalization_version, normalized_url)`; every URL lookup must
  include the version. V1 historical identities remain legitimate and must not be reused as V2.
- V2 is Site-independent. Site query suppression is crawl/source policy and must never redefine a
  global V2 identity.
- Existing populated databases remain V1 until verified migration activation; fresh databases use
  V2. Operator decisions must never be guessed and candidate merges fail closed.
- Reassign immutable evidence only from retained requested/resolved identity provenance. Provider
  targets, final URLs, and redirects do not redefine Page ownership.
- Never guess split Page workspace state. Keep insufficient provenance explicit and prefer an honest
  grandfathered V1 identity to invented history.
- Reconciliation manifests and reports are local sensitive artifacts. Never commit them or apply a
  stale manifest.
- Real identity migration requires no active mutating jobs, a verified SQLite backup plus content
  store inventory, and post-migration invariants. Rebuild projections/comparisons from evidence.
- Full manifests are sensitive local artifacts. Migration must not rewrite immutable evidence bytes.
- Performance and Accessibility observations are immutable while retained but may be explicitly
  deleted by the user; terminal Run collection counters must never be rewritten by observation
  deletion, and retention counts derive from currently retained observations.
- Delete raw payload blobs/files only after the last retained reference. Shared payloads survive
  partial deletion, and concurrent content-addressed inserts must reconcile to the committed winner.
- Accessibility rule/node evidence is owned by its observation and disappears with it. Observability
  deletion must never delete `WebResource` or `SitePage` identity or affect the other evidence domain.
- Active collection blocks deletion and GC in that domain. Commit database deletion before
  best-effort file removal; report cleanup failures without resurrecting evidence.
- Full Site deletion must apply the same reference-aware observability cleanup and must not leak
  unreferenced payload records or files.
- Never delete a `RenderRunTarget` solely because its `RenderedObservation` was deleted. A target
  with `evidence_deleted_at` is deleted evidence; a target without an observation or marker was
  never attempted. Rerendering always creates a new Run and never restores the old observation.
- Rendered evidence deletion never rewrites historical Run counters or deletes Pages, Scans,
  snapshots, Performance, or Accessibility evidence. Current retention counts are query-derived.
- Rendered `ArtifactBlob` deletion is reference-aware, and physical files are removed only after
  committed database deletion. Legacy Scan-bound browser evidence remains independently deletable.
- Site rendered purge owns Site Runs plus legacy observations from that Site's Scans. Scan rendered
  purge owns legacy observations plus Site-less ad-hoc Runs only; independently Site-owned Runs
  survive. Active affected Runs always block deletion.
- Never delete immutable Scan evidence to change mutable Site membership. `SitePage` workspace
  state is distinct from workflow status, and later observations must not reactivate a suppressed
  Page.
- URL Inventory is Source truth plus Site-scoped policy. Suppression must preserve Source
  declarations, survive refresh, retain multi-source grouping, and affect only Inventory-derived
  seeding rather than ordinary crawler discovery.
- Manual URL removal retains its `UrlSourceEntry` provenance as non-current. Page and Inventory
  suppression must leave historical evidence queryable, and future Findings must explicitly honor
  active or suppressed subject policy.
- Remove and Delete are distinct lifecycle operations. Page Remove preserves `SitePage`
  organization and later observations must not reactivate it; Page Delete may destroy mutable
  `SitePage` organization but never Scan evidence.
- Inventory Remove is persistent Site suppression policy. Inventory Delete deactivates all current
  contributors for the grouped identity, clears suppression, and must never physically delete
  `UrlSourceEntry` or break historical `ScanSeedOrigin` source-entry references.
- Source refresh may reactivate Inventory-deleted entries, preferably reusing their identity, but
  rediscovery must not reactivate suppressed entries. UI Removed views mean suppressed and
  restorable, not deleted.
- Grouped Inventory bulk semantics are derived and validated server-side from representative entry
  IDs; clients do not enumerate contributors as authority.

## Pull Request Format

Pull requests should describe:

- Summary.
- User-visible behavior.
- Architecture and data-model impact.
- Compatibility and security considerations.
- Tests and checks run.
- Known limitations.
- Explicitly excluded follow-up work.
