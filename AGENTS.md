# Codex Instructions

## Project

This repository contains **Artsen Design Scanner**, the first implementation of a reusable website inventory and observability platform. The initial real-world target is the TechSmith website estate, but the crawler and scope model must remain generic so the application can later scan other sites.

The long-term product may include page inventories, sitemaps, media and asset inventories, change history, GA4, Google Search Console, PageSpeed, international-site relationships, uptime monitoring, accessibility checks, deployment correlation, and AI-assisted investigation.

Do not attempt to build that entire product in the first pull request.

## Current milestone: PR 1, scoped page scanner

Build one complete vertical slice that lets a user:

1. Enter a starting URL.
2. Configure reusable crawl scope settings.
3. Start a scan.
4. Watch scan progress.
5. See all discovered HTML pages.
6. Inspect where each page link was discovered.
7. Preserve the complete HTML response and parsed head metadata for each fetched page.
8. Reopen completed scans after restarting the application.

PR 1 handles pages only. It may encounter images, scripts, stylesheets, videos, fonts, documents, and iframes, but it must not inventory those resource types yet.

## Required stack

Use this stack unless an existing implementation in the repository clearly establishes something else:

- Backend: Python, FastAPI, SQLAlchemy 2, Alembic, SQLite, httpx, and lxml
- Frontend: React, TypeScript, Vite, TanStack Query, and Tailwind CSS
- Backend tests: pytest
- Frontend tests: Vitest and Testing Library
- End-to-end tests: Playwright
- Python quality checks: Ruff and mypy
- Frontend quality checks: ESLint and TypeScript type checking

SQLite is the initial database, but persistence code must not depend on SQLite-only behavior when a normal SQLAlchemy solution exists. Keep the design portable to PostgreSQL.

The first crawler is a static HTTP crawler. Do not use browser rendering for PR 1.

## Repository shape

Prefer this structure:

```text
backend/
  app/
    api/
    crawler/
    models/
    schemas/
    services/
    storage/
    config.py
    database.py
    main.py
  alembic/
  tests/
  pyproject.toml
frontend/
  src/
    api/
    components/
    features/scans/
    pages/
    styles/
    types/
  tests/
  package.json
data/
  html/
docs/
```

The `data/` directory and local database files must be ignored by Git.

## Domain model

Use generic resource-oriented names internally even though PR 1 exposes only pages.

### Scan

A scan stores:

- Starting URL
- Status
- Complete scope configuration as JSON
- Created, started, and finished timestamps
- Counts for discovered, fetched, failed, and skipped pages
- Stop reason
- Fatal error message, when applicable

Supported statuses:

- `queued`
- `running`
- `completed`
- `completed_with_errors`
- `failed`
- `cancelled`
- `interrupted`

On application startup, a scan left in `running` state must be changed to `interrupted`. PR 1 does not need scan resumption.

### WebResource

A stable normalized URL identity across scans.

Required fields include:

- Resource type
- Normalized URL
- Scheme
- Host
- Port
- Path
- Query
- First seen
- Last seen

For PR 1, the resource type is `page`.

### ResourceSnapshot

One observation of one resource during one scan.

Store at least:

- Scan and resource IDs
- Requested URL
- Final URL
- HTTP status
- Content type and encoding
- Crawl depth
- Fetch timestamp
- Response time
- Response headers
- Full redirect chain
- HTML blob reference
- Raw HTML SHA-256
- Head SHA-256
- Page title
- HTML language
- Meta description
- Meta robots
- Canonical URL
- Parsed head JSON
- Fetch state
- Categorized error type and message

### ResourceOccurrence

One resource reference found inside another resource.

For every anchor occurrence, retain:

- Source snapshot
- Relation type, initially `page_link`
- Raw `href`
- Resolved absolute URL
- Normalized target URL
- Target resource ID when known
- Anchor text
- `title`
- `aria-label`
- `rel`
- `target`
- Compact DOM path or selector
- In-scope boolean
- Scope decision and exclusion reason
- Discovery timestamp

Do not collapse duplicate links into one record. Aggregation belongs in queries and the UI. Provenance is a first-class requirement.

### ContentBlob

Store full HTML through a content-addressed storage abstraction.

Process:

1. Keep the exact response bytes.
2. Calculate SHA-256.
3. Gzip-compress the content.
4. Store it under a hash-derived path.
5. Reuse an existing blob when the hash already exists.

Store:

- SHA-256
- Storage key
- Compression type
- Content type
- Encoding
- Raw byte size
- Stored byte size
- Creation time

Do not put large HTML bodies directly in the main snapshot table.

The storage interface must make it possible to replace local disk storage with object storage later.

## Crawl behavior

Use breadth-first traversal.

The crawler must:

