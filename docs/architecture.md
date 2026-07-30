# PR 1 Architecture

The scanner is split into explicit boundaries:

- `crawler.url_normalizer` resolves and normalizes URLs without merging distinct resources.
- `crawler.scope` applies persisted scan scope and returns one deterministic decision per URL.
- `crawler.html_parser` extracts head metadata and anchor provenance from best-effort parsed HTML.
- `storage.content_store` stores exact response bytes as gzip-compressed content-addressed blobs.
- `crawler.static_crawler` performs breadth-first HTTP GET crawling and persists partial results.
- `services.scan_runner` keeps in-process scan execution replaceable by a later worker queue.
- `api.routes` exposes scan, page, snapshot, link, HTML, and occurrence endpoints.
- `frontend/src/components/ui` contains small shared UI primitives used by the current scanner
  workflow only. It is not intended as a speculative design system.

## Scope Defaults

When a scan has no explicit `allowed_host_patterns`, the scope engine derives the exact starting
hostname and does not include sibling hosts or subdomains. Subdomains require either an explicit
wildcard pattern or `follow_subdomains` with an allowed base host.

No TechSmith-specific host set is hardcoded. Site-specific configuration is deferred to future
saved-site records.

## Redirects and Response Limits

Redirects are not followed automatically by HTTPX. The crawler validates each redirect target
against scope and SSRF network rules before issuing the next GET, and stores the redirect-chain
evidence with requested URL, status, raw `Location`, and resolved destination URL.

Final response bodies are read through HTTPX streaming. `Content-Length` is checked before reading
when present, and streamed chunks are counted so oversized responses are stopped and categorized as
`response_too_large` without storing a partial content blob.

Unsafe redirect destinations blocked by network safety checks are categorized as
`unsafe_destination`; configured scope rejections are categorized as `scope_excluded`.

## PR 2 UI and API Additions

The scan workflow UI now keeps scan tabs and page filters in URL search parameters so refreshes,
browser navigation, and shared links preserve context. Page search is debounced before requesting
server-side results.

The page-list API remains backward compatible and adds optional `min_depth` and `max_depth`
parameters alongside the existing exact `depth` filter. Snapshot reads include additive
`html_raw_byte_size` and `html_stored_byte_size` fields derived from the related content blob when
available. No persistence migration is required.

The page detail view presents snapshot overview data, redirect chains, head metadata, link
occurrences, and raw HTML without using raw JSON as the primary interface. Raw HTML remains escaped
and non-executable in the dashboard; the HTML endpoint remains `text/plain`.

## Deferred

Robots.txt enforcement and concurrent crawling remain internal configuration placeholders for a
future PR. PR 1 executes a sequential static crawl and may apply a configured delay between
requests.

The Playwright coverage currently exercises the frontend scan form route. Complete deterministic
crawl behavior, including redirect and response-size handling, is covered in backend integration
tests through mocked HTTP transports.

PR 1 deliberately excludes asset inventory, rendered crawling, sitemap ingestion, analytics integrations, scheduled scans, AI features, and multi-user permissions.

