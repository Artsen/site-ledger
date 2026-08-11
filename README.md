# Site Ledger

**A historical record of your website.**

Site Ledger is a local-first website intelligence platform that records websites as structured
historical datasets. It inventories Pages, preserves scan observations and link provenance, and
keeps the stored evidence needed to understand what exists and how the recorded state evolves over
time.

It is useful for developers, site owners, content teams, and investigators who need a durable,
inspectable record rather than a disposable crawl report. Persistent Page identities connect
observations from separate scans without erasing the evidence captured by each scan.

## What It Currently Does

- Saves Sites with reusable scope and user-defined classification labels.
- Runs bounded static HTML scans through durable background jobs.
- Optionally attaches bounded Chromium-rendered observations to eligible static snapshots.
- Accepts sitemap, robots-discovered sitemap, and manual URL Sources.
- Discovers and retains nested AI Document Sources with exact refresh evidence.
- Maintains a current URL Inventory with source provenance.
- Preserves persistent Pages and scan-specific observation history.
- Inventories observed and HTML-referenced non-HTML Resources without storing Resource bodies.
- Provides Site-scoped Page workspaces with categories, owner labels, workflow status, and notes.
- Applies deterministic automatic Page Category Rules with manual provenance and exclusions.
- Displays Site-scoped timestamps in an optional IANA timezone without changing stored evidence.
- Classifies individual link occurrences by source-DOM role with explicit rule provenance.
- Stores exact HTML responses as compressed, content-addressed evidence.
- Records page metadata, redirect chains, errors, and inbound/outgoing link provenance.
- Uses conditional HTTP revalidation and deterministic parsed-result reuse when safe.
- Displays scan-specific 2D and 3D topology graphs with bounded server-side queries.
- Materializes versioned, rebuildable indexes for fast immutable terminal-Scan reads while keeping
  raw evidence authoritative.
- Indexes browser-rendered observations from the Scan workspace with exact evidence links.
- Supports scan, source, Site, and background Activity lifecycle management.

Site Ledger does not perform browser-only crawling, Resource-body storage, complete website change
detection, visual regression, accessibility or performance audits, analytics correlation, or AI
findings.

## Core Product Model

- **Site:** A saved website property with reusable scope and configuration. The internal model is
  WebsiteProperty.
- **Page:** A persistent normalized URL identity represented internally by WebResource.
- **Resource:** A non-HTML representation observed directly or referenced by retained HTML.
- **Observation:** A scan-specific ResourceSnapshot of a Page or non-HTML Resource.
- **Scan:** One bounded collection run that produces observations.
- **Source:** A sitemap, robots-discovered sitemap, manual URL source, or AI Document Source.
- **Inventory:** Current URL candidates declared by Sources. Inventory entries are inputs, not
  observations.
- **Graph:** A scan-specific representation of observed Pages and links.
- **Activity:** Durable background execution and worker status.

See [Product vision](docs/product-vision.md) for the broader model and roadmap.
See [Resource Inventory](docs/resource-inventory.md) for classification, provenance, and storage
boundaries.
See [Scan projections](docs/scan-projections.md) for terminal-result indexing, fallback, and rebuild
behavior.
See [Page Category Rules](docs/page-category-rules.md) and
[Site display timezones](docs/site-timezones.md) for mutable Site organization and presentation.

## Architecture Overview

The backend uses FastAPI, SQLAlchemy 2, Alembic, SQLite, HTTPX, and lxml. A standalone worker claims
durable database-backed jobs and invokes the crawler or source-refresh services. Exact response
bytes are gzip-compressed behind a content-store abstraction.

The frontend uses React, TypeScript, Vite, TanStack Query, Tailwind CSS, Vitest, Testing Library,
and Playwright. Graph rendering is lazy-loaded so the Three.js-backed 3D renderer stays outside the
initial application bundle.

The crawler is a static HTTP subsystem. It performs breadth-first GET traversal, validates each
redirect against scope and SSRF protections, enforces response-size and request limits, and saves
partial evidence when individual Pages fail.

Detailed boundaries are documented in [Architecture](docs/architecture.md).

## Local Setup

The tested setup uses Windows PowerShell and Node.js 20.19.0 or newer.

~~~powershell
git clone https://github.com/Artsen/site-ledger.git
cd site-ledger

cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m playwright install chromium
python -m app.browser_check
alembic upgrade head
~~~

Install the frontend dependencies in a separate terminal:

