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

## PR 3 Inbound Links and Scan Lifecycle

Inbound link counts and discovery sources are computed with set-based scan-specific queries in
`services.scan_queries`. Occurrences are counted only when their source snapshot belongs to the same
scan as the target page snapshot. Page-list aggregation returns both total inbound occurrences and
unique source-page counts without per-row SQL loops.

`GET /api/snapshots/{snapshot_id}/inbound-links` returns a paginated, typed list of every inbound
link occurrence for the target snapshot's scan and resource, plus summary counts for total
occurrences, unique source pages, unique anchor texts, nofollow occurrences, and self-links.
Inbound attribution is intentionally direct: a stored occurrence points to the selected resource's
normalized URL identity. A link to URL A is not reported as inbound to URL B just because URL A later
redirects to URL B. Redirect-mediated attribution requires final-resource identity and remains
future work.

`services.scan_deletion` owns scan deletion preview and execution. It allows deletion only for
terminal scans, deletes source occurrences and snapshots explicitly, and removes unreferenced
content blobs through the content-store abstraction. Blobs referenced by another scan are preserved.
The local content store exposes `delete()` so later object-storage implementations can provide the
same lifecycle operation.

`GET /api/scans/history` is the complete scan-history query surface. It is server-side paginated and
supports starting-URL search, status filtering, sort, direction, limit, and offset. The lightweight
`GET /api/scans` recent-scans endpoint remains for the sidebar.

Deletion summaries and deletion execution share the same impact calculation so the preview cannot
drift from the actual cleanup rules. The service calculates candidate blob and resource IDs before
deleting scan-owned rows, commits database cleanup before removing files, and returns warnings for
missing or failed physical-file cleanup. A rollback cannot leave a live snapshot pointing at a file
that was already removed because files are never deleted before the database commit succeeds.

After scan-owned rows are removed, candidate `WebResource` rows are deleted only when no remaining
snapshot references them and no remaining occurrence targets them. These query and lifecycle service
boundaries are intended to be reused by future findings, broken-link aggregation, scan comparison,
retention policies, alternate storage backends, and link visualizations without adding a speculative
plugin architecture.

## PR 4 Saved Sites

`WebsiteProperty` represents a saved Site above scans. It stores generic site metadata, a normalized
base URL, active state, user-defined group/platform/ownership labels, and a saved `scope_config`
JSON object using the same schema as scan creation. Classification labels are normalized and
validated centrally, but they are not hardcoded crawler behavior switches.

`Scan.website_property_id` is nullable. Existing and future ad hoc scans remain valid with no site
relationship. Saved-site scans store both the site relationship and a copied effective `scope_config`
snapshot, so editing a site later does not alter historical scan behavior.

`services.site_management` owns creation, update, duplicate base URL validation, active/inactive
state changes, scan creation from an active site, and conservative site deletion. A site with scans
cannot be deleted; scan deletion and site deletion remain separate lifecycle operations.

`services.site_queries` owns paginated site listing, site detail aggregates, and site scan history.
The site list uses set-based scan counts and latest-scan joins rather than querying scans for each
site row. `/api/sites` supports server-side search, classification filters, active-state filtering,
sorting, limit, and offset.

Future sitemap, analytics, comparison, scheduling, monitoring, ownership, tagging, and integration
features should extend the saved-site layer through focused related tables or services. PR 4 does
not add empty integration columns, scheduled scans, seed data, or organization/user permission
models.

## PR 6 URL Sources and Inventory

URL sources are saved-site children, not crawler plugins. `UrlSource` stores source configuration,
`SourceRefresh` stores one fetch/parse attempt, and `UrlSourceEntry` stores each URL observed from
that source with raw URL, normalized URL, current membership, validation state, scope decision, and
source-specific metadata. Valid in-scope entries link to `WebResource`; invalid or out-of-scope
entries are retained without being crawlable resources.

`services.source_refresh` owns robots.txt sitemap discovery and sitemap refreshes. It uses
`crawler.safe_fetch.SafeHttpFetcher` so source ingestion and page crawling share redirect limits,
SSRF destination checks, timeout handling, user-agent handling, and streamed response-size
enforcement. Sitemap XML parsing lives in `parsers.sitemap`; robots directives live in
`parsers.robots`; gzip detection and bounded decompression live in `parsers.compression`.

Sitemap index children are represented as child `UrlSource` rows linked through
`parent_source_id` and `root_source_id`. Child refreshes reuse the same scope and safety checks as
top-level sitemap refreshes, and cycle/child-count limits prevent unbounded source expansion.
Robots discovery creates or reuses a `robots_txt` source for the site and child sitemap sources for
the discovered `Sitemap:` directives.

`services.source_queries` owns source, source-entry, refresh, and inventory list queries. Inventory
groups current entries by normalized URL and exposes multi-source provenance plus latest crawl
status when a linked resource has scan snapshots. This is deliberately source inventory, not a
replacement for scan results: scan pages remain observations from crawler fetches.

Scan starts from saved sites can include current inventory entries. `services.scan_seeds` snapshots
the selected source entries into `ScanSeed` and `ScanSeedOrigin` rows before the scan is queued.
The crawler reads queued seeds at startup and marks them fetched or failed as it processes them.
This preserves scan input provenance even if sources are refreshed or deleted later.

Deletion rules include the new source tables. Source deletion cascades source config, refreshes, and
entries, then removes only resources no longer referenced by snapshots, occurrences, other source
entries, or scan seeds. Scan deletion removes seed origins and seeds for that scan while preserving
source configuration and source-owned resources still in use.

Source refreshes are synchronous in PR 6. A later worker can move `refresh_source` behind a queue in
the same way `services.scan_runner` hides crawler execution.

## Deferred

Robots.txt enforcement and concurrent crawling remain internal configuration placeholders for a
future PR. PR 1 executes a sequential static crawl and may apply a configured delay between
requests.

The Playwright coverage currently exercises the frontend scan form route. Complete deterministic
crawl behavior, including redirect and response-size handling, is covered in backend integration
tests through mocked HTTP transports.

Rendered crawling, asset inventory, analytics integrations, scheduled scans, AI features, and
multi-user permissions remain excluded.

