# PR 1 Architecture

The scanner is split into explicit boundaries:

- `crawler.url_normalizer` resolves and normalizes URLs without merging distinct resources.
- `crawler.scope` applies persisted scan scope and returns one deterministic decision per URL.
- `crawler.html_parser` extracts head metadata and anchor provenance from best-effort parsed HTML.
- `storage.content_store` stores exact response bytes as gzip-compressed content-addressed blobs.
- `crawler.static_crawler` performs breadth-first HTTP GET crawling and persists partial results.
- `services.scan_runner` keeps in-process scan execution replaceable by a later worker queue.
- `api.routes` exposes scan, page, snapshot, link, HTML, and occurrence endpoints.

PR 1 deliberately excludes asset inventory, rendered crawling, sitemap ingestion, analytics integrations, scheduled scans, AI features, and multi-user permissions.

