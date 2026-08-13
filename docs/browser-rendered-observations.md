# Browser-rendered observations

Browser rendering is optional and defaults to `none`. A Scan may render only its starting Page or
up to `render_max_pages` eligible static observations. Eligibility requires usable static HTML and
an in-scope HTTP(S) main-navigation URL. `all_eligible` ordering is deterministic: starting Page,
lowest crawl depth, earliest static observation time, then snapshot ID.

Static HTTP evidence remains authoritative. Each selected ResourceSnapshot receives at most one
RenderedObservation attempt. Rendered DOM is not parsed into static metadata or links and does not
enter the graph. HTTP 404 and 500 documents can be successful browser observations when usable
HTML was captured.

Browser-rendered Pages are never retried. Bounded retry behavior applies only to eligible static
requests while their Scan is still active; it never causes a second browser capture.

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

## Scan Discoverability

The Scan Rendered tab indexes retained observations with server-side filtering and pagination.
Overview and Pages links open the exact snapshot's Rendered workspace. This index does not alter
capture selection, browser policy, or the no-retry rule. Rendered network and DOM evidence do not
feed static Resource Inventory; see [Resource Inventory](resource-inventory.md).