- Use `GET` requests only.
- Never submit forms.
- Never execute JavaScript.
- Follow redirects while preserving the full redirect chain.
- Re-evaluate scope after every redirect.
- Record `nofollow` but still crawl an otherwise in-scope internal link.
- Record `noindex` but still inventory the page.
- Save partial results when individual pages fail.
- Deduplicate fetches by normalized URL.
- Preserve the raw discovered URL, normalized URL, requested URL, and final URL separately.
- Respect configured page, depth, timeout, redirect, response-size, and concurrency limits.
- Treat HTTP error statuses as fetch results, not crawler exceptions.
- Record external and excluded links as occurrences without adding them to the crawl queue.
- Ignore fragment-only links for crawling while retaining useful occurrence information.
- Parse malformed HTML on a best-effort basis.

A scan with page-level failures should normally finish as `completed_with_errors`, not `failed`.

## Scope configuration

Scope is data owned by each scan. Do not hardcode TechSmith rules into the crawl engine.

Support these settings:

- Allowed host patterns
- Excluded host patterns
- Included path prefixes
- Excluded path prefixes
- Follow-subdomains behavior where useful
- Maximum pages
- Maximum depth
- Respect robots.txt
- Request timeout
- Maximum HTML response size
- Concurrent requests per host
- Delay between requests
- Custom user agent
- Query parameters to drop

Pattern matching must be deterministic and unit tested. Prefix matching is sufficient for paths in PR 1. Avoid adding regular-expression scope rules unless required by an actual failing use case.

Every discovered URL must receive one explicit scope decision, such as:

- `crawlable`
- `already_seen`
- `excluded_host`
- `excluded_path`
- `external`
- `unsupported_scheme`
- `invalid_url`
- `robots_disallowed`

### TechSmith starter preset

Provide a UI preset, not crawler-specific code, that can cover:

Allowed host families:

- `techsmith.com`
- `*.techsmith.com`
- `techsmith.de`
- `*.techsmith.de`
- `techsmith.fr`
- `*.techsmith.fr`
- `techsmith.es`
- `*.techsmith.es`
- `techsmith.co.jp`
- `*.techsmith.co.jp`
- `techsmith.pt`
- `*.techsmith.pt`

Excluded host pattern:

- `support.*`

Default excluded paths:

- `/wp-admin/`
- `/wp-login.php`

Default removable query parameters:

- `utm_*`
- `gclid`
- `fbclid`
- `msclkid`

Do not discard all query strings. Preserve functional query parameters unless configured otherwise.

## URL normalization

Normalization must be isolated in its own module and covered by focused tests.

Normalize where safe:

- Hostname casing
- Internationalized host representation
- Default ports
- Dot segments
- Empty fragments
- Configured tracking parameters
- Retained query parameter ordering

Do not automatically:

- Lowercase paths
- Remove every trailing slash
- Treat HTTP and HTTPS as identical
- Treat canonical URLs as resource identity
- Remove all query parameters

Canonical metadata is an observation and must not silently merge resources.

## Parsed HTML and head data

Preserve the complete HTML and also extract common fields for immediate filtering and display.

Extract at least:

- `<html lang>`
- `<title>`
- Meta description
- Meta robots
- Canonical URL
- Character encoding
- Viewport declaration
- All meta tags in order
- All head link elements in order
- Open Graph metadata
- Twitter metadata
- JSON-LD script blocks
- Ordered head representation

Use both normalized columns for common fields and a generic JSON structure for complete head data.

Stored HTML must never execute inside the dashboard. Display it as escaped source text. Raw HTML endpoints must return `text/plain` or a download attachment.

## Error categories

Use structured error types rather than one generic error string.

Include at least:

- `dns_error`
- `connection_error`
- `connection_timeout`
- `read_timeout`
- `tls_error`
- `redirect_loop`
- `too_many_redirects`
- `response_too_large`
- `invalid_url`
- `parse_error`
- `robots_disallowed`
- `scope_excluded`
- `unsupported_scheme`
- `unsupported_content_type`

HTTP statuses such as 404, 429, 500, and 503 are successful HTTP observations and should still create snapshots where possible.

## Security requirements

A crawler is an SSRF boundary. PR 1 must:

- Allow only HTTP and HTTPS.
- Reject file, FTP, data, JavaScript, and other unsupported schemes.
- Block loopback, link-local, and private network destinations by default.
- Recheck resolved IP addresses after redirects.
- Enforce redirect, timeout, response-size, page-count, and depth limits.
- Never forward browser cookies or user credentials.
- Never execute scanned HTML.
- Prevent redirects from escaping the configured allowlist.
- Use a descriptive crawler user agent.

Authenticated and private-network crawling are future features and must require explicit configuration when added.

## API expectations

Provide endpoints equivalent to:

```text
POST /api/scans
GET  /api/scans
GET  /api/scans/{scan_id}
POST /api/scans/{scan_id}/cancel
GET  /api/scans/{scan_id}/pages
GET  /api/scans/{scan_id}/errors
GET  /api/snapshots/{snapshot_id}
GET  /api/snapshots/{snapshot_id}/links
GET  /api/snapshots/{snapshot_id}/html
GET  /api/resources/{resource_id}/occurrences
```

Use pagination and server-side filtering for page results. At minimum support search, status, host, path prefix, depth, error state, sorting, and pagination.

