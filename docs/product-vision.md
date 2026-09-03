# Site Ledger Product Vision

## Purpose

Site Ledger is a local-first website intelligence platform that inventories sites, preserves crawl
evidence, and tracks Page observations over time. It records a website as a structured historical
dataset so users can inspect what was observed, where URLs came from, how Pages connect, and which
evidence supports each result.

The product is larger than its crawler. Crawling is one collection mechanism; the durable Page,
observation, source, evidence, graph, and Activity records are the foundation for future comparison,
interpretation, and investigation features.

## Current Capabilities

The current application implements:

- Saved Sites with reusable scope and open-ended group, platform, and ownership labels.
- Scoped static HTML scans executed as durable background jobs.
- Aggregate static-request deadlines spanning redirects and streamed response bodies.
- Standalone durable Render Runs over frozen persistent Page targets, plus optional Scan-triggered
  rendering.
- Sitemap, robots-discovered sitemap, and manual URL Sources.
- AI Document Sources with nested indexes, retained text evidence, and refresh history.
- Current URL Inventory with source and scan-seed provenance.
- Persistent Pages across saved-site scans.
- Page observation history.
- Site-scoped Page organization, categories, owner labels, workflow status, and plain-text notes.
- Deterministic URL-based automatic Category Rules with provenance and exclusions.
- Site-scoped IANA display timezones over immutable UTC evidence.
- Deterministic link roles on individual source-DOM occurrences.
- Conditional HTTP revalidation and parsed-result reuse.
- Stored HTML evidence and parsed head metadata.
- A versioned canonical source-document representation, outline, and deterministic Markdown
  derived from exact stored HTML.
- Inbound and outgoing link occurrence provenance.
- Scan-specific 2D and 3D topology graphs.
- Versioned prepared results for immutable terminal Scans, with raw evidence fallback and rebuilds.
- Deterministic same-Site Scan Comparison and Page Change History.
- Immutable PageSpeed lab and CrUX field observations collected independently of Scans.
- Immutable automated Accessibility observations with pinned detector and browser provenance.
- Read-only Site Intelligence with independent evidence clocks and explicit coverage denominators.
- Current-evidence Collection Plans that batch existing native collectors without becoming evidence.
- Scan, source, Site, and Activity lifecycle management.
- Persistent deterministic static Findings for Page HTTP/fetch failures, noindex directives,
  conflicting indexability, missing titles, canonical defects, and current non-HTML representations.

## Product Vocabulary

### Site

A saved website property with reusable scope and configuration. WebsiteProperty remains the
internal model name.

### Page

A Site-scoped persistent web Page identity that can accumulate successful and failed observations
over time. `WebResource` owns the normalized URL identity and `SitePage` owns mutable Site workspace
membership; a Page is not tied to one Scan or contingent on its latest fetch succeeding.

### Resource

A non-HTML representation observed directly or inferred from retained HTML reference evidence.
Resources do not receive a separate WebResource identity for the same normalized URL.

### Observation

One Scan-specific ResourceSnapshot of a Page or Resource. An observation contains the requested and final URL,
HTTP result, retrieval details, metadata, stored evidence references, and errors recorded in that
scan.

### Scan

One bounded collection run that produces observations. A scan copies its effective scope so later
Site edits do not rewrite historical behavior.

### Source And Inventory

A Source is a sitemap, robots-discovered sitemap, manual URL source, or AI Document Source. Inventory is the current set
of URL candidates declared by Sources. An inventory entry is not a Page observation until a scan
fetches it.

### Graph

A scan-specific representation of observed Pages and stored links. It is derived, read-only data;
layout and camera state are not persisted.

### Activity

Durable background execution, lifecycle events, leases, cancellation, and worker status.

### Finding

A persistent logical condition inferred deterministically from exact retained evidence. A Finding
has immutable assessments and independent mutable acknowledgement workflow; unknown evidence never
means resolved. See [Findings](findings.md).

### Scan Projection

A deterministic, versioned, rebuildable index derived only from one terminal Scan's immutable
evidence. It accelerates ordinary reads but never replaces observations or exact evidence. See
[Scan projections](scan-projections.md).

## Page Versus Observation

WebResource provides stable Page identity across scans. ResourceSnapshot preserves what one scan
actually observed. Keeping these concepts separate allows Site Ledger to show Page history without
silently replacing old evidence with a newer result.

A reused response still creates a new observation. A successful conditional 304 records the actual
retrieval status, references the prior evidence used, and recreates current-scan link occurrences
with current scope decisions.

