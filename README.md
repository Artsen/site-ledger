# Artsen Design Scanner

Artsen Design Scanner is a scoped website page inventory tool. PR 1 implements a static HTML crawler that stores page snapshots, link provenance, parsed head metadata, and compressed HTML blobs.

## Local Setup

Backend:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload
```

Frontend:

```powershell
cd frontend
npm install
npm run dev
```

The API defaults to `http://127.0.0.1:8000`; the Vite app defaults to `http://127.0.0.1:5173`.
The frontend toolchain expects Node.js `20.19.0` or newer.

## Scanner Behavior

New scans default to the exact hostname of the starting URL. If a scan starts at
`https://www.example.com/`, the default scope includes `www.example.com` and does not include
`example.com`, `blog.example.com`, or other sibling/subdomain hosts unless the user explicitly
adds allowed host patterns or enables subdomain following.

Redirects are handled manually. Each redirect destination is resolved, normalized, checked against
scan scope, and validated by SSRF destination protection before the next GET request is sent.

Response-size limits are enforced while streaming. Oversized responses are stopped before they are
stored and are recorded as `response_too_large`.

Robots.txt enforcement and concurrent crawling are deferred. The crawler is currently sequential,
with an optional delay between requests. TechSmith-specific saved-site configuration belongs to a
future PR; no site-specific host set is hardcoded in PR 1.

## Quality Checks

```powershell
cd backend
pytest
ruff check .
ruff format --check .
mypy app
alembic upgrade head
alembic check
```

```powershell
cd frontend
npm run lint
npm run typecheck
npm run test
npm run build
npm run e2e
```

The current Playwright test verifies the frontend route and scan form behavior. The deterministic
crawl workflow is covered by backend integration tests using an HTTPX test transport; full
frontend/backend/fixture orchestration remains a follow-up for PR 1 hardening.

Runtime databases and captured HTML are written under `data/` and ignored by Git.

## Scan Workflow UI

The new scan form accepts a bare hostname such as `example.com` and converts it to
`https://example.com/` before submission. Client-side validation rejects missing URLs, invalid
URLs, unsupported schemes, hostless URLs, and invalid numeric limits before the API request is sent.
Backend validation remains the source of truth.

Advanced scope lists are edited as raw textarea content and parsed only when the scan is created.
Use one value per line; blank lines are ignored. Non-sensitive preferences are remembered in local
storage for maximum pages, maximum depth, and whether the advanced settings section was expanded.
Host/path/query scope values are not reused automatically across unrelated scans.

The scan detail route uses URL state for tabs and page filters. Supported page filter parameters
include `tab`, `search`, `status`, `host`, `path_prefix`, `min_depth`, `max_depth`, `error_state`,
`sort`, `direction`, `limit`, and `offset`. Search is debounced and sent to the existing server-side
page API rather than filtering an incomplete client-side result set.

Stored HTML is always displayed as escaped text in a monospace source viewer. The dashboard does not
execute stored HTML and does not use `dangerouslySetInnerHTML`; the raw HTML API continues to return
`text/plain`.

The Playwright workflow test uses mocked scanner API responses to cover frontend UX behavior. It is
not a complete real-crawler integration test; deterministic crawler behavior remains covered by the
backend integration tests.

## Scan History, Inbound Links, and Deletion

The sidebar shows recent scans, and `/scans` provides server-side paginated scan history for older
runs. The All Scans page supports search by starting URL, status filtering, sorting, rerunning a scan
with its previous scope, and deleting terminal scans after reviewing a confirmation summary.

Page results show scan-specific inbound link counts. Counts are limited to occurrences whose source
page snapshot belongs to the same scan, so historical scans do not inflate each other. Total inbound
occurrences count duplicate links individually; unique source pages count distinct linking snapshots.

The page detail view has separate Outgoing links and Inbound links tabs. Inbound links are direct
occurrences whose normalized target resource matches the selected page resource in the same scan.
Redirect-mediated attribution is not inferred in PR 3; redirect evidence remains available on the
snapshot overview. The inbound table preserves duplicate occurrences and exposes source page,
status, crawl depth, anchor context, raw href, rel, scope decision, DOM location, and discovery time.

Deletion is allowed only for terminal scans: `completed`, `completed_with_errors`, `failed`,
`cancelled`, and `interrupted`. Queued or running scans return `409 Conflict`; running worker tasks
are checked before deletion. `GET /api/scans/{scan_id}/deletion-summary` and
`GET /api/scans/{scan_id}/delete-preview` return the same typed summary. `DELETE /api/scans/{scan_id}`
returns a typed result.