An in-process asynchronous scan runner is acceptable for PR 1, but place it behind an interface so a worker queue can replace it later.

Polling every one or two seconds is acceptable for scan progress. Do not add WebSockets unless there is a clear need.

## UI expectations

Create a clean, restrained interface inspired by the current ChatGPT layout without copying proprietary assets.

PR 1 routes:

- `/scans/new`
- `/scans/:scanId`
- `/scans/:scanId/pages/:snapshotId`

Initial sidebar:

- Product name
- New Scan
- Recent scans

Do not fill the sidebar with nonfunctional future modules.

The new-scan form should show:

- Starting URL
- Scope preset
- Maximum pages
- Maximum depth
- Expandable advanced scope settings
- Start button

The live scan screen should show:

- Status
- Discovered count
- Fetched count
- Queue count
- Error count
- Recent or current pages
- Cancel action

Completed scan tabs:

- Overview
- Pages
- Errors

Page detail tabs:

- Overview
- Head
- Links
- HTML

The page table should include requested URL, final URL, status, title, depth, content type, discovery source, inbound occurrence count, fetch duration, and error state.

Favor clarity and density over decorative dashboard cards. The graph visualization is not part of PR 1.

## Tests

Do not consider the milestone complete without automated coverage.

### Unit tests

Cover:

- Exact and wildcard host scope
- Excluded hosts
- Included and excluded paths
- External and unsupported URLs
- Redirects that leave scope
- Fragment removal
- Tracking parameter removal
- Query ordering
- Host normalization
- Relative and protocol-relative URL resolution
- Unicode URLs
- Trailing-slash preservation
- Anchor parsing
- Empty and malformed href values
- Canonical and metadata extraction
- JSON-LD extraction
- HTML hashing, compression, deduplication, and retrieval

### Integration fixture site

Create a deterministic local fixture site containing:

- Relative and absolute links
- Redirects
- A 404
- A 500
- An external link
- An excluded path
- Duplicate link occurrences
- Query parameters
- Malformed HTML
- A non-HTML response

Verify the complete crawl result, including provenance and scope decisions.

### End-to-end flow

Test this user journey:

1. Open the application.
2. Enter the fixture-site URL.
3. Configure scope.
4. Start a scan.
5. Wait for completion.
6. Open page results.
7. Select a page.
8. View head metadata.
9. View links and provenance.
10. View escaped HTML.

## Definition of done for PR 1

The milestone is complete only when:

- A scan can be created from the UI.
- Scope is persisted with the scan.
- Host and path rules work.
- Internal HTML pages are recursively discovered.
- External and excluded links are recorded but not crawled.
- Normalized URLs are not fetched repeatedly.
- Redirect chains are retained.
- HTTP results and network errors are distinguished.
- Every link occurrence retains source provenance and anchor context.
- Full HTML is compressed and persisted.
- Identical HTML content reuses a blob.
- Parsed head data is persisted.
- Scan progress is visible.
- Results remain available after application restart.
- Pages can be searched and filtered.
- Page details expose overview, head, links, and raw source.
- Stored HTML cannot execute in the dashboard.
- Tests, linting, and type checks pass.
- Setup and architecture are documented.

## Explicit non-goals for PR 1

Do not implement:

- Sitemap ingestion or robots.txt sitemap discovery
- Browser-rendered crawling
- Image, script, stylesheet, video, font, or document inventories
- Screenshots
- Scan-to-scan change comparison
- GA4
- Google Search Console
- PageSpeed Insights or CrUX
- Accessibility auditing
- Scheduled scans
- Uptime monitoring
- WordPress, Pagely, RS, or WPML integrations
- Authentication-protected crawling
- Multi-user permissions
- AI summaries or natural-language querying

Keep interfaces extensible for these features, but do not create speculative implementations or unused abstractions.

## Working rules for Codex

- Read this file before planning or editing.
- Inspect the repository before creating new structure.
- Build the smallest complete vertical slice that satisfies the milestone.
- Do not replace the required stack or introduce major dependencies without explaining the concrete need.
- Prefer clear modules and typed boundaries over clever abstractions.
- Do not create fake data, placeholder APIs, simulated scanners, or UI controls that do nothing.
- Keep network, parsing, normalization, scope, persistence, and storage concerns separate.
- Keep migrations synchronized with models.
- Add tests with each behavior rather than postponing all tests until the end.
- Run relevant tests, linting, and type checks after changes.
- Fix failures caused by the change. Do not hide them by disabling checks.
- Avoid unrelated refactors.
- Update README and architecture documentation when commands or design decisions change.
- Record any intentional deviation from this plan in the pull request description.
- Never commit secrets, credentials, local databases, HTML capture data, build output, or dependency caches.

## Pull request format

The PR description should include:

- Summary
- User-visible behavior
- Architecture and data-model notes
- Security considerations
- Tests run and results
- Known limitations
- Follow-up work explicitly excluded from the PR

Prefer a focused PR over a large collection of partially implemented future features.
