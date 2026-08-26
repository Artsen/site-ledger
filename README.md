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
- Collects bounded Chromium-rendered observations in durable Render Runs, either manually or from
  eligible static Scan snapshots.
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
- Extracts versioned deterministic Page outlines and direct source-text sections from retained HTML.
- Collects immutable PageSpeed lab and CrUX field observations on demand with exact provider payloads.
- Collects immutable automated Accessibility observations with pinned local axe-core evidence.
- Records page metadata, redirect chains, errors, and inbound/outgoing link provenance.
- Uses conditional HTTP revalidation and deterministic parsed-result reuse when safe.
- Displays scan-specific 2D and 3D topology graphs with bounded server-side queries.
- Materializes versioned, rebuildable indexes for fast immutable terminal-Scan reads while keeping
  raw evidence authoritative.
- Indexes browser-rendered observations from Site, Page, Render Run, and historical Scan workspaces
- Deletes retained browser evidence independently with target tombstones, bounded bulk actions,
  reference-safe artifact reclamation, and Site/legacy Scan ownership controls
  with exact evidence links.
- Supports scan, source, Site, and background Activity lifecycle management.

Site Ledger does not perform browser-only crawling, Resource-body storage, complete website change
detection, visual regression, WCAG certification, performance regression detection, analytics
correlation, or AI findings.

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
- **Performance observation:** External PageSpeed lab or CrUX field evidence collected independently
  of a Scan.
- **Accessibility observation:** Automated axe-core evidence for one persistent Page and responsive
  profile, collected independently of a Scan.

See [Product vision](docs/product-vision.md) for the broader model and roadmap.
See [Resource Inventory](docs/resource-inventory.md) for classification, provenance, and storage
boundaries.
See [Scan projections](docs/scan-projections.md) for terminal-result indexing, fallback, and rebuild
behavior.
See [Structured Page Content](docs/structured-page-content.md) for source-text extraction,
historical preparation, and Content-tab semantics.
See [Page Category Rules](docs/page-category-rules.md) and
[Site display timezones](docs/site-timezones.md) for mutable Site organization and presentation.
See [Performance observations](docs/performance-observations.md) for external provider evidence,
security, collection limits, and workspace semantics.
See [Automated Accessibility observations](docs/accessibility-observations.md) for detector
provenance, browser security, evidence semantics, and automated-testing limitations.
See [URL identity contract](docs/url-identity-contract.md) for persistent WebResource semantics,
known V1 equivalences, retained-data audit results, and future migration constraints.

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

The reproducible contributor setup uses Python 3.11, uv 0.12.3, Node.js 20.19.0, and the npm
10.8.2 distributed with that Node release. Install uv once with
`python -m pip install --user uv==0.12.3`. The backend lock is authoritative for resolved Python
dependencies, and `npm ci` installs the exact frontend lock.

~~~powershell
git clone https://github.com/Artsen/site-ledger.git
cd site-ledger

cd backend
uv sync --extra dev --locked
uv run playwright install chromium
uv run python -m app.browser_check
uv run alembic upgrade head
~~~

Install the frontend dependencies in a separate terminal:

~~~powershell
cd frontend
npm ci
~~~

Runtime databases, static HTML, rendered DOM, and screenshots are written under data/ and ignored
by Git.

To enable on-demand Performance collection, set the Google API key only in the backend process
environment before starting both API and worker:

~~~powershell
$env:SITE_LEDGER_GOOGLE_API_KEY="your-local-key"
~~~

The recommended Performance and Accessibility batch is 50 Pages. The configurable hard Page
limit defaults to the absolute application ceiling of 250 Pages. Performance additionally permits
at most 1,002 provider requests per run and throttles CrUX to 120 queries/minute; Accessibility
permits at most 500 Page/profile browser audits. Collection is serial and manual. Scheduling and
CrUX History import are not implemented.

Operators may lower the limits with `SCANNER_PERFORMANCE_DEFAULT_PAGE_LIMIT`,
`SCANNER_PERFORMANCE_HARD_PAGE_LIMIT`, `SCANNER_PERFORMANCE_MAX_PROVIDER_REQUESTS`,
`SCANNER_PERFORMANCE_CRUX_QUERIES_PER_MINUTE`, `SCANNER_ACCESSIBILITY_DEFAULT_PAGE_LIMIT`,
`SCANNER_ACCESSIBILITY_HARD_PAGE_LIMIT`, and `SCANNER_ACCESSIBILITY_MAX_AUDIT_COUNT`. Invalid
values fail settings validation and are never silently clamped.

