# Scan Configuration Policy

`backend/app/crawler/config.py` owns
`crawl-policy-v2-total-request-deadline`, the authoritative static/general Scan configuration
bounds. `ScopeConfigPayload` applies that policy to API input and `ScopeConfig.from_dict()` applies
the same policy when persisted JSON or an internal caller enters runtime. Browser-specific limits
remain separately owned by `backend/app/browser/config.py`.

Bounds violations are rejected, never clamped. For accepted values, requested configuration equals
persisted configuration and executed configuration, apart from existing default population and
scope normalization. `request_timeout_seconds` is one aggregate wall-clock budget for a
`SafeHttpFetcher.get()` call, including redirect validation and response streaming. Its explicit
crawler failure classification is `request_timeout` and it remains eligible for bounded static
retry.

Execution validates the crawl policy, starting URL length, and browser policy before the static
crawler or browser renderer starts. Unsafe persisted configuration terminates the Scan as `failed`
with `stop_reason = invalid_scope_config` and does not create network or browser evidence.

Historical evidence is not revalidated on read. Completed Scans remain readable with their exact
stored configuration, and an unrelated Site update does not rewrite or revalidate omitted saved
scope configuration. Starting new work from explicitly submitted or persisted unsafe configuration
fails closed.

## Control Status

| Control | Status | Runtime contract |
| --- | --- | --- |
| `respect_robots_txt` | Rejected when `true` | Enforcement is not implemented. New and edited configurations cannot claim it; historical JSON remains readable. |
| `concurrent_requests_per_host` | Compatibility-only | It sizes the HTTPX connection pool, but the current breadth-first crawl loop is serial and does not provide within-crawl concurrency. |
| `user_agent` | Enforced per Scan | The copied scope value is sent by static crawler requests. |
| `SCANNER_CRAWLER_USER_AGENT` | Inactive compatibility setting | The setting remains readable but is not the source of the per-Scan crawler user agent. |
| `SCANNER_JOB_GRACEFUL_SHUTDOWN_SECONDS` | Inactive | Validated by Settings but not consumed by the current worker shutdown path. |
| `SCANNER_JOB_PROGRESS_MIN_INTERVAL_SECONDS` | Inactive | Validated by Settings but not consumed by progress reporting. |
| `SCANNER_JOB_EVENT_LIMIT_PER_JOB` | Inactive | Validated by Settings but does not currently prune or cap persisted events. |

The API and Site settings UI do not expose a robots-compliance toggle. `respect_robots_txt` remains
in the serialized compatibility shape so historical records can be represented truthfully.

Future schedulers, agents, CLI commands, and internal Python callers must use the typed API schemas
or runtime `ScopeConfig` validation. They must not create an execution path that bypasses these
policies or present inactive compatibility fields as enforced controls.
