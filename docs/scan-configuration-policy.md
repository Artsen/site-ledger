# Scan Configuration Policy

`backend/app/crawler/config.py` owns `crawl-policy-v1`, the authoritative static/general Scan
configuration bounds. `ScopeConfigPayload` applies that policy to API input and
`ScopeConfig.from_dict()` applies the same policy when persisted JSON or an internal caller enters
runtime. Browser-specific limits remain separately owned by `backend/app/browser/config.py`.

Bounds violations are rejected, never clamped. For accepted values, requested configuration equals
persisted configuration and executed configuration, apart from existing default population and
scope normalization. The static crawler uses the validated per-host connection value directly; the
current request loop remains sequential.

Execution validates the crawl policy, starting URL length, and browser policy before the static
crawler or browser renderer starts. Unsafe persisted configuration terminates the Scan as `failed`
with `stop_reason = invalid_scope_config` and does not create network or browser evidence.

Historical evidence is not revalidated on read. Completed Scans remain readable with their exact
stored configuration, and an unrelated Site update does not rewrite or revalidate omitted saved
scope configuration. Starting new work from explicitly submitted or persisted unsafe configuration
fails closed.

Future schedulers, agents, CLI commands, and internal Python callers must use the typed API schemas
or runtime `ScopeConfig` validation. They must not create an execution path that bypasses these
policies.