### Observability Payload Lifecycle

Performance and Accessibility evidence is immutable while retained, with explicit hard deletion at
observation, Run, and Site-domain scope. Original terminal Run counters remain collection history;
separate retained/deleted counts describe current evidence. Active collection blocks deletion and
garbage collection only in its own domain. Shared content-addressed payloads survive partial
deletion, and database changes commit before best-effort file cleanup. Cleanup failures are visible
warnings. Full Site deletion applies the same payload cleanup without leaking unreferenced files.

Payload GC is dry-run by default:

~~~powershell
python tools/observability_payload_gc.py --domain all
python tools/observability_payload_gc.py --domain performance --apply
~~~

GC reports referenced, unreferenced, missing, orphan, unexpected, and reclaimable storage without
deleting unexpected-layout files. See the Performance and Accessibility evidence documentation for
the complete retention semantics.

## Running Locally

Run the API:

~~~powershell
cd backend
uv run uvicorn app.main:app --reload
~~~

Run the worker in a second terminal:

~~~powershell
cd backend
uv run python -m app.worker
~~~

Historical terminal Scans can prepare optimized results with
`uv run python -m app.scan_projections build-missing --limit 25` from `backend`.
Historical HTML can prepare structured Page content with
`uv run python -m app.structured_content build-missing --site-id 1 --limit 500` from `backend`.
Category Rule performance can be measured with
`uv run python -m app.category_rule_benchmark`.
Performance history queries can be measured with
`uv run python -m app.performance_benchmark`.
Run the deterministic Accessibility history benchmark with
`uv run python -m app.accessibility_benchmark`.

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
- Only complete globally routable DNS answer sets are accepted by default; mixed public/private,
  loopback, link-local, private, and shared/CGNAT destinations are blocked.
- Static sockets connect to the validated address while preserving HTTP Host, TLS SNI, and
  certificate verification. Ambient proxy environment variables are ignored.
- Redirect destinations are revalidated before each request.
- Cookies and user credentials are not forwarded.
- Request timeout, redirect, response-size, Page, and depth limits are enforced.
- Active static scans may retry transient network failures and selected temporary HTTP statuses up
  to `static_max_attempts`; every request remains durable attempt evidence under one final Page
  observation. Retry-After and exponential delays are capped by `static_retry_max_delay_ms`.
- Completed Scans cannot retry an individual static Page. Browser observations are never retried or
  modified in place; an explicit selected rerender creates a new Render Run and new evidence.
- Scanned HTML is parsed as data and never executed in the application.
- Browser requests are intercepted before navigation and every HTTP redirect or subresource
  destination is checked against the network policy.
- Browser byte budgets use observed Chromium transfer and actively stop loading after a limit;
  Chromium still has a documented DNS validation/connection TOCTOU boundary.
- Browser contexts are non-persistent, service workers and unsafe methods are blocked, and no
  credentials are supplied.

Authenticated browser capture is not supported. Private-network access remains disabled by
default and must be deliberately enabled in scan scope.

See [Network security](docs/network-security.md) for guarantees and residual risks.

## Quality Checks

Backend:

~~~powershell
cd backend
uv lock --check
uv sync --extra dev --locked
uv run --extra dev --locked pytest
uv run --extra dev --locked ruff check . ../tools
uv run --extra dev --locked ruff format --check . ../tools
uv run --extra dev --locked mypy app
uv run --extra dev --locked alembic upgrade head
uv run --extra dev --locked alembic check
~~~

Frontend:

~~~powershell
cd frontend
npm ci
npm run lint
npm run typecheck
npm run test
npm run build
npm run e2e
npm audit --omit=dev
~~~

Full-stack Golden Path, from the repository root after both locked environments and Playwright
Chromium are installed:

~~~powershell
uv run --project backend --extra dev --locked python tools/run_full_stack_e2e.py
~~~

