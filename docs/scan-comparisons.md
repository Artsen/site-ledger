# Deterministic Scan Comparisons

Scan comparison is a versioned deterministic layer between prepared Scan results and future
interpretation. It describes differences in recorded observations. It does not create Findings,
score health, infer URL moves, or claim that an unobserved URL was removed from a website.

~~~mermaid
flowchart LR
  E[Immutable raw evidence] --> P[scan-projection-v1]
  P --> C[scan-comparison-v1]
  C -. future .-> F[Finding or interpretation]
~~~

## Direction And Eligibility

Every comparison is directional: **Baseline Scan -> Target Scan**. The UI defaults to the previous
and latest successful Scans, but never silently reverses a selected pair. Both Scans must be
different, terminal, saved-Site Scans belonging to the same WebsiteProperty. Failed, cancelled,
and interrupted Scans may be selected manually and receive strong coverage warnings. Cross-Site,
ad-hoc, and environment comparison are not supported.

Both sides require a ready compatible scan-projection-v1 build with the expected algorithm
identity. Missing projections are queued through the existing durable preparation mechanism. The
comparison waits without synchronously aggregating raw evidence.

~~~mermaid
flowchart LR
  B[Baseline terminal Scan] --> BP{Compatible ready projection?}
  T[Target terminal Scan] --> TP{Compatible ready projection?}
  BP -- no --> BQ[Queue Baseline preparation]
  TP -- no --> TQ[Queue Target preparation]
  BP -- yes --> C[Comparison build]
  TP -- yes --> C
  BQ --> C
  TQ --> C
~~~

## Persistence And Versioning

ScanComparison is the Site-scoped logical identity for one directional Scan pair. Its unique key is
Site, Baseline Scan, and Target Scan. Its current-build pointer identifies the active ready result.

ScanComparisonBuild is an immutable attempt. It stores scan-comparison-v1, algorithm identity
scan-comparison-v1|page-v1|resource-v1|link-v1|scan-projection-v1, lifecycle and timing, coverage
fingerprints, warnings, validation, counts, and a deterministic checksum. It pins both projection
build IDs and copies each projection version, algorithm identity, checksum, and build timestamp.
Projection FKs use SET NULL, so future projection garbage collection does not erase provenance.

Page, Resource, Link, and summary rows are materialized by build. Their IDs can later be referenced
by deterministic Findings, but this release creates no Finding records.

~~~mermaid
stateDiagram-v2
  [*] --> Queued
  Queued --> WaitingForProjections
  Queued --> Building
  WaitingForProjections --> Building
  Building --> Ready: validate, checksum, activate
  Building --> Failed
  Building --> Cancelled
  Ready --> Superseded: replacement activates
  Failed --> PreviousReadyRemainsCurrent
  Cancelled --> PreviousReadyRemainsCurrent
~~~

A rebuild stages separately. Only a validated build atomically becomes current; failure,
cancellation, or interruption leaves the prior ready build readable. Checksums exclude database
row IDs, projection IDs, timestamps, and other nondeterministic storage details.

## Coverage And Neutral Absence

Coverage fingerprints compare canonicalized scope configuration and persisted Scan seed/input
provenance. Deterministic warnings cover changed scope, starting URL, seeds, error-terminal states,
limit stop reasons, and fetch failures. Coverage is comparable, comparable with warnings, or
limited; there is no invented confidence percentage.

~~~mermaid
flowchart TD
  A[Baseline Page identity] --> O{Target Page projection?}
  O -- yes --> Both[Observed in both]
  O -- no --> R{Target raw observation?}
  R -- failed --> Fail[Not observed as Page in Target: fetch failed]
  R -- non-HTML --> Non[Not observed as Page in Target: observed as non-HTML]
  R -- absent --> Missing[Not observed in Target]
  N[Target-only identity] --> New[Newly observed]
~~~

Canonical states are newly observed, observed in both, and not observed in Target. None proves or
means that a URL was removed from the website.

## Page Comparison

Pages match only through stable WebResource identity, never through titles, path similarity,
content similarity, redirects, fuzzy logic, or AI.

~~~mermaid
flowchart LR
  BR[Baseline WebResource] --> I[Same resource ID]
  TR[Target WebResource] --> I
  I --> PR[One Page comparison result]
  PR --> BS[Baseline snapshot]
  PR --> TS[Target snapshot]
~~~

For Pages observed on both sides, comparison records requested/final URL, redirect state, HTTP and
fetch state, type, content/head hashes, title, canonical, robots, language, depth, static link and
embedded-Resource aggregates, and rendered availability/count summaries. Content and head states
are same, changed, unavailable, or not applicable. Timing and transfer-byte deltas remain
operational measurements and do not alone mark a structural change. Conditional 304 and parse
reuse compare the effective reused hashes.

