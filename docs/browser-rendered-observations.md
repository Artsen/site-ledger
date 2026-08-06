# Browser-rendered observations

Browser rendering is optional and defaults to `none`. A Scan may render only its starting Page or
up to `render_max_pages` eligible static observations. Eligibility requires usable static HTML and
an in-scope HTTP(S) main-navigation URL. `all_eligible` ordering is deterministic: starting Page,
lowest crawl depth, earliest static observation time, then snapshot ID.

Static HTTP evidence remains authoritative. Each selected ResourceSnapshot receives at most one
RenderedObservation attempt. Rendered DOM is not parsed into static metadata or links and does not
enter the graph. HTTP 404 and 500 documents can be successful browser observations when usable
HTML was captured.

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
duration, declared network bytes, bounded event counts, and artifact bytes without contacting an
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

The request and total network byte budgets use declared response lengths as early warnings and
evidence limits. Browser engines do not provide a portable pre-body byte cutoff for every encoded
response; the wall-clock limit and bounded event/artifact persistence remain the hard worker and
storage controls.

## Evidence and retention

Rendered HTML is gzip-compressed; PNG is stored without additional compression. Both use SHA-256
content addressing, atomic writes, and reference-aware deletion. Artifact paths are derived only
from hashes. Rendered DOM is served as `text/plain` and displayed as escaped React text.

Capture states are `capturing`, `completed`, `completed_with_warnings`, `failed`, `skipped`,
`cancelled`, and `interrupted`. Page-level browser failures make the Scan
`completed_with_errors`; browser preflight failure before useful execution makes it `failed`.
