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

## Core Domain Model

- WebsiteProperty is a saved Site with reusable configuration.
- WebResource is the persistent normalized URL identity shared by Page and Resource evidence.
- SitePage associates a WebResource with one saved Site and owns Site-specific manual metadata.
- ResourceSnapshot is one Scan-specific observation with representation classification.
- ResourceOccurrence is one duplicate-preserving reference found in an observation.
- ContentBlob stores exact compressed response evidence by SHA-256.
- RenderedObservation optionally attaches browser evidence to one ResourceSnapshot; ArtifactBlob,
  RenderedArtifact, and bounded event rows preserve that evidence without changing static facts.
- HtmlParseArtifact, HtmlParseAnchor, and HtmlParseResourceReference store reusable deterministic
  parse output.
- Scan stores one bounded collection run and its copied effective scope.
- UrlSource, SourceRefresh, and UrlSourceEntry store URL-source configuration and Inventory.
- AiDocumentRefresh, AiDocumentSnapshot, AiDocumentReference, and AiDocumentBlob preserve immutable
  AI Document Source evidence without creating Scan observations.
- ScanSeed and ScanSeedOrigin preserve explicit scan-input provenance.
- BackgroundJob, JobEvent, and WorkerInstance store durable Activity state.
- ScanProjectionBuild and ScanProjectionState select a complete compatible set of Page, Resource,
  Link, and summary projections for fast terminal-Scan reads.

These internal class and table names are stable technical contracts. Product copy uses Page and
Observation where the implementation names would be unnecessarily technical.

## Crawler Boundaries

- crawler.url_normalizer resolves and normalizes URLs without merging distinct resources.
- crawler.scope applies persisted scan scope and returns one deterministic decision per URL.
- crawler.security validates destinations at the SSRF boundary.
- crawler.safe_fetch performs bounded HTTP GET requests and validates redirects.
- crawler.html_parser extracts head metadata, anchors, and embedded Resource references from
  best-effort HTML.
- crawler.static_crawler performs breadth-first traversal and persists partial results.
- storage.content_store stores exact response bytes as gzip-compressed, content-addressed blobs.

services.scan_execution owns queued Scan terminal state across static and optional rendered phases.
Browser capture never discovers additional Pages and never replaces static HTML, parse artifacts,
occurrences, or graph data. See [Browser-rendered observations](browser-rendered-observations.md).

services.resource_queries aggregates observed non-HTML snapshots, anchor-linked files, and
embedded references with set-based SQL. Embedded references are not automatically fetched and
non-HTML response bodies are not retained. See [Resource Inventory](resource-inventory.md).

Terminal Scans enqueue a durable projection build after evidence commits. Active and missing-build
reads remain dynamic; compatible ready builds route Page, Resource, summary, and graph reads through
indexed projection tables. Activation is an atomic state-pointer update, and failed rebuilds leave
the previous ready build current. See [Scan projections](scan-projections.md).

The crawler does not execute JavaScript, submit forms, forward cookies, or send user credentials.
Only HTTP and HTTPS are supported. Redirects are followed manually so every destination is checked
against scope and network-safety rules before another request is sent.

Response bodies are streamed. Content-Length is checked when available and streamed bytes are
counted, so oversized responses stop before storage and are recorded as response_too_large.

## Scope And URL Identity

When a scan has no explicit allowed hosts, the exact starting hostname is derived. Sibling hosts
and subdomains remain excluded unless explicitly configured.

Normalization safely handles host casing, internationalized hosts, default ports, dot segments,
fragments, configured tracking parameters, and deterministic query ordering. It does not lowercase
paths, erase all trailing slashes, merge HTTP with HTTPS, or treat canonical metadata as identity.

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
into ScanSeed and ScanSeedOrigin records. Later refresh or deletion does not rewrite a scan's input
provenance.

AI Document refreshes reuse Source jobs, safe fetching, Site scope, `WebResource`, and current
Inventory origins. Dedicated compressed blobs preserve exact accepted text. They never create
`ResourceSnapshot` rows, affect Scan counters, trigger rendering, or add graph edges. See
[AI Document Sources](ai-document-sources.md).

## Durable Background Activity

services.background_jobs owns queueing, claiming, leases, heartbeats, progress, cancellation, and
worker health. A BackgroundJob has exactly one domain subject: a scan or a source refresh.
website_property_id is filter metadata, not a polymorphic subject.

services.job_handlers adapts claimed jobs to crawler and source-refresh services. Cancellation is
cooperative. Workers recover expired leases on startup and reconcile terminal domain records before
marking unfinished work interrupted.

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

Parse artifacts are identified by content blob, parser version, parser configuration, and final URL
resolution base. The base URL is required because relative links and canonical URLs depend on it.

Conditional revalidation is conservative. A prior observation must have compatible validators,
cache metadata, request representation, scope, and an available local blob. A successful 304 creates
a new observation, records the actual retrieval status separately from the effective Page status,
and recreates current-scan link occurrences.

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

Stored HTML is rendered only as escaped text. The raw HTML endpoint returns text/plain.

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
findings, accessibility and performance observations, analytics integrations, semantic analysis,
investigation workflow, scheduling, notifications, authentication, and multi-user permissions are
future direction.

Versioned deterministic Scan comparison is implemented above prepared Scan projections. See
[Deterministic Scan comparisons](scan-comparisons.md).

Robots.txt enforcement and concurrent requests within one crawl also remain deferred. The current
static crawler uses a sequential request loop with an optional delay.