Page detail links to exact Baseline and Target observations. Raw source diff reads stored HTML only
on demand, decodes using stored encoding, and emits escaped unified text. Each input is limited to
1 MiB; output is limited to 5,000 lines and 1 MiB. Missing, identical, too-large, decoding-failed,
available, and truncated states are explicit. No source is executed.

## Resource Comparison

Resources match by stable WebResource identity. Results compare presence, inferred kind, MIME
type, HTTP/observed state, declared size, occurrence count, and source-Page count. Site Ledger does
not store general Resource bodies, so it makes no Resource-body equality or change claim.

## Link Comparison

Cross-Scan edge identity is source WebResource plus target WebResource, not source snapshot ID.
Aggregates compare occurrence count, role counts, scope counts, and follow/nofollow evidence.

~~~mermaid
flowchart LR
  BS[Baseline source snapshot] --> E[Source WebResource + Target WebResource]
  TS[Target source snapshot] --> E
  E --> L[Stable Link comparison row]
  L --> A[Aggregate differences]
  L --> X[Exact occurrence diff]
~~~

Duplicate occurrences remain raw evidence. Exact drill-down fingerprints occurrence fields and
performs a multiset comparison, retaining multiplicity. It compares at most 20,000 occurrences per
side and reports truncation rather than pretending the result is complete.

## Summary And Page Change History

The overview stores deterministic Page, Resource, Link, and grouped Scan-summary counts and deltas.
These are facts, not severity or recommendations.

Persistent Page Change History compares each observed Page snapshot with the previous observed
snapshot for the same Site and WebResource. Missing or unsuccessful intervening Scans remain visible
as gap counts; unchanged content after a gap remains No tracked change.

~~~mermaid
flowchart LR
  O1[Observed Scan 1] --> G1[Scan 2 gap]
  G1 --> G2[Scan 3 fetch failure]
  G2 --> O2[Observed Scan 4]
  O1 -->|previous observed snapshot| O2
  G1 -. counted gap .-> O2
  G2 -. counted gap .-> O2
~~~

## Exact Evidence Drill-Down

~~~mermaid
flowchart TD
  C[Comparison overview] --> P[Page result]
  C --> R[Resource result]
  C --> L[Link result]
  P --> PS[Exact snapshots]
  P --> D[Bounded source diff]
  R --> RS[Exact snapshot metadata]
  L --> O[Bounded occurrence multiset]
  PS --> H[Raw immutable evidence]
  RS --> H
  O --> H
~~~

## Jobs, Automation, And CLI

The scan comparison build job uses the durable queue, lease, cancellation, progress, deduplication,
and startup recovery infrastructure. Projection completion queues comparisons waiting on that Scan.
Completion of an eligible saved-Site Scan also creates the adjacent successful comparison when a
prior successful Scan exists. Comparison failure never changes Scan or projection status.

~~~text
python -m app.scan_comparisons build BASELINE_SCAN_ID TARGET_SCAN_ID
python -m app.scan_comparisons rebuild COMPARISON_ID
python -m app.scan_comparisons verify COMPARISON_ID
python -m app.scan_comparisons build-adjacent --site-id SITE_ID
python -m app.scan_comparisons build-adjacent --all-sites --limit 100 --stop-on-error
~~~

## API, Caching, And Performance

Ready tables are server-paginated, filtered, and sorted over materialized result rows. They do not
rerun projection aggregation. Ready build responses use deterministic build/query-specific ETags,
private no-cache semantics, and 304 Not Modified. TanStack Query treats ready comparison data as
immutable and polls only active build status. A newer active rebuild is merged with the retained
current result until activation.

The deterministic benchmark uses two 2,000-Page, 2,000-link Scans. Ready overview and Page,
Resource, and Link lists execute three SQL statements each.

~~~text
python -m app.scan_comparison_benchmark
~~~

## Timezone, Deletion, And Limits

Comparison evidence and checksums use stored absolute values. Site display timezone affects only
timestamp presentation. Categories, rules, notes, owner, workflow, and other mutable Site metadata
are outside comparison inputs.

Deleting a comparison removes only derived builds/results. It does not delete Scans, projections,
snapshots, occurrences, blobs, or persistent Site Pages. Scan deletion removes dependent
comparisons first and blocks while comparison work is active. Site deletion cascades Site-owned
comparisons.

Current limits include same-Site saved Scans only, exact URL identity, static-source diff only, and
metadata-only Resource comparison. This release does not implement Findings, severity, AI,
semantic/fuzzy matching, environment comparison, screenshot/DOM diff, accessibility, PageSpeed,
analytics, scheduling, or notifications.
