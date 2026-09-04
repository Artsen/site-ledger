# Development Frontier

This file records non-canonical direction that may matter when planning a change. Canonical graph
truth is reviewed against post-PR #54 `main`:

`234d9d1945f2fc48518ea76e5adcd750308ea223`

PR #55 completes BackgroundJob lifecycle contract consolidation. Unimplemented work below remains
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

## Next architectural work

Broader non-binding direction remains:

- decompose `backend/app/api/routes.py`;
- decompose large frontend workspace modules;
- establish Web Estate identity foundations;
- add host/domain evidence and discovery;
- infer technology/platform evidence;
- later define explicit freshness policy and recurring collection semantics.

These are planning signals, not a binding numbered constitution. PR boundaries may move as
implementation reveals better ownership boundaries.
