# Development Frontier

This file records non-canonical direction that may matter when planning a change. Canonical graph
truth is reviewed against post-PR #53 `main`:

`7154d9ccbe421e088c23de1de3592f3e625b628d`

PR #54 completes Collection Plans V2. Unimplemented work below remains non-canonical direction.

## Completed Collection Plans V2 work

Collection Plans now preserve historical `missing_current` semantics and add explicit
`refresh_current` collection for Performance, Accessibility, and Render. V2 freezes target reasons
and latest-compatible observation timestamps while keeping compatible coverage and equivalent
active collection independent. Structured Content remains missing-current only. No stale policy,
default age threshold, recurring scheduling, or new collector abstraction was introduced.

## Next architectural work

BackgroundJob lifecycle consolidation is the next intended architecture area. The goal is to reduce
repeated native lifecycle wiring while preserving transaction boundaries, ownership fencing,
collector-specific semantics, and current job compatibility. Do not combine that work with
scheduling.

Broader non-binding direction remains:

- decompose large API/frontend workspace modules;
- establish Web Estate identity foundations;
- add host/domain evidence and discovery;
- infer technology/platform evidence;
- later define explicit freshness policy and recurring collection semantics.

These are planning signals, not a binding numbered constitution. PR boundaries may move as
implementation reveals better ownership boundaries.
