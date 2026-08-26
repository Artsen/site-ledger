# Browser-rendered observations

Browser rendering is optional and defaults to `none`. A Scan may render only its starting Page or
up to `render_max_pages` eligible static observations. Eligibility requires usable static HTML and
an in-scope HTTP(S) main-navigation URL. `all_eligible` ordering is deterministic: starting Page,
lowest crawl depth, earliest static observation time, then snapshot ID.

Static HTTP evidence remains authoritative. Each selected ResourceSnapshot receives at most one
RenderedObservation attempt. Rendered DOM is not parsed into static metadata or links and does not
enter the graph. Browser technical success is distinct from requested-Page success: normal Page
screenshots and rendered DOM require a final artifact-eligible main-document HTTP 2xx response.
HTTP 204 and 205 responses retain their exact status but are no-content outcomes, not successful
rendered Pages, and receive no viewport screenshot, full-page screenshot, or rendered DOM. Final
non-followed 3xx responses and explicit HTTP 4xx/5xx responses likewise retain exact status and
bounded diagnostic, network, console, and Page-error evidence, but receive no normal Page
artifacts. HTTP 200 soft challenge or block documents are not heuristically classified yet.

Browser-rendered Pages are never retried. Bounded retry behavior applies only to eligible static
requests while their Scan is still active; it never causes a second browser capture.

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
jobs never download a browser automatically. Rendering uses one Chromium process per rendered Scan
and a fresh non-persistent context for every Page.

## Security policy

- Request interception is installed before a Page exists and therefore before navigation.
- Only GET, HEAD, and OPTIONS are allowed.
- Every HTTP(S) request, including redirect hops and subresources, passes destination validation.
- Main-frame navigations must remain within Scan scope.
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
`cancelled`, and `interrupted`. Page-level browser failures make the Scan
`completed_with_errors`; browser preflight failure before useful execution makes it `failed`.
For new Scans, only `completed` or `completed_with_warnings` observations with artifact-eligible
HTTP 2xx statuses increment `rendered_completed_count`; no-content responses and HTTP errors
increment `rendered_failed_count`, while circuit-open targets increment `rendered_skipped_count`.
Historical counters are not rewritten. The Rendered
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

## Scan Discoverability

The Scan Rendered tab indexes retained observations with server-side filtering and pagination.
Overview and Pages links open the exact snapshot's Rendered workspace. This index does not alter
capture selection, browser policy, or the no-retry rule. Rendered network and DOM evidence do not
feed static Resource Inventory; see [Resource Inventory](resource-inventory.md).
