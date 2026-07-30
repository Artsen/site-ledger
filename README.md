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

