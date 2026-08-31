# Collection Plans

Collection Plans turn current evidence coverage into bounded native collection work. A Plan freezes
one Site, one evidence domain, one current compatibility context, the active Page universe, and the
deterministic set of Pages that were missing compatible current evidence at creation time.

A Plan is orchestration provenance. It is not evidence, a collector Run, a BackgroundJob type, or a
scheduler. Each batch creates the existing native Performance Run, Accessibility Run, Render Run,
or Structured Content job. Those children retain ownership of collection, retries, progress, and
immutable evidence.

## Selection Contract

`collection-planner-v1` supports only `missing_current` for these domains:

- Performance: one PageSpeed mobile/desktop or CrUX PHONE/DESKTOP URL context using current provider
  adapter and normalization identities. Origin CrUX is never included.
- Accessibility: one desktop/mobile profile with current axe, detector, integration,
  normalization, and ruleset identities.
- Render: the current renderer, browser policy, capture schema, URL normalization, and meaningful
  capture configuration. Orchestration bounds such as `max_pages`, `render_max_pages`, and
  `render_mode` do not affect compatibility.
- Structured Content: the latest successfully fetched retained HTML blob for each active Page using
  the current extractor/config identity. The frozen blob IDs are passed explicitly to child jobs.

The active Page universe is ordered by `WebResource.id`. Plans retain SHA-256 identities for both
that universe and the selected targets. Suppressed Pages are excluded. Compatible covered and
already in-flight Pages are not selected. Pages without eligible retained HTML remain explicitly
ineligible for Structured Content rather than being treated as missing.

Current terminal failure or unavailability is coverage where the native domain contract treats it
as a truthful current observation. Render host-throttling skips are not coverage. Unknown or stale
compatibility identities remain missing.

## Lifecycle

Creation persists the Plan, frozen targets, native Runs, batches, and queued jobs in one transaction.
An equivalent active Plan is rejected. Status and progress are derived from child jobs and Runs, so
there is no second mutable execution state to reconcile.

Cancellation requests cancellation for remaining child jobs. For a queued native child, the
BackgroundJob and its Performance, Accessibility, or Render Run are terminalized as cancelled in
one transaction. Running children retain their cooperative, ownership-fenced cancellation path.
Evidence already produced by completed or running children remains valid; cancellation means that
remaining work was cancelled, not that completed evidence was rolled back.
Child Run/job foreign keys use `SET NULL` so Plan provenance remains truthful if separate evidence
lifecycle actions later remove native history.

Plan progress represents terminal persisted work. In particular, Render progress is the bounded
sum of completed, failed, and skipped outcomes; an attempted capture still in Chromium is not yet
reported as processed.

Site Intelligence uses the same selectors as preview and creation and always exposes the fixed
current contexts, including contexts with zero evidence or an unconfigured provider. Frontend
evidence mutations invalidate this read model immediately. While mounted, it refreshes quickly
during active work and at a bounded idle cadence so work initiated in another tab or through the
API cannot leave coverage stale indefinitely.
