# Collection Plans

Collection Plans turn current evidence coverage into bounded native collection work. A Plan freezes
one Site, one evidence domain, one current compatibility context, the active Page universe, and a
deterministic Page selection. `missing_current` fills absent compatible evidence. `refresh_current`
deliberately acquires another compatible observation while retaining existing history.

A Plan is orchestration provenance. It is not evidence, a collector Run, a BackgroundJob type, or a
scheduler. Each batch creates the existing native Performance Run, Accessibility Run, Render Run,
or Structured Content job. Those children retain ownership of collection, retries, progress, and
immutable evidence.

## Selection Contract

New Plans use `collection-planner-v2`. Historical `collection-planner-v1` Plans and checksums remain
readable and are never reinterpreted. V1 recorded missing-and-in-flight Pages, but not V2's broader
total of all equivalent active collection. Migrated V1 Plans therefore expose total active
collection as unknown rather than inventing a value; their total missing count is reconstructed as
frozen targets plus missing Pages that were already in flight. V2 supports:

- `missing_current`: eligible Pages without compatible evidence, excluding equivalent collection
  already active.
- `refresh_current`: every eligible Page, whether covered or missing, excluding equivalent
  collection already active.

A refresh target with prior compatible evidence records reason `refresh_current`. A refresh target
without prior evidence records reason `missing_current`. Each target freezes the latest compatible
observation timestamp before Plan creation when one exists. Plan-level counts keep covered,
genuinely missing, equivalent active collection, and selected targets separate.

Compatibility is defined per domain:

- Performance: one PageSpeed mobile/desktop or CrUX PHONE/DESKTOP URL context using current provider
  adapter and normalization identities. Origin CrUX is never included.
- Accessibility: one desktop/mobile profile with current axe, detector, integration,
  normalization, and ruleset identities.
- Render: the current renderer, browser policy, capture schema, URL normalization, and meaningful
  capture configuration. Orchestration bounds such as `max_pages`, `render_max_pages`, and
  `render_mode` do not affect compatibility.
- Structured Content: the latest successfully fetched retained HTML blob for each active Page using
  the current extractor/config identity. The frozen blob IDs are passed explicitly to child jobs.

`refresh_current` applies to Performance, Accessibility, and Render. It does not apply to Structured
Content because Structured Content is a deterministic derivative of retained HTML. Collecting new
static evidence changes its source; rebuilding the same blob because time passed would not create
new website evidence.

The active Page universe is ordered by `WebResource.id`. Plans retain SHA-256 identities for both
that universe and the selected targets. Suppressed Pages are excluded. Compatible covered and
already in-flight Pages are not selected. Pages without eligible retained HTML remain explicitly
ineligible for Structured Content rather than being treated as missing.

Current terminal failure or unavailability is coverage where the native domain contract treats it
as a truthful current observation. Render host-throttling skips are not coverage. Unknown or stale
compatibility identities remain missing.

## Compatibility And Freshness

Compatibility and freshness are separate. Current-compatible evidence remains covered until its
identity changes or a future explicit freshness policy says otherwise. A Page can be covered while
equivalent refresh work is active; another Plan will not duplicate that work.

Freshness age is based on the latest compatible native observation timestamp:

- Performance: `PerformanceObservation.observed_at`.
- Accessibility: `AccessibilityObservation.observed_at`, within the exact profile and detector
  identity.
- Render: terminal `RenderedObservation.finished_at`, with `created_at` only as a defensive fallback
  for historical terminal rows without `finished_at`.

V2 introduces no stale threshold, `stale_current` public mode, recurring schedule, or due policy. A
future stale policy must freeze its maximum age, evaluation time, resulting cutoff, context,
active-Page universe, and targets in deterministic provenance.

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

Downgrading the V2 migration removes `refresh_current` Plan orchestration rows because the V1 CHECK
constraint cannot represent them. Historical `missing_current` Plans, native Runs, and collected
evidence remain. This is an explicit schema-compatibility downgrade behavior, not normal retention.
