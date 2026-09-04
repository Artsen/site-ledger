# Site Ledger Architecture

Site Ledger is a local-first website intelligence application with explicit collection,
persistence, query, background-execution, and presentation boundaries.

## Runtime Shape

~~~text
React application
      |
FastAPI routes
      |
Domain services ---- SQLAlchemy models ---- SQLite
      |                                      |
Durable jobs ---- standalone worker     Alembic migrations
      |
Scan coordinator ---- static crawler ---- local content store
      |
Optional Chromium capture ---- local artifact store
~~~

The frontend, API, and worker are separate processes. The API creates durable records and queues
work. The worker claims jobs and invokes domain services. SQLite and local gzip storage are the
current implementations.

## API Router Structure

`backend/app/api/routes.py` is the stable composition and compatibility surface for the older core
API. It includes focused HTTP adapters from:

```text
app/api/
|-- routes.py                 composition and compatibility exports
|-- dependencies.py           shared typed database/query dependencies
|-- system_routes.py          health
|-- job_routes.py             jobs, worker health, and events
|-- scan_routes.py            Scan lifecycle, inputs, deletion, and Page results
|-- site_routes.py            Site CRUD
|-- source_routes.py          Sources, refreshes, and current Inventory
|-- page_routes.py            persistent Pages and Page Categories
|-- note_routes.py            Site, Scan, and Page notes
|-- projection_routes.py      Scan Projection lifecycle and HTTP cache policy
|-- resource_routes.py        Site and Scan Resource Inventory
|-- graph_routes.py           Scan topology and graph capabilities
|-- snapshot_routes.py        static observations, links, attempts, and HTML
|-- legacy_render_routes.py   historical Scan-bound Render evidence adapters
|-- render_routes.py          first-class RenderRun API
`-- *_routes.py               other established domain routers
```

Routers own HTTP adaptation only. Services and query modules retain domain behavior, transaction
semantics, and evidence ownership. New endpoints belong in the router for their domain; the
composition module should not accumulate unrelated handlers.

## Core Domain Model

- WebsiteProperty is a saved Site with reusable configuration.
- WebResource is the persistent normalized URL identity shared by Page and Resource evidence.
- SitePage associates a WebResource with one saved Site and owns Site-specific manual metadata.
- ResourceSnapshot is one Scan-specific observation with representation classification.
- ResourceOccurrence is one duplicate-preserving reference found in an observation.
- ContentBlob stores exact compressed response evidence by SHA-256.
- RenderRun and RenderRunTarget define one durable browser collection over frozen Page identities.
  RenderedObservation belongs to one target and WebResource; optional Scan/snapshot references are
  provenance only. ArtifactBlob, RenderedArtifact, and bounded event rows preserve exact evidence.
- HtmlParseArtifact, HtmlParseAnchor, and HtmlParseResourceReference store reusable deterministic
  parse output.
- HtmlStructuredContentArtifact and HtmlStructuredContentNode store the current versioned,
  ContentBlob-scoped canonical document with bounded inline runs and unresolved relative URLs.
  HtmlStructuredContentSection remains historical V1 derivative state.
- Scan stores one bounded collection run and its copied effective scope.
- UrlSource, SourceRefresh, and UrlSourceEntry store URL-source configuration and Inventory.
- AiDocumentRefresh, AiDocumentSnapshot, AiDocumentReference, and AiDocumentBlob preserve immutable
  AI Document Source evidence without creating Scan observations.
- ScanSeed and ScanSeedOrigin preserve explicit scan-input provenance.
- BackgroundJob, JobEvent, and WorkerInstance store durable Activity state.
- FindingEvaluation, Finding, FindingAssessment, and FindingEvidenceReference store deterministic
  condition evaluation, stable logical identity, immutable outcomes, and typed evidence pointers.
- ScanProjectionBuild and ScanProjectionState select a complete compatible set of Page, Resource,
  Link, and summary projections for fast terminal-Scan reads.

These internal class and table names are stable technical contracts. Product copy uses Page and
Observation where the implementation names would be unnecessarily technical.

## Crawler Boundaries

- crawler.url_normalizer resolves and normalizes URLs without merging distinct resources.
- crawler.scope applies persisted scan scope and returns one deterministic decision per URL.
- crawler.security performs asynchronous URL and complete-address-set validation at the SSRF
  boundary.
- crawler.secure_transport binds static sockets to validated addresses while retaining original
  HTTP and TLS hostname identity.
- crawler.safe_fetch performs bounded HTTP GET requests, disables ambient proxies, and validates
  redirects.
- crawler.html_parser extracts head metadata, anchors, and embedded Resource references from
  best-effort HTML.
- crawler.canonical_document extracts the bounded Structured Content V2 canonical IR and renders
  deterministic Markdown independently from comparison document identity. DOM paths are
  provenance and Markdown is not canonical truth.
- crawler.static_crawler performs breadth-first traversal and persists partial results.
- storage.content_store stores exact response bytes as deterministically gzip-compressed,
  content-addressed blobs. Sibling temporary files are atomically published, and unique-row races
  reconcile through nested savepoints to the committed winner.

`WebResource`, `ContentBlob`, and `HtmlParseArtifact` get-or-create operations are safe under
concurrent Sessions. A losing unique insert rolls back only its savepoint and reloads the winner;
parse-race results load the winner's persisted child rows.

services.scan_execution owns queued static Scan terminal state and may enqueue an independent
Render Run after deterministic target selection. Saved-Site Runs are Site-owned; ad-hoc Scan Runs
are Site-less and remain owned by their source Scan. services.render_runs owns browser execution,
Run-local throttling, progress, and immutable observation persistence.
Browser capture never discovers additional Pages and never replaces static HTML, parse artifacts,
occurrences, or graph data. See [Browser-rendered observations](browser-rendered-observations.md).

services.resource_queries aggregates observed non-HTML snapshots, anchor-linked files, and
embedded references with set-based SQL. Embedded references are not automatically fetched and
non-HTML response bodies are not retained. See [Resource Inventory](resource-inventory.md).

services.source_comparison owns exact and normalized source analysis plus versioned deterministic
document-content extraction. Source normalization and document-content profiles are independent:
template-aware exclusion from document identity never rewrites retained HTML or Meaningful source
evidence.

services.structured_content owns ContentBlob-scoped extraction, validation, reuse, rebuild, and
historical preparation. It does not modify raw HTML, parse artifacts, Scan projections, or Scan
comparison identities. See [Structured Page Content](structured-page-content.md).

Terminal Scans enqueue a durable projection build after evidence commits. Active and missing-build
reads remain dynamic; compatible ready builds route Page, Resource, summary, and graph reads through
indexed projection tables. Activation is an atomic state-pointer update, and failed rebuilds leave
the previous ready build current. See [Scan projections](scan-projections.md).

The crawler does not execute JavaScript, submit forms, forward cookies, or send user credentials.
Only HTTP and HTTPS are supported. Redirects are followed manually so every destination is checked
against scope and network-safety rules before another request is sent.

Response bodies are streamed. Content-Length is checked when available and streamed bytes are
counted, so oversized responses stop before storage and are recorded as response_too_large. The
configured static timeout is also one aggregate wall-clock deadline across destination checks,
redirect hops, response headers, and body streaming; expiration is recorded as `request_timeout`.

Chromium uses separate route interception and observed CDP byte budgets. It independently resolves
destinations, so its residual DNS TOCTOU is not equivalent to the pinned static boundary. See
[Network security](network-security.md).

Browser navigation success does not by itself establish requested-Page success. The renderer
classifies the final main-document HTTP outcome before collecting normal Page screenshots or DOM.
HTTP errors retain bounded diagnostic evidence without Page artifacts. Repeated explicit 429
outcomes open a host-scoped circuit so remaining selected targets are represented as not attempted
without discarding valid static Scan evidence.

## Scope And URL Identity

When a scan has no explicit allowed hosts, the exact starting hostname is derived. Sibling hosts
and subdomains remain excluded unless explicitly configured.

Global URL identity is versioned. V1 remains available for historical data; V2 preserves audited
path and query distinctions and is Site-independent. Site `drop_query_parameters` produces only an
ephemeral crawl/source dedupe key under V2 and never rewrites `WebResource.normalized_url`.

`UrlIdentityState` gates the active runtime contract. Existing populated databases stay on V1 after
schema preparation; fresh databases start on V2. A guarded local-only migration records provenance
and mappings, rebuilds affected projections/comparisons, verifies invariants, then activates V2.

Scope belongs to each scan. Saved-site scans copy the effective Site scope into the Scan row so
later Site edits do not rewrite history.

## Saved Sites

WebsiteProperty stores a Site name, normalized base URL, description, active state, user-defined
group/platform/ownership labels, locale, and scope configuration.

Scan.website_property_id remains nullable so ad hoc scans keep working. Site deletion is
conservative: a Site with scans cannot be deleted, and Site deletion never invokes scan deletion.
Inactive Sites remain inspectable but cannot start new scans.

## URL Sources And Inventory

UrlSource is a Site child, not a crawler plugin. Supported sources are direct sitemaps, robots.txt
discovery, sitemap-index children, manual URL batches, and nested AI Document Sources.

Source refreshes use the same SafeHttpFetcher boundary as crawling. XML parsing disables networked
DTD/entity loading, and gzip decompression is bounded. Out-of-scope or invalid entries remain
reviewable but are not crawlable resources.

Source Inventory is input data, not scan output. When selected for a scan, source entries are copied
into ScanSeed and ScanSeedOrigin records. Later refresh or current-membership deletion does not rewrite a scan's input
provenance.

`UrlSourceEntry.is_current` records current Source truth. Site-level
`SiteInventorySuppression` records the separate user policy for whether a normalized or exact raw
URL appears in active Inventory and Inventory-derived seeding. Suppression never rewrites Source
declarations, survives refresh and additional matching Sources, and preserves grouped multi-source
provenance. Manual declaration removal only marks the retained manual entry non-current. Neither
operation is a global crawl exclusion or an evidence-deletion path.

Inventory Remove and Delete are separate. Remove retains current Source declarations and stores a
restorable suppression policy. Delete clears that policy and marks every current Source contributor
for the server-derived grouped Inventory identity non-current. It never physically deletes
`UrlSourceEntry`, so historical `ScanSeedOrigin.url_source_entry_id` provenance remains resolvable;
a later refresh can reactivate the same row.

`SourceRefresh` is the immutable collection envelope for one Source execution.
`SourceEntryObservation` records each declaration from a successfully materialized sitemap
`urlset` refresh at its deterministic position, preserving duplicate declarations, raw URLs,
validation/scope results, optional WebResource identity, and the exact normalization version.
Each refresh also retains sitemap document type and ordered exact child-refresh IDs, allowing
recursive index topology to be reconstructed without mutable Source state. These rows and topology
are historical evidence and are not reconstructed for pre-migration refreshes.
`UrlSourceEntry` remains only the mutable current Inventory projection.

Finding evaluator V3 freezes the selected static Scan and exact recursive refresh tree for every
active configured or robots-discovered sitemap root in `finding-evidence-manifest-v1`.
Sitemap-index-discovered descendants are selected only through that immutable tree. Scan fetch
times and Source refresh finish times remain independent evidence clocks. Cross-stream Findings use
typed immutable observation pointers; they never use current Inventory rows as historical proof.

AI Document refreshes reuse Source jobs, safe fetching, Site scope, `WebResource`, and current
Inventory origins. Dedicated compressed blobs preserve exact accepted text. They never create
`ResourceSnapshot` rows, affect Scan counters, trigger rendering, or add graph edges. See
[AI Document Sources](ai-document-sources.md).

## Durable Background Activity

services.background_jobs owns queueing, claiming, leases, heartbeats, progress, cancellation, and
worker health. Jobs have one constrained subject: a Scan, Source refresh, Scan comparison, Render
Run, or a supported Site-scoped operation such as Category Rule evaluation or structured-content
preparation.

services.job_handlers adapts claimed jobs to crawler and source-refresh services. Cancellation is
cooperative. Workers recover expired leases on startup and reconcile terminal domain records before
marking unfinished work interrupted.

Long synchronous projection, comparison, Category Rule, and structured-content handlers execute
outside the asyncio worker loop with thread-owned SQLAlchemy Sessions. Job heartbeats and worker
heartbeats therefore remain independently schedulable, while authenticated progress also renews
the active lease atomically. Expired recovery uses a current-state conditional ownership transition;
a stale candidate cannot interrupt a lease renewed before recovery acts, and a stale executor cannot
complete or fail work after ownership is lost.

Deletion services reject active jobs so background work cannot mutate rows while their owning Scan,
Source, or Site is deleted.

See [Background jobs](background-jobs.md).

## Page History And Reuse

WebResource provides stable normalized URL identity across scans. ResourceSnapshot retains one observation's
requested URL, final URL, HTTP result, retrieval metadata, parsed metadata, evidence references, and
error state.

services.page_queries provides Site-scoped Page catalogs based on SitePage and left-joined
observation history. services.site_pages, services.page_categories, and services.notes own manual
organization and exactly-one-target notes. `services.category_rules` owns support-aware automatic
Category reconciliation; `services.category_rule_evaluator` is the shared deterministic matching
implementation. Site display timezone is presentation configuration and UTC instants remain
canonical. An explicit
all-sites observation mode can inspect the same normalized Page identity outside the selected Site.

`SitePage.workspace_state` controls current Site membership independently of workflow status.
Operational Page selectors use active membership; historical Page and Scan accessors retain
suppressed associations so later mutable policy never changes what was observed.

Page Remove retains `SitePage` and all Site organization while setting suppressed state. Page
Delete removes that mutable workspace and its owned notes and organization, but never deletes
`WebResource`, Scan observations, links, content, Performance, Accessibility, comparison, or
projection evidence. A later saved-Site observation may create a fresh active `SitePage`.

Parse artifacts are identified by content blob, parser version, parser configuration, and final URL
resolution base. The base URL is required because relative links and canonical URLs depend on it.

Conditional revalidation is conservative. A prior observation must have compatible validators,
cache metadata, request representation, scope, and an available local blob. A successful 304 creates
a new observation, records the actual retrieval status separately from the effective Page status,
and recreates current-scan link occurrences.

Persistent Page Change History and Scan comparison share the `document-content-v2` extractor. Its
recognized operational profiles are structural and narrow; arbitrary timestamps, identifiers,
error Pages, and ordinary visible text retain the default extraction behavior.

See [Page history and reuse](page-history-and-reuse.md).
See [Page workspaces](page-workspaces.md).

## Scan Queries And Lifecycle

Scan page results are server-side paginated, filterable, and sortable. Inbound counts and discovery
sources are calculated with set-based, scan-specific queries.

Inbound attribution is direct: a stored occurrence targets the selected Page identity in the same
scan. Redirect-mediated attribution is not inferred.

Scan deletion calculates affected resources and blobs before deleting scan-owned rows. Database
cleanup commits before physical blob files are removed. Shared blobs and resources referenced by
other scans, occurrences, source entries, or scan seeds are retained.

## Graph Architecture

The Graph is scan-specific derived data. services.graph_config owns capabilities and hard limits.
services.graph_queries filters, ranks, aggregates, and limits topology in SQL before constructing
the response.

Graph nodes represent scan-specific observations. Optional unfetched boundary nodes represent
in-scope Page resources discovered through links. Directed edges aggregate duplicate-preserving
page_link occurrences, while occurrence details remain separately paginated.

The frontend graph adapter is pure and renderer-independent. 2D and 3D renderers are isolated and
lazy-loaded. Layout coordinates, camera position, selection, and exports are not persisted.

See [Website graph](website-graph.md) and [Graph performance](graph-performance.md).

## API And Frontend

app.api.routes exposes typed Site, Scan, Page observation, Resource, Source, Inventory, Rendered,
Graph, Activity, and HTML evidence endpoints. Existing API paths remain unversioned and stable.

React routes cover new scans, scan history, scan details, scan observations, Sites, Site editing,
Site Page catalogs, and persistent Page history. TanStack Query owns server state. URL parameters
preserve tab, filter, pagination, graph, and presentation state where appropriate.
Shared table pagination conventions and URL parameter isolation are documented in
[Table pagination](table-pagination.md).

Render Run detail is target-centric: it left-joins optional retained observations so frozen target
membership, ordering, deleted-evidence tombstones, and never-attempted targets remain visible.
Rendered evidence deletion is a separate lifecycle and cannot delete the Page, WebResource, Scan,
static evidence, Performance evidence, or Accessibility evidence it describes.

Stored HTML is rendered only as escaped text. The raw HTML endpoint returns text/plain.

## Site Intelligence Composition

Site Intelligence is a typed, read-only composition over authoritative workspace state, evidence,
and deterministic derivatives. It is not evidence, a projection, or a persisted dashboard. The
default operational Page denominator is the set of active SitePage workspaces; suppressed Pages
and deleted workspaces retain historical evidence without inflating current coverage.

Static Scans, Render, Performance, Accessibility, Structured Content, Sources, and Comparisons
retain independent clocks and provenance. The latest Scan never acts as a global Site timestamp.
Coverage always exposes integer numerator and denominator values, with a null ratio when the
denominator is zero. Missing evidence never implies a healthy state. The read endpoint does not
prepare Structured Content, rebuild projections or comparisons, enqueue work, or mutate state.
Accessibility current-state rows and run provenance use the same detector, integration,
normalization, ruleset, and profile compatibility identities as Collection Plan selection.

The architectural sequence is: retained evidence, deterministic derivatives, deterministic
Finding evaluation, persistent Findings, Site Intelligence and workflow, and only then future AI
interpretation. No health score or Finding
inference belongs in the composition layer.

Finding history is durable during normal evidence and Page lifecycle operations. Explicit
administrative deletion can remove one Finding while retaining its frozen evaluation; explicit
Site-scoped reset can atomically remove the complete rebuildable Finding/evaluation layer and its
terminal Finding job history. Both preserve collected evidence, including frozen recursive sitemap
Source evidence, and block while Site Finding evaluation work is active.

## Collection Plans

Collection Plans are implemented orchestration records, not evidence and not a scheduler. They
freeze a current active-Page universe and compatibility context, select missing evidence or an
explicit refresh of eligible Performance, Accessibility, or Render evidence, and batch the existing
native job types. Structured Content remains missing-current only because it is deterministic from
retained HTML. Site Intelligence uses the same selectors so overview coverage and Plan previews
agree about current-compatible evidence while separately representing equivalent active collection.
See [Collection Plans](collection-plans.md).

## External Performance Evidence

Performance collection is independent of Scan execution. A durable `PerformanceRun` invokes fixed
PageSpeed and CrUX adapters, stores exact compressed provider payloads, and creates immutable,
versioned `PerformanceObservation` rows associated with a Site and, for URL targets, an existing
persistent Page `WebResource`. Lab and field evidence remain separate. Latest summaries are query
views over history and do not mutate Page or Scan records. See
[Performance observations](performance-observations.md).

## Automated Accessibility Evidence

Accessibility collection is independent of Scan execution. A durable `AccessibilityRun` loads an
existing persistent Page through the hardened browser boundary, executes a pinned local axe-core
detector, retains exact compressed payloads, and creates immutable, versioned
`AccessibilityObservation` rows. Automated evidence does not establish WCAG conformance and does
not create Findings. See [Automated Accessibility observations](accessibility-observations.md).

## Portability And Compatibility

SQLAlchemy services avoid SQLite-only behavior where a normal portable solution exists. The content
store is abstracted so object storage can replace local files later.

The following legacy identifiers remain intentionally stable:

- SCANNER_ environment-variable prefix.
- sqlite:///../data/scanner.db default database path.
- WebsiteScanner/0.1 default crawler user agent.
- website-scanner.scan.preferences frontend local-storage key.
- Existing database tables, model names, migration IDs, and migration filenames.

Changing these identifiers as part of branding could hide local data, discard preferences, alter
crawl behavior, or break operator configuration.

## Deferred Areas

Resource-body storage, environment comparison,
additional Finding detector packs, performance regression interpretation, analytics integrations, semantic analysis,
investigation workflow, scheduling, notifications, authentication, and multi-user permissions are
future direction.

Versioned deterministic Scan comparison is implemented above prepared Scan projections. See
[Deterministic Scan comparisons](scan-comparisons.md).

Robots.txt enforcement and concurrent requests within one crawl also remain deferred. The current
static crawler uses a sequential request loop with an optional delay.