URL identity migration is an offline, local-only operator workflow. Schema upgrade alone is safe
for an existing database and leaves V1 active. After resolving the private full reconciliation
manifest, rebase and inspect it before any simulation:

~~~powershell
uv run --project backend --extra dev --locked python tools/url_identity_migrate.py `
  --database data/scanner.db rebase .local/url-identity/manifest-full.json `
  --output .local/url-identity/manifest-rebased.json
uv run --project backend --extra dev --locked python tools/url_identity_migrate.py `
  --database data/scanner.db status
uv run --project backend --extra dev --locked python tools/url_identity_migrate.py `
  --database data/scanner.db preflight .local/url-identity/manifest-rebased.json
uv run --project backend --extra dev --locked python tools/url_identity_migrate.py `
  --database data/scanner.db simulate .local/url-identity/manifest-rebased.json `
  --destination .local/url-identity/simulation.db
~~~

Live apply and rollback require separate exact confirmation phrases and stopped workers. See
[URL identity migration](docs/url-identity-migration.md). Never commit full manifests or reports.

GitHub Actions runs independent `Backend`, `Frontend`, `Playwright`, and `Golden Path` checks for
pull requests to `main` and pushes to `main`. The production npm audit blocks on high or critical findings; the full
dependency-tree audit is reported without blocking while the remaining Vite/Vitest advisories
require major upgrades. The two current production advisories are moderate React Router findings.
Python dependency vulnerability scanning is not yet automated.

The regular Playwright workflow uses mocked API responses for fast UI coverage. The separate Golden
Path runs one deterministic local fixture through the real React, API, SQLite, worker, crawler,
evidence, projection, comparison, and UI lifecycle. Deterministic crawler behavior, redirect
safety, storage, graph queries, background jobs, Page history, and reuse remain covered more broadly
by backend tests. Benchmarks remain manual diagnostics rather than hosted-runner gates; run them
explicitly through `uv run`, for example `uv run python -m app.static_benchmark`.

## Updating Dependencies

For backend requirements, edit `backend/pyproject.toml`, run `uv lock`, then verify with
`uv sync --extra dev --locked` and the backend checks above. Commit `pyproject.toml` and `uv.lock`
together when both change; do not edit resolved lock entries manually.

For frontend requirements, change `frontend/package.json` intentionally, update
`frontend/package-lock.json` with npm, then run `npm ci` and the frontend checks above. Commit both
files when the declared dependency set changes.

## Documentation

- [Product vision](docs/product-vision.md)
- [Architecture](docs/architecture.md)
- [URL identity contract](docs/url-identity-contract.md)
- [URL identity migration](docs/url-identity-migration.md)
- [Background jobs](docs/background-jobs.md)
- [Website graph](docs/website-graph.md)
- [Graph performance](docs/graph-performance.md)
- [Page history and reuse](docs/page-history-and-reuse.md)
- [Page workspaces](docs/page-workspaces.md)
- [Structured Page Content](docs/structured-page-content.md)
- [Browser-rendered observations](docs/browser-rendered-observations.md)
- [Resource Inventory](docs/resource-inventory.md)
- [AI Document Sources](docs/ai-document-sources.md)
- [Deterministic Scan comparisons](docs/scan-comparisons.md)
- [Full-stack Golden Path testing](docs/full-stack-testing.md)
- [Product workspace navigation](docs/workspace-navigation.md)

## Current Limitations

- The crawler observes static HTTP responses and does not render JavaScript.
- Robots.txt enforcement and concurrent requests inside one crawl remain deferred.
- Each crawl currently uses a sequential request loop with an optional delay.
- Graph hard caps are 3,000 nodes and 10,000 edges; filters or focused neighborhoods are preferable
  for dense scans.
- The Three.js renderer is a large lazy chunk and triggers Vite's chunk-size warning.
- SQLite can become a bottleneck for large aggregate graph queries and concurrent local work.
- The full-stack Golden Path covers one deterministic static crawl and adjacent comparison workflow;
  broader browser-rendered and failure-recovery workflows remain outside that focused path.
- React Router production audit advisories remain an existing dependency concern.

## Roadmap

Future direction is designed to support screenshots, richer asset
inventories, environment comparisons, findings, performance regression interpretation, analytics
integrations, semantic analysis, and investigation workflow.
These capabilities are planned areas, not current product claims.
