# Network security

Site Ledger treats every scanned URL as attacker-controlled. Public crawling accepts only HTTP and
HTTPS URLs whose complete DNS answer set is globally routable. Resolution uses asyncio's asynchronous
resolver. Loopback, private, link-local, shared/CGNAT, unspecified, reserved, multicast,
documentation, and other non-global addresses are rejected by default. A mixed public/non-public
answer is also rejected by default.

The existing `allow_private_networks` scope option is an explicit exception for controlled local
targets such as the Golden Path fixture. It permits non-public and mixed answer sets, but does not
permit URL credentials, unsupported schemes, missing hosts, invalid ports, unrestricted redirects,
cookies, credentials, or oversized responses.

## Static connection boundary

`SafeHttpFetcher` uses a dedicated HTTPX/httpcore transport. Its network backend resolves and
validates the destination immediately before opening a socket, then passes an approved numeric
address to the underlying socket backend. HTTP request URLs remain unchanged, so HTTP `Host`, TLS
SNI, and certificate hostname verification continue to use the original hostname. TLS verification
uses the platform default trust configuration and is never disabled.

Redirects are followed manually. Every new origin is independently resolved and pinned. An existing
pooled connection may be reused only under httpcore's exact scheme/host/port origin key; that
connection was itself opened to an approved address. DNS answers are never shared across origins.

Crawler, Source refresh, sitemap/robots, and AI Document network paths use this fetcher. They set
`trust_env=False`; process `HTTP_PROXY`, `HTTPS_PROXY`, and `ALL_PROXY` values are not an implicit
network route. Explicit proxy support is not currently a product feature.

Static response bodies remain streamed and bounded by observed body bytes. `Content-Length` is an
early rejection hint only. Caller `Authorization`, `Cookie`, and `Proxy-Authorization` headers are
rejected, cookie state is cleared between hops, and sensitive response headers are not retained.

## Chromium boundary

Chromium requests are intercepted before navigation. URL and complete DNS-answer policy is applied
to main navigation, redirects, and subresources. Chromium is launched with ambient proxy use
disabled. Chromium nevertheless performs its own DNS resolution after Python validation. Site
Ledger does **not** pin Chromium's actual connection to the Python-approved address, so a residual
DNS validation/connection rebinding boundary remains for browser capture. Robust closure requires a
validated outbound proxy, restricted browser process, egress firewall, or OS network sandbox.

Chromium transfer budgets use CDP `Network.dataReceived` encoded-byte deltas and reconcile with
`Network.loadingFinished.encodedDataLength`. `Content-Length` is not authoritative. Crossing either
the per-resource or aggregate budget blocks later URLs and invokes `Page.stopLoading` for active
traffic. Event/chunk granularity permits a bounded overshoot before Chromium reports the crossing.
The capture records a machine-readable policy warning while retaining whatever bounded evidence can
still be collected.

New observations use browser policy version `2` and capture schema version `2`; renderer version
remains `1`. Historical observations retain their original versions and byte semantics.

## Guarantees

| Boundary | Validation | Connection pinned? | Byte bounded? | Residual risk |
| --- | --- | --- | --- | --- |
| Static HTTP | Async complete-answer policy | Yes | Streamed body bytes | Resolver and OS routing trust |
| Sitemap/Source fetch | Same SafeHttpFetcher policy | Yes | Streamed body/decompression limits | Resolver and OS routing trust |
| AI Document fetch | Same SafeHttpFetcher policy | Yes | Per-document and aggregate limits | Resolver and OS routing trust |
| Chromium main navigation | Async route validation | No | Observed encoded bytes and duration | Chromium DNS TOCTOU; event overshoot |
| Chromium subresource | Async route validation | No | Observed encoded bytes | Chromium DNS TOCTOU; event overshoot |

For packaged or multi-tenant deployment, add defense in depth outside the application: deny private
egress by default, isolate Chromium, and mediate browser traffic through a destination-validating
proxy. These controls complement rather than replace application validation.
