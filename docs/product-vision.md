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
- Sitemap, robots-discovered sitemap, and manual URL Sources.
- Current URL Inventory with source and scan-seed provenance.
- Persistent Pages across saved-site scans.
- Page observation history.
- Site-scoped Page organization, categories, owner labels, workflow status, and plain-text notes.
- Deterministic link roles on individual source-DOM occurrences.
- Conditional HTTP revalidation and parsed-result reuse.
- Stored HTML evidence and parsed head metadata.
- Inbound and outgoing link occurrence provenance.
- Scan-specific 2D and 3D topology graphs.
- Scan, source, Site, and Activity lifecycle management.

## Product Vocabulary

### Site

A saved website property with reusable scope and configuration. WebsiteProperty remains the
internal model name.

### Page

A successful HTML representation of a persistent normalized URL identity represented by
WebResource. A Page is not tied to one scan.

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

A Source is a sitemap, robots-discovered sitemap, or manual URL source. Inventory is the current set
of URL candidates declared by Sources. An inventory entry is not a Page observation until a scan
fetches it.

### Graph

A scan-specific representation of observed Pages and stored links. It is derived, read-only data;
layout and camera state are not persisted.

### Activity

Durable background execution, lifecycle events, leases, cancellation, and worker status.

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

## Local-First Operation

The application defaults to SQLite and local content storage. API, worker, frontend, database, and
captured evidence run on the operator's machine. This keeps sensitive crawl evidence under local
control and makes development straightforward. The SQLAlchemy and content-store boundaries are
intended to allow PostgreSQL and object storage later without changing the product model.

## Four Conceptual Layers

### Observation

What was actually recorded: Pages, Resources, observations, links, Sources, Inventory, stored HTML
responses, rendered captures, topology, Activity, and reuse provenance.

This layer is substantially implemented.

### Comparison

Deterministic differences between observations or environments.

This layer is only partially represented through Page history, content hashes, retrieval metadata,
and exact reuse provenance. Site Ledger does not yet provide a complete scan comparison workflow.

### Interpretation

Rules, statistics, models, or AI that explain evidence.

This is future direction. Findings, audits, semantic analysis, and AI explanations are not currently
implemented.

### Workflow

Site Ledger now provides lightweight Page organization, freeform owner labels, workflow status, and
plain-text notes. Authenticated ownership, assignments to users, findings, investigations,
permissions, and resolution workflow remain future direction.

## Roadmap

Planned areas include Resource-body analysis, deterministic scan and environment comparisons,
findings, accessibility and performance observations, analytics
integrations, semantic analysis, and investigation workflow.

New work should preserve the separation between evidence, deterministic comparison, interpretation,
and workflow. Interpretation must remain traceable to the observations that support it.

## Current Limitations

- Browser rendering is bounded optional Page evidence, not browser-only crawling or Resource discovery.
- Complete website and environment comparison is not implemented.
- Resource-body storage and analysis, findings, audits, analytics, semantic embeddings, and AI
  summaries are not implemented.
- Authenticated and private-network crawling are not supported.
- Robots.txt enforcement and within-crawl concurrency remain deferred.
- Graph views are bounded and scan-specific, not persistent site-wide knowledge graphs.
- SQLite and local files are the current storage implementations.
- The application has no authentication, multi-user permissions, scheduling, or notifications.
