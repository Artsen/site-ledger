# Site Ledger Page History and Conditional Reuse

Site Ledger keeps Page identity and Page observation separate:

- `WebResource` is the stable normalized page identity.
- `SitePage` is the saved-Site association that preserves manual Page metadata across Scan deletion.
- `ResourceSnapshot` is one observation of that page during one scan.
- `HtmlParseArtifact` is reusable parsed HTML output for one content blob, parser version, parser
  configuration, and final URL resolution base.
- `HtmlParseAnchor` stores ordered anchor extraction for an artifact.
- `ResourceOccurrence` remains scan-specific provenance and is recreated for every scan.

This lets saved sites show persistent page history without losing exact scan evidence.

Terminal Scan catalogs may read a versioned `ScanPageProjection`, but Page identity and exact
observation detail remain `WebResource` and `ResourceSnapshot`. Content/head hashes in the
projection support future compatible comparisons without rewriting historical observations. See
[Scan projections](scan-projections.md).

## Parse Artifact Identity

The content hash is not enough to identify parsed output. Relative URLs, protocol-relative URLs, and
canonical URLs are resolved against the final page URL, so the final URL resolution base is part of
the artifact key.

Artifact identity is:

```text
content_blob_id + parser_version + parser_config_version + resolution_base_url
```

When the same artifact exists, the crawler can reuse parsed head metadata and ordered anchors. When
reuse is disabled, the crawler performs a fresh parse pass but still does not create duplicate
artifact rows for an identical artifact identity.

## Conditional HTTP Revalidation

For repeat saved-site scans, the crawler may use a prior observation as a revalidation candidate when
all of these are true:

- The previous snapshot belongs to the same normalized resource.
- The previous result is fetched HTML with an existing content blob.
- The previous response has an ETag or Last-Modified validator.
- `Cache-Control` does not include `no-store`.
- `Vary` is empty or names only crawler-controlled representation headers.
- The stored request variant fingerprint is compatible with the current request headers.

The crawler sends only allowlisted caller headers through `SafeHttpFetcher`: conditional validators
and representation headers. Browser cookies and credentials are never forwarded.

## `304 Not Modified` Snapshots

A successful `304 Not Modified` response creates a fresh `ResourceSnapshot`. The snapshot stores:

- `http_status`: the reused effective page status, usually `200`.
- `retrieval_http_status`: the actual retrieval status, `304`.
- `retrieval_method`: `conditional_not_modified`.
- `parse_method`: `reused_not_modified`.
- `html_blob_id`, hashes, and parsed head fields reused from the prior observation.
- `reused_from_snapshot_id`: the prior observation used as evidence.

The crawler then recreates link and embedded-Resource occurrences for the current Scan from the
current parse artifact and scope configuration. It does not reuse old Scan occurrence rows.

Current parser artifacts also store occurrence-specific link role and rule evidence. Scope remains
scan-specific and is recomputed when anchors are reused. See [Page workspaces](page-workspaces.md).
Parser v3 also stores duplicate-preserving embedded references; see
[Resource Inventory](resource-inventory.md).

## Limits

This is a crawl optimization, not a general browser cache. It intentionally does not implement
freshness lifetime calculation, cache revalidation merging rules beyond preserving prior effective
headers for unchanged content, authenticated caching, private-network crawling, or JavaScript-rendered
page state.

If compatibility is uncertain, the crawler falls back to a full GET or records a structured crawler
error through the existing safe fetch path.

Effective reused content/head hashes participate in deterministic comparison exactly like hashes
from a full response. Persistent Page Change History compares the previous observed snapshot and
preserves intervening Scan gaps. See [Deterministic Scan comparisons](scan-comparisons.md).