Deleting a scan removes its snapshots, source link occurrences, unreferenced content blobs, and web
resources no longer referenced by snapshots or remaining occurrences. HTML blobs are deleted through
the content-store abstraction only after database cleanup commits. Shared blobs stay available for
other scans. If a blob file is already missing or cannot be deleted after commit, the scan deletion
still succeeds and returns a cleanup warning for later maintenance.

## Saved Sites

Sites are saved website properties above individual scans. A site stores a name, base URL,
description, group, locale, platform, ownership, active state, and reusable scan scope configuration.
Group, platform, and ownership are user-defined labels, so teams can add their own organization
terms without a code change.

Saved site scope uses the same shape as scan scope. When a scan starts from a site, the effective
scope is copied into the scan row with `website_property_id`. Later edits to the site do not rewrite
historical scan scope, and scan-specific overrides do not mutate the saved site. Ad hoc scans still
work with no site relationship.

`/sites` lists saved sites with server-side search, filters, sorting, and pagination. Site detail
shows saved metadata, saved scope, latest scan, recent scans, and total scan count. Inactive sites
remain inspectable and retain scan history, but they are excluded from the default saved-site scan
selector and cannot start new scans.

Site deletion is conservative. A site with scans returns `409 Conflict` and must keep its scan
history intact. A site with no scans can be deleted permanently. Deleting a scan associated with a
site leaves the site record intact and updates site aggregates on the next query.

No TechSmith sites are seeded automatically. TechSmith-like records can be created manually for local
testing, but core models, APIs, and crawler behavior remain generic.

## URL Sources and Inventory

Saved sites can now own reusable URL sources. PR 6 supports sitemap sources, robots.txt sitemap
discovery, and manual URL batches. Source refreshes fetch with the same SSRF destination checks,
redirect validation, timeout limits, and response-size limits used by crawling. Sitemap XML is parsed
without networked DTD/entity loading, and `.gz` sitemap responses are decompressed with a bounded
limit before parsing.

The Sources tab on a site lets users add a sitemap URL, discover sitemap directives from
`/robots.txt`, refresh a source, delete a source, or paste manual URLs one per line. The Inventory
tab groups current source entries by normalized URL and shows their source provenance, scope
decision, validation state, and whether the URL has been seen by scans. Out-of-scope and invalid
source entries are preserved for review but are not queued for crawling.

When starting a scan from a saved site, users can include the current URL inventory. The scan stores
explicit `ScanSeed` rows with `ScanSeedOrigin` provenance, so later source edits do not rewrite the
inputs used by an existing scan. Inventory seeds respect scope and page limits before being queued;
the crawler still deduplicates fetched resources by normalized URL.

Deleting a URL source removes its source entries and refresh history. Resource cleanup remains
reference-aware: resources still referenced by scans, link occurrences, source entries, or scan seeds
are preserved. Deleting a scan removes its scan seeds and seed origins without deleting the saved
site or source configuration.

Source refreshes run synchronously in the current API request. A background refresh worker and
progress polling are intentionally left for a later PR.

Current npm production audit status: `npm audit --omit=dev` reports React Router advisories in the
available registry ranges for both the existing v6 line and npm's suggested v7 targets. The
application does not use React Router SSR/RSC features, but the audit remains a known dependency
advisory until the package publishes or resolves a non-vulnerable compatible target.

## Website Topology Graph

Scan detail includes a Graph tab at `/scans/{scan_id}?tab=graph`. The graph is read-only and is
derived from the selected scan's page snapshots and stored page-link occurrences. Page snapshots are
nodes; repeated links from the same source page to the same target page are aggregated into one
directed edge with occurrence counts and sample anchor text. Edge occurrence details are loaded
through a separate paginated API only after an edge is selected.

Graph filters and display controls are stored in URL parameters. Users can filter by host, path,
depth, status, errors, connectivity thresholds, self-links, and optional unfetched internal pages.
Display controls include 2D/3D mode, node sizing, node categorization, labels, arrows, edge width,
background, presentation mode, and PNG export. Search and the node/edge browser panels provide an
accessible alternative to canvas-only exploration.

The graph is bounded by deterministic server-side limits. The default graph returns up to 400 nodes
and 1,200 edges; hard caps are 1,500 nodes and 5,000 edges. The API prioritizes the starting page,
then shallow crawl depth, stronger connectivity, URL, and snapshot ID. Focused neighborhood mode can
load one to three hops around a selected snapshot.

The 2D and 3D graph renderers are lazy-loaded. The production build currently emits separate graph
chunks for the 2D renderer and the Three.js-backed 3D renderer; the 3D chunk is large enough to
trigger Vite's chunk-size warning, so it stays isolated from the initial application bundle.

