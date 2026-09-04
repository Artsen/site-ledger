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
browser collection, or `website_property_id` for supported Site-scoped Category Rule, structured
content, and Finding evaluation operations.

`JobEvent` stores coarse lifecycle events for debugging and user-visible history. It intentionally
does not store every discovered URL or crawler detail; page snapshots, occurrences, scan seeds, and
source entries remain the durable domain records.

`WorkerInstance` stores process heartbeat and capacity so the UI can distinguish a queued job from a
queued job that has no online worker.

## Lifecycle

APIs create the domain record and enqueue the job in the same transaction where practical. Scan and
source refresh endpoints return `202 Accepted` once work is durable.

Every supported job type has one typed lifecycle contract in
`backend/app/services/job_lifecycle.py`. The static registry declares queued cancellation, running
cancellation, failure, interruption/lease-expiry, domain reconciliation, and required follow-up
behavior explicitly; unsupported capabilities are registered as `None`. Domain services continue
to own their state mutations, while lifecycle adapters only stage mutations in the caller's
Session. BackgroundJob callers retain ownership of commits, leases, and transaction fencing.

| Job type | Native/domain state | Queued cancel | Recovery/reconcile | Required follow-up |
| --- | --- | --- | --- | --- |
| Scan | Scan | native cancellation | yes | projection and active category rules |
| Source refresh | SourceRefresh | native cancellation | yes | none |
| Projection | ScanProjectionBuild | build cancellation | yes | waiting and adjacent comparisons |
| Comparison | ScanComparisonBuild | build cancellation | yes | none |
| Category rules | PageCategoryRuleRun | run cancellation | yes | requested coalesced rerun |
| Structured content | job-owned preparation | job only | job lifecycle only | none |
| Performance | PerformanceRun | native cancellation | yes | none |
| Accessibility | AccessibilityRun | native cancellation | yes | none |
| Render | RenderRun | native cancellation | yes | none |
| Finding evaluation | FindingEvaluation | evaluation cancellation | yes | none |

Workers claim queued jobs deterministically by priority, availability time, creation time, and id.
Claiming sets a lease token and lease expiry. Heartbeats and progress updates are accepted only from
the holder of the current lease.

Job lease health is independent of synchronous domain throughput. Substantial CPU, SQL, and local
filesystem work runs through a bounded `asyncio.to_thread` boundary so job and worker heartbeats
remain schedulable. Scan projection, Scan comparison, Category Rule reconciliation, and structured
content preparation create, use, and close their SQLAlchemy Sessions inside that execution thread;
live Sessions and attached ORM state are never passed across the boundary. Path-only content-store
configuration is reconstructed in the thread when required.

Authenticated job heartbeats and bounded progress updates both atomically renew `heartbeat_at` and
`lease_expires_at` under the running-status and lease-token ownership check. A transient SQLite lock
may delay one heartbeat or progress write and produces a bounded warning; it is not itself a domain
failure. Worker heartbeats also perform their synchronous database work off the event loop.

Expired-job recovery atomically claims only rows that are still running and expired when recovery
acts. A legitimate renewal that wins that compare-and-set remains authoritative even if another
worker observed an older expired value. Once recovery wins, the prior token cannot heartbeat,
report progress, complete, or fail the job. Confirmed stale ownership is surfaced to the executor
as a distinct execution-ownership loss, not user cancellation. Blocking domain work then stops at
its next progress, cancellation-check, or batch boundary without completing, cancelling, failing,
or activating stale domain state. Exception terminalization conditionally guards the active lease
and stages domain and BackgroundJob terminal state in one transaction, so recovery cannot win
between ownership validation and domain mutation. Heartbeats remain mutable operational state and
do not create permanent `JobEvent` rows.

Cancellation is cooperative. Direct cancellation stages a queued job and its applicable native
Scan, Source Refresh, Projection, Comparison, Category Rule, Performance, Accessibility, Render, or
Finding evaluation terminal state in one transaction.
A running job stores `cancellation_requested_at`; handlers check that flag between fetches or source
parsing steps, save partial results, and finish as `cancelled`.

