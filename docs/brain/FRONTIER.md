# Development Frontier

This file records non-canonical direction that may matter when planning a change. Canonical graph
truth is reviewed against post-PR #56 `main`:

`3dcdcfa410f7ed5b956b2f779178083a0927c7a6`

PR #57 decomposes the core backend API router into focused HTTP adapter modules while preserving
the stable composition import and complete OpenAPI contract. Unimplemented work below remains
non-canonical direction.

## Completed Collection Plans V2 work

Collection Plans now preserve historical `missing_current` semantics and add explicit
`refresh_current` collection for Performance, Accessibility, and Render. V2 freezes target reasons
and latest-compatible observation timestamps while keeping compatible coverage and equivalent
active collection independent. Structured Content remains missing-current only. No stale policy,
default age threshold, recurring scheduling, or new collector abstraction was introduced.

## Completed BackgroundJob lifecycle work

Every supported JobType now has one explicit typed lifecycle contract covering applicable queued and
running cancellation, failure, interruption, domain reconciliation, and required follow-ups.
Operational callers still own leases, fencing, and commits; domain-specific status semantics remain
authoritative. No scheduler, retry framework, or dynamic job discovery was introduced.

## Completed Render outcome authority cleanup

Modern Scan reads resolve the original scan-triggered RenderRun as the sole authority for browser
execution lifecycle and counters. Legacy Scan counters and NULL-run observations remain readable as
historical truth, while exact Run filtering prevents later rerenders from entering original Scan
results. No migration, backfill, or counter synchronization was introduced.

## Completed backend API route decomposition

The stable `app.api.routes.router` now composes focused core domain routers. Shared typed HTTP
dependencies have one neutral home, and the Projection HTTP helper remains compatibility-exported.
Domain services, transactions, paths, methods, schemas, errors, and the complete OpenAPI contract
remain unchanged.

## Next architectural work

Broader non-binding direction remains:

- decompose frontend API contracts and client modules;
- establish Web Estate identity foundations;
- add host/domain evidence and discovery;
- infer technology/platform evidence;
- later define explicit freshness policy and recurring collection semantics.

These are planning signals, not a binding numbered constitution. PR boundaries may move as
implementation reveals better ownership boundaries.
