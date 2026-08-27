# Site Ledger Background Jobs

Site Ledger executes scans, source refreshes, terminal Scan projection and comparison builds, and
supported Site-scoped preparation through a database-backed job queue. API requests
persist work and return without holding an HTTP connection open for the collection run.

## Local Commands

Run the API and frontend as usual, then start a worker in a third terminal:

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
python -m app.worker
```

For test-style processing, run one polling cycle and exit:

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
python -m app.worker --once
```

To reconcile expired leases without processing new jobs:

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
python -m app.worker --recover-only
```

## Model

`BackgroundJob` stores the durable unit of work. A job has one constrained subject: `scan_id` for
crawl/projection jobs, `source_refresh_id` for source refresh jobs, `scan_comparison_id` for
comparison builds, `performance_run_id` for external Performance collection, `render_run_id` for
browser collection, or `website_property_id` for supported Site-scoped Category Rule and structured
content operations.

`JobEvent` stores coarse lifecycle events for debugging and user-visible history. It intentionally
does not store every discovered URL or crawler detail; page snapshots, occurrences, scan seeds, and
source entries remain the durable domain records.

`WorkerInstance` stores process heartbeat and capacity so the UI can distinguish a queued job from a
queued job that has no online worker.

## Lifecycle

APIs create the domain record and enqueue the job in the same transaction where practical. Scan and
source refresh endpoints return `202 Accepted` once work is durable.

Workers claim queued jobs deterministically by priority, availability time, creation time, and id.
Claiming sets a lease token and lease expiry. Heartbeats and progress updates are accepted only from
the holder of the current lease.

Cancellation is cooperative. A queued job can move directly to `cancelled`. A running job stores
`cancellation_requested_at`; handlers check that flag between fetches or source parsing steps, save
partial results, and finish as `cancelled`.

`scan_projection_build` starts only after Scan evidence reaches a terminal state. It is
lease-guarded, cancellation-aware, batch-progress-reporting, and deduplicated per build. A failed or
interrupted projection job records build failure without changing the crawl's terminal result or
the current ready projection. See [Scan projections](scan-projections.md).

`category_rule_evaluation` is a Site-scoped durable job. Only one reconciliation executes per Site;
queued triggers coalesce and changes during an active lease request one follow-up run. Evaluation
and Scan projection jobs are independent and report progress in bounded Page batches.

`structured_content_build` is a Site-scoped historical preparation job. It selects retained HTML
ContentBlobs missing the current structured identity, commits bounded per-blob results, reports
progress, cooperates with cancellation, and continues after individual blob failures. See
[Structured Page Content](structured-page-content.md).

`performance_run` executes a bounded canonical request set serially through fixed PageSpeed and CrUX
adapters. It commits each immutable observation independently, reports ready/unavailable/failed
counters, cooperates between provider requests, and skips already-retained logical requests after a
reclaim. Page count and provider-request budgets are independently enforced. CrUX URL and origin
attempts use one local cancellation-aware quota limiter; PageSpeed remains serial without that
delay. See [Performance observations](performance-observations.md).

`accessibility_run` enforces both a bounded Page count and an exact Page/profile audit budget. It
reuses one Chromium session, commits each immutable observation independently, and checks
cancellation between audits. See [Automated Accessibility observations](accessibility-observations.md).

`render_run` executes one frozen target set in one Chromium session. It persists one immutable
observation per target, owns a Run-local host throttling circuit, reports Page counters, and checks
cancellation between and during bounded captures. A Scan may enqueue this job, but the job and its
evidence remain independently owned by the Render Run.

An active `render_run` job blocks observation, bulk, Run, and owner-scope rendered evidence
deletion for that Run. Terminal Run deletion removes its terminal job/event history; partial
observation deletion preserves both the Run and historical execution counters.

The scan comparison build job waits for compatible prepared results, stages materialized
differences, validates and checksums them, and atomically activates a ready build. Failed,
cancelled, or interrupted rebuilds preserve the prior current result. See
[Deterministic Scan comparisons](scan-comparisons.md).

If a worker exits or the process is killed, expired running jobs are reconciled on worker startup.
When the domain record already reached a terminal state, the job follows that terminal state.
Otherwise the job and domain record move to `interrupted`.

## Boundaries

The queue owns claiming, leasing, heartbeats, progress, cancellation requests, and worker health.
The crawler and source refresh services still own domain behavior and persistence. Renderer state,
graph state, scan results, source inventory, and HTML blobs are never mutated by the job system
except through the existing domain services.