## Site Versus Scan

A Site stores reusable intent: its name, base URL, labels, active state, and default scope. A Scan
stores one execution: copied scope, timestamps, status, counts, stop reason, observations, inputs,
and errors. Updating a Site does not mutate existing scans.

Ad hoc scans remain valid without a Site. Saved-site scans connect persistent Page history to a
specific property.

## Evidence And Provenance

Evidence is a first-class product concern:

- Exact HTML response bytes are compressed and stored by content hash.
- Redirect chains and response headers remain attached to observations.
- Link occurrences preserve duplicate anchors, source observation, DOM location, and scope result.
- Scan seeds preserve which source entries supplied explicit inputs.
- Parse artifacts record parser and URL-resolution identity.
- Reuse fields record when prior evidence avoided a full transfer or parse.

Site Ledger should continue to distinguish recorded facts from later conclusions.

Content-addressed resource, HTML blob, and parse-artifact identities are concurrency contracts.
Concurrent producers reconcile to one committed row without rolling back unrelated work, while
local HTML files are deterministically compressed and atomically published.

## Local-First Operation

The application defaults to SQLite and local content storage. API, worker, frontend, database, and
captured evidence run on the operator's machine. This keeps sensitive crawl evidence under local
control and makes development straightforward. The SQLAlchemy and content-store boundaries are
intended to allow PostgreSQL and object storage later without changing the product model.

## Conceptual Layers

Site Intelligence sits between deterministic derivatives and future interpretation. It composes
the current operational view without becoming new evidence or persisted state. Active Site Pages
define Page coverage denominators, each evidence domain keeps its own observation clock, and every
coverage statement includes its numerator and denominator. Missing evidence is reported as
missing, never as good. There is no global Site health score.

### Observation

What was actually recorded: Pages, Resources, observations, links, Sources, Inventory, stored HTML
responses, rendered captures, topology, Activity, and reuse provenance.

This layer is substantially implemented.

### Comparison

Deterministic differences between observations or environments.

This layer is only partially represented through Page history, content hashes, retrieval metadata,
and exact reuse provenance. Site Ledger provides deterministic same-Site Scan comparison and Page
Change History without interpreting those facts as Findings.

### Deterministic Findings And Interpretation

Rules, statistics, models, or AI that explain evidence.

The deterministic static Finding evaluator covers Page HTTP/fetch failures, noindex directives,
indexability conflicts, missing titles, canonical validity/cardinality/observed-target failures,
and active Pages currently returning non-HTML representations. Per-detector evaluation diagnostics
make clear and unknown outcomes observable without expanding sparse Finding persistence.
The current bundle correlates static Scan evidence with immutable refresh-scoped sitemap Source
evidence. Additional cross-domain packs for Render, Accessibility, Performance, analytics,
semantic analysis, and AI explanations remain future direction. Automated Accessibility and
Performance collection are evidence domains, not automatically Finding or compliance conclusions.

### Workflow

Site Ledger provides lightweight Page organization, freeform owner labels, workflow status,
plain-text notes, and Finding acknowledgement. Authenticated ownership, assignments to users,
investigations, permissions, and richer resolution workflow remain future direction.

## Roadmap

Planned areas include Resource-body analysis, environment comparisons, additional cross-domain
Finding evidence beyond the implemented static+sitemap contract, performance regression interpretation, analytics
integrations, semantic analysis, and investigation workflow.

New work should preserve the separation between evidence, deterministic comparison, interpretation,
and workflow. Interpretation must remain traceable to the observations that support it.

## Current Limitations

- Browser rendering is bounded optional Page evidence, not browser-only crawling or Resource discovery.
- Cross-Site and environment comparison are not implemented. Same-Site Scan comparison is
  documented in [Deterministic Scan comparisons](scan-comparisons.md).
- Resource-body storage and analysis, Render/Accessibility/Performance/analytics Finding evidence,
  semantic embeddings, and AI summaries are not implemented. Static technical/indexability,
  internal-link topology, and sitemap/static cross-stream Findings are current.
- Authenticated crawling is not supported. Private-network crawling is blocked by default and is
  available only through the explicit trusted `allow_private_networks=true` scope setting.
- Robots.txt enforcement and within-crawl concurrency remain deferred.
- Graph views are bounded and scan-specific, not persistent site-wide knowledge graphs.
- SQLite and local files are the current storage implementations.
- The application has no authentication, multi-user permissions, scheduling, or notifications.
