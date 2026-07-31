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
The stored classification values are stable keys; the UI renders human-readable labels.

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

