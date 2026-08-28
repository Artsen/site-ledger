# Structured Page Content

Structured Page Content is a deterministic derivative of exact retained static HTML:

```text
Exact retained ContentBlob
    -> Structured Content V2 canonical document
    -> Outline / deterministic Markdown / future consumers
```

Exact HTML remains authoritative evidence. The current derivative identity is
`structured-content-v2 | canonical-document-v1 | ContentBlob`; deterministic Markdown uses
`structured-markdown-v1`. Markdown is a renderer output, not canonical truth.

## Canonical Document

V2 preserves meaningful structure without mirroring every DOM wrapper. Persisted structural node
kinds are `document`, `section`, `heading`, `paragraph`, `list`, `list_item`, `figure`, `caption`,
`blockquote`, `code_block`, `table`, `table_row`, `table_cell`, `definition_list`,
`definition_term`, `definition_description`, `thematic_break`, and `generic_block`.

Headings create deterministic semantic sections while retaining source-faithful h1-h6 levels,
duplicates, empty headings, multiple h1 elements, and skipped levels. Incidental `div` and
`section` wrappers are flattened. Unknown content-bearing block elements use `generic_block`.
Section and database node IDs are artifact-local; cross-artifact section identity and matching are
not implemented.

Small inline semantics are retained as bounded ordered runs on structural rows instead of one SQL
row per text fragment. Runs preserve text, links with nested display runs, images, inline code,
strong/emphasis marks, and line breaks. Normal prose uses deterministic whitespace normalization;
preformatted code retains indentation and line breaks after line-ending normalization.

`head`, `script`, `style`, `template`, `noscript`, and `svg` content is excluded. Extraction is
static-source-derived: it does not execute JavaScript, apply CSS, infer visual visibility, inspect
screenshots, or use Rendered DOM or accessibility evidence.

## Source And URL Semantics

V2 is scoped to the exact ContentBlob, not an observation URL. Parser-observed relative `href` and
`src` values remain unresolved, so one blob reused by observations with different URL bases still
has one canonical artifact. Context-aware URL resolution belongs to a future consumer with its own
provenance.

Useful parser-observed attributes are retained under deterministic per-node count and character
bounds: `href`, `src`, `alt`, `title`, `rel`, `target`, `width`, `height`, `start`, `type`, `scope`,
`colspan`, `rowspan`, `id`, and `class`. They are not byte-exact source lexemes because lxml cannot
preserve original quoting, order, or entity syntax. Event-handler attributes are not retained or
executed. Exact attribute evidence remains in the ContentBlob.

DOM and region paths (`main`, `article`, `nav`, `header`, `footer`, `aside`, `body`, or `unknown`)
are provenance. Incidental paths and wrappers do not participate in semantic identity.

## Hashes And Bounds

Each structural node has a semantic hash over its kind, normalized text, inline semantics, and
kind-specific semantics. Its subtree hash adds ordered child hashes. The artifact records a
canonical document hash, source-faithful outline hash, document-text hash, and deterministic
Markdown hash. IDs, timestamps, observation/Site/Scan context, DOM paths, and parser object identity
are excluded.

Extraction is bounded by structural node count, retained text characters, nested inline run count,
document depth, parser-observed attributes per node, and attribute characters per node. A reached
bound produces `partial` state with explicit deterministic truncation reasons; it never claims
completeness. API document reads are paginated up to 2,000 rows per request. Markdown reads are
bounded and expose partial and total-character headers.

## Persistence And Reuse

`HtmlStructuredContentArtifact` remains the versioned ContentBlob-scoped root. V2 adds canonical
document and Markdown metadata to that root and stores ordered structure in
`HtmlStructuredContentNode`. The unique identities are extractor/config per blob and position per
artifact.

An exact 304 or later observation that references an existing ContentBlob reuses its compatible V2
artifact and nodes. Rebuilding replaces only the current V2 identity. Historical
`structured-content-v1 | default-v1` artifacts and `HtmlStructuredContentSection` rows remain
stored, unchanged, and diagnosable. Blobs with only V1 report current V2 as `not_prepared` until the
existing Prepare workflow creates V2 beside V1; there is no bulk migration backfill.
Downgrading below the V2 schema removes only `structured-content-v2 | canonical-document-v1`
derivatives because schema V1 cannot represent them; retained ContentBlobs and V1 derivatives remain.

Deleting one observation does not delete a derivative shared by other observations. Legitimate
ContentBlob deletion cascades to its derivative rows through the existing content lifecycle.

## Markdown

`structured-markdown-v1` renders the canonical IR deterministically. It supports headings,
paragraphs, unresolved links and images, nested ordered/unordered lists, figures/captions,
blockquotes, inline and fenced code, readable tables including span labels, definition lists, line
breaks, thematic breaks, and readable generic-block fallback. Fence length is selected from code
content so embedded backticks cannot terminate a block. Arbitrary retained HTML is never passed
through as executable markup.

Pipe tables use the first source row as the Markdown header only when every cell in that row is a
source `th`. Tables with a `td`-only or mixed first row receive a neutral blank Markdown header so
every source row remains data. Destinations remain unresolved; values containing spaces,
parentheses, backslashes, or angle brackets use deterministic angle-bracket Markdown destination
syntax without changing canonical inline evidence.

## API And UI

Existing Outline and Prepare routes remain:

- `/api/snapshots/{snapshot_id}/structured-content`
- `/api/sites/{site_id}/pages/{resource_id}/structured-content`
- matching `/prepare` routes
- `/api/sites/{site_id}/structured-content/prepare` for durable historical preparation

Bounded V2 reads add `/structured-content/document` and `/structured-content/markdown` beneath
both observation and persistent-Page routes. Markdown responds as `text/markdown` and exposes
extractor, config, renderer, hash, partial-state, and total-character headers. The Content UI offers
Outline, Document, and escaped Markdown views plus Copy Markdown.

Historical bulk preparation continues through the durable `structured_content_build` job and its
existing lease, ownership-loss, cancellation, and progress contracts. CLI diagnostics remain:

```powershell
python -m app.structured_content build-missing --site-id 1 --limit 500
python -m app.structured_content build-missing --scan-id 10 --stop-on-error
python -m app.structured_content build 123
python -m app.structured_content rebuild 123
python -m app.structured_content verify 123
```

## Independence And Limits

Preparing or rebuilding V2 does not change `scan-projection-v2`, `scan-comparison-v3`,
`document-content-v2`, Page Change History, Render/Performance/Accessibility evidence, URL identity,
Page identity, graph identity, or their checksums. V2 hashes are not comparison inputs in this PR.

Not included: section matching or comparison, full-text search/FTS, rendered-DOM extraction,
Resource/PDF bodies, Findings, embeddings/RAG/AI interpretation, or exotic HTML round-trip
fidelity. Run `python -m app.structured_content_benchmark` for local extraction, persistence,
exact-reuse, rebuild, Markdown, bounded-read, row-growth, storage, memory, and determinism metrics;
these are engineering diagnostics rather than production SLA claims.