`scan_projection_build` starts only after Scan evidence reaches a terminal state. It is
lease-guarded, cancellation-aware, batch-progress-reporting, and deduplicated per build. A failed or
interrupted projection job records build failure without changing the crawl's terminal result or
the current ready projection. See [Scan projections](scan-projections.md).

`category_rule_evaluation` is a Site-scoped durable job. Only one reconciliation executes per Site;
queued triggers coalesce and changes during an active lease request one follow-up run. Evaluation
and Scan projection jobs are independent and report progress in bounded Page batches.

Transactional ownership fencing covers Scan crawl commits and follow-up enqueue, Source Refresh
including recursive sitemap and AI Document writes, Projection and Comparison batches and
activation, Category Rule batches and reruns, Structured Content, Performance, Accessibility, and
Render collection. Finding evaluation retains its equivalent guarded single transaction. Optional
fence callbacks keep these domain services usable by non-worker rebuild and test callers; every
BackgroundJob handler supplies the fence for job-owned execution.

`structured_content_build` is a Site-scoped historical preparation job. It selects retained HTML
ContentBlobs missing the current structured identity, commits bounded per-blob results, reports
progress, cooperates with cancellation, and continues after individual blob failures. See
[Structured Page Content](structured-page-content.md).

`finding_evaluation` is a Site-scoped deterministic evaluation over one pinned terminal Scan and a
frozen active-Page universe. The handler owns its Session in the blocking thread and atomically
commits lifecycle transitions, immutable assessments, evaluation completion, and BackgroundJob
completion under the active lease. Lease-expiry recovery interrupts the job and fails an otherwise
nonterminal evaluation with explicit provenance. Failed or cancelled exact inputs can only be
requeued by an explicit Finding run request; the same evaluation and job retain attempt/event
history, and completed inputs never rerun. See [Findings](findings.md).

Administrative Finding deletion/reset independently checks both Site-scoped FindingEvaluation and
`finding_evaluation` BackgroundJob active state. Queued/running work blocks deletion; reset never
cancels or removes work under a worker. A successful full reset removes only terminal
Finding-evaluation jobs and their events, in the same transaction as the rebuildable Finding layer,
so the old dedupe keys cannot block an intentional rerun from retained evidence. Other job types
and their activity history are preserved.

Execution ownership governs authority to mutate durable domain state, not only authority to
terminalize a BackgroundJob. Work that can block outside the database follows the transactional
shape `external work -> ownership fence -> domain mutation -> commit`. The fence renews and verifies
the current running lease in the same transaction as the resulting domain write, so recovery and a
stale executor cannot both commit authority-dependent state. Checking ownership before long work is
still necessary for bounded cancellation, but is insufficient by itself because ownership can be
lost while that work is in flight.

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
When the domain record already reached a terminal state, recovery first idempotently ensures required
Scan projection/category work, ready-Projection comparison work, or a requested Category rerun, then
reconciles the job in the same transaction. This recoverable boundary covers process death after the
domain commit but before normal follow-up persistence. Otherwise the job and domain record move to
`interrupted`.

Increasing the configured lease duration is not a substitute for keeping the scheduler responsive.
The configured graceful-shutdown duration is not currently an enforced deadline: WorkerService
waits for active work during shutdown, and cancelling an await of `asyncio.to_thread` cannot stop
the underlying Python thread. A bounded graceful-shutdown contract requires a dedicated follow-up
design rather than claiming that threads can be forcibly terminated.

## Boundaries

The queue owns claiming, leasing, heartbeats, progress, cancellation requests, and worker health.
The crawler and source refresh services still own domain behavior and persistence. Renderer state,
graph state, scan results, source inventory, and HTML blobs are never mutated by the job system
except through the existing domain services.
