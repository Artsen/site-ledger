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

The sidebar shows recent scans, and `/scans` provides paginated scan history for older runs. Terminal
scans can be deleted after reviewing a delete preview. Running or queued scans must be cancelled or
finish before deletion is allowed.

Page results now show scan-specific inbound link counts. Counts are limited to occurrences whose
source page snapshot belongs to the same scan, so historical scans do not inflate each other. The
page detail view includes an Inbound tab that lists every occurrence pointing to the current page,
including duplicate links and self-links, with source page metadata and provenance.

Deleting a scan removes its snapshots and link occurrences. HTML blobs are deleted through the
content-store abstraction only when no remaining scan references them; shared blobs stay available
for other scans.