~~~powershell
cd frontend
npm install
~~~

Runtime databases, static HTML, rendered DOM, and screenshots are written under data/ and ignored
by Git.

## Running Locally

Run the API:

~~~powershell
cd backend
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload
~~~

Run the worker in a second terminal:

~~~powershell
cd backend
.\.venv\Scripts\Activate.ps1
python -m app.worker
~~~

Historical terminal Scans can prepare optimized results with
`python -m app.scan_projections build-missing --limit 25` from `backend`.
Category Rule performance can be measured with `python -m app.category_rule_benchmark`.

Run the frontend in a third terminal:

~~~powershell
cd frontend
npm run dev
~~~

The API defaults to http://127.0.0.1:8000 and the frontend defaults to
http://127.0.0.1:5173. Scans and source refreshes remain queued when no worker is online.

## Data Storage And Privacy

Site Ledger is local-first. SQLite data, worker state, and captured HTML stay in the local data
directory unless the operator deliberately moves or exports them. Stored HTML is displayed as
escaped source text and is never executed by the dashboard. Graph PNG exports are generated in the
browser.

Content blobs are addressed by SHA-256 and compressed with gzip. Identical response bodies share a
blob record, while every scan retains its own Page observation and link provenance. Deletion is
reference-aware so shared evidence remains available to other scans.

## Security Boundaries

The crawler is an SSRF boundary:

- Only HTTP and HTTPS destinations are accepted.
- Loopback, link-local, and private network destinations are blocked by default.
- Redirect destinations are revalidated before each request.
- Cookies and user credentials are not forwarded.
- Request timeout, redirect, response-size, Page, and depth limits are enforced.
- Active static scans may retry transient network failures and selected temporary HTTP statuses up
  to `static_max_attempts`; every request remains durable attempt evidence under one final Page
  observation. Retry-After and exponential delays are capped by `static_retry_max_delay_ms`.
- Completed scans cannot retry an individual Page, and browser-rendered Pages are never retried.
- Scanned HTML is parsed as data and never executed in the application.
- Browser requests are intercepted before navigation and every HTTP redirect or subresource
  destination is checked against the network policy.
- Browser contexts are non-persistent, service workers and unsafe methods are blocked, and no
  credentials are supplied.

Authenticated browser capture is not supported. Private-network access remains disabled by
default and must be deliberately enabled in scan scope.

## Quality Checks

Backend:

~~~powershell
cd backend
pytest
ruff check .
ruff format --check .
mypy app
alembic upgrade head
alembic check
python -m app.static_benchmark
python -m app.render_benchmark
~~~

Frontend:

~~~powershell
cd frontend
npm run lint
npm run typecheck
npm run test
npm run build
npm run e2e
npm audit --omit=dev
~~~

The Playwright workflow uses mocked API responses. Deterministic crawler behavior, redirect safety,
storage, graph queries, background jobs, Page history, and reuse are covered by backend tests.

## Documentation

- [Product vision](docs/product-vision.md)
- [Architecture](docs/architecture.md)
- [Background jobs](docs/background-jobs.md)
- [Website graph](docs/website-graph.md)
- [Graph performance](docs/graph-performance.md)
- [Page history and reuse](docs/page-history-and-reuse.md)
- [Page workspaces](docs/page-workspaces.md)
- [Browser-rendered observations](docs/browser-rendered-observations.md)
- [Resource Inventory](docs/resource-inventory.md)
- [AI Document Sources](docs/ai-document-sources.md)
- [Deterministic Scan comparisons](docs/scan-comparisons.md)

## Current Limitations

- The crawler observes static HTTP responses and does not render JavaScript.
- Robots.txt enforcement and concurrent requests inside one crawl remain deferred.
- Each crawl currently uses a sequential request loop with an optional delay.
- Graph hard caps are 3,000 nodes and 10,000 edges; filters or focused neighborhoods are preferable
  for dense scans.
- The Three.js renderer is a large lazy chunk and triggers Vite's chunk-size warning.
- SQLite can become a bottleneck for large aggregate graph queries and concurrent local work.
- Playwright does not currently orchestrate a real API, worker, and fixture website end to end.
- React Router production audit advisories remain an existing dependency concern.

## Roadmap

Future direction is designed to support screenshots, richer asset
inventories, environment comparisons, findings, accessibility and
performance observations, analytics integrations, semantic analysis, and investigation workflow.
These capabilities are planned areas, not current product claims.
