# Browser-rendered observations

Browser rendering is a first-class durable evidence collector. A `RenderRun` freezes a bounded set
of `RenderRunTarget` Page identities and effective browser configuration before its asynchronous
job starts. Manual Site/Page Runs do not require a Scan or `ResourceSnapshot`; rerendering selected
targets creates a new Run and new observations without modifying prior evidence.

A Scan with rendering enabled deterministically selects eligible static observations, creates a
linked Render Run with snapshot provenance, and completes according to static crawl evidence.
Saved-Site Scan Runs are owned durably by the Site and survive source Scan deletion with Scan and
snapshot provenance detached. Ad-hoc Scan Runs have no Site owner, remain navigable through their
source Scan, and are deleted with that Scan using reference-aware artifact cleanup. Browser HTTP or
technical outcomes belong to the Render Run and do not change the Scan terminal result. Historical
Scan-bound observations remain readable without invented Run membership.

Static HTTP evidence remains authoritative. Each frozen target receives at most one immutable
RenderedObservation. Rendered DOM is not parsed into static metadata or links and does not
enter the graph. Browser technical success is distinct from requested-Page success: normal Page
screenshots and rendered DOM require a final artifact-eligible main-document HTTP 2xx response.
HTTP 204 and 205 responses retain their exact status but are no-content outcomes, not successful
rendered Pages, and receive no viewport screenshot, full-page screenshot, or rendered DOM. Final
non-followed 3xx responses and explicit HTTP 4xx/5xx responses likewise retain exact status and
bounded diagnostic, network, console, and Page-error evidence, but receive no normal Page
artifacts. HTTP 200 soft challenge or block documents are not heuristically classified yet.

A selected rerender is an explicit new Render Run. It never retries in place and never changes an
existing observation. Target membership is not re-derived from current SitePages when queued work
starts; removing or suppressing a Page workspace does not rewrite an existing Run.

Three consecutive explicit HTTP 429 outcomes open a render circuit for that requested host. Later
selected targets on that host are persisted as `skipped` with
`host_rate_limit_circuit_open`, no navigation status, network rows, or artifacts because Chromium
was not called. A successful or non-429 response resets the consecutive count, and other hosts are
independent. `Retry-After` is retained in the safe response-header evidence, parsed as a bounded
signal, but never causes a worker sleep. Repeated HTTP 503 responses open the circuit only when
each has a valid `Retry-After`; repeated 403, 404, or generic 5xx responses do not open it.

## Runtime

Install and verify Chromium explicitly:

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python -m playwright install chromium
python -m app.browser_check
```

Run the bounded local fixture benchmark with `python -m app.render_benchmark`. It reports capture
duration, observed encoded network bytes, bounded event counts, and artifact bytes without contacting an
external website.

The worker reports package and Chromium availability in its capability metadata. API requests and
jobs never download a browser automatically. Rendering uses one Chromium process per Render Run
and a fresh non-persistent context for every Page.

## Security policy

- Request interception is installed before a Page exists and therefore before navigation.
- Only GET, HEAD, and OPTIONS are allowed.
- Every HTTP(S) request, including redirect hops and subresources, passes destination validation.
- Main-frame navigations must remain within the frozen Run scope.
- Private, loopback, link-local, reserved, and multicast destinations are blocked by default.
- Service workers, popups, downloads, WebSocket/EventSource constructors, and blocking dialogs are
  disabled or dismissed.
- No cookies, authorization values, request bodies, response bodies, or persistent browser profile
  are supplied or stored.
- Sensitive query values and credential-bearing headers are removed before event persistence.
- Chromium is launched without ambient proxy inheritance.

Resource and total network budgets use Chromium CDP observed encoded-byte events, not declared
`Content-Length`. At a crossing, later requests are blocked and active page loading is stopped.
Enforcement can overshoot by the bytes Chromium transfers before reporting the next event. The
wall-clock limit remains an independent hard worker bound.

Python validation does not pin Chromium's independently resolved connection. Browser capture retains
a documented DNS rebinding boundary; see [Network security](network-security.md).

## Evidence and retention

Rendered HTML is gzip-compressed; PNG is stored without additional compression. Both use SHA-256
content addressing, atomic writes, and reference-aware deletion. Artifact paths are derived only
from hashes. Rendered DOM is served as `text/plain` and displayed as escaped React text.

Capture states are `capturing`, `completed`, `completed_with_warnings`, `failed`, `skipped`,
`cancelled`, and `interrupted`. Run counters distinguish attempted, successful, failed, and skipped
targets. Worker cancellation and expired leases leave durable Run/observation terminal state.
Historical Scan counters and observations are not rewritten. The Rendered
workspace derives its outcome summary from retained observations, so legacy renderer-v1 rows such
as `completed` plus HTTP 429 are still presented truthfully.

Rendered operational summary buckets are mutually exclusive: successful render, no-content
response, HTTP redirect, HTTP error excluding 429, rate limited (HTTP 429), skipped after host
throttling, and technical failure. Artifact count is separate evidence-retention information and is
not an operational outcome. A final non-followed 3xx retains the row label `HTTP redirect` and is
not a technical browser failure.

Renderer version 2 names the response-first classification and artifact-eligibility semantics.
Browser policy remains version 2 because request interception and browser safety policy did not
change, and capture schema remains version 2 because persisted shapes did not change. Renderer-v1
observations remain readable and are never rewritten.

## Discoverability

The Site Rendered workspace provides Run creation, history, active progress, Run detail, bounded
server-side observation filtering/pagination, and selected rerender. Persistent Page detail exposes
bounded render history. Scan detail links to its associated Run when present; the historical Scan
Rendered tab remains readable. Rendered network and DOM evidence do not feed static Resource
Inventory; see [Resource Inventory](resource-inventory.md).

Deleting a source Scan preserves Site-owned Run evidence and nulls optional Scan/snapshot
provenance. Browser evidence also has an explicit independent deletion lifecycle:

- deleting an observation removes its network, console, Page-error, and artifact relationships;
- its frozen `RenderRunTarget` remains with `evidence_deleted_at`, presented as **Evidence deleted**;
- a target with no observation and no marker is **Not attempted**;
- historical execution counters remain unchanged while retained counts are derived from current rows;
- rerendering a deleted or unattempted target creates a new Run and never restores old evidence;
- shared content-addressed `ArtifactBlob` records/files survive until their final reference is gone;
- database deletion commits before best-effort physical file removal.

Site purge removes Site-owned Runs and legacy Scan-bound browser evidence for that Site without
removing Pages, Scans, snapshots, Performance, Accessibility, notes, or categories. Scan purge
removes legacy observations and Site-less ad-hoc Runs owned by the Scan; linked Site-owned Runs
remain independent. Active affected Runs must finish or be cancelled before deletion.
