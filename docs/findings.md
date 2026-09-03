# Findings

Findings are deterministic, persistent logical conditions inferred from retained evidence. A
Finding is not evidence, a Comparison result, or AI interpretation.

```text
Evidence -> deterministic derivatives -> deterministic Finding evaluation
         -> persistent Findings -> Site Intelligence and workflow -> future AI interpretation
```

## V4 Detector Bundle Contract

`finding-evaluator-v2` runs the fixed `finding-detectors-v4` bundle over one frozen ordered
universe of active Site Page resource IDs and one server-selected terminal static Scan. It contains
exactly these production detectors:

- `page-http-error-v1` (`page_http_error`, `page-http-error-key-v1`): a usable fetched
  ResourceSnapshot with HTTP 400-499 is detected at medium severity and HTTP 500-599 is detected at
  high severity. Other usable statuses are clear. Missing, failed, or incomplete evidence is
  unknown. This detector and its logical fingerprint are unchanged from V1.
- `page-static-fetch-failure-v1` (`page_static_fetch_failure`,
  `page-static-fetch-failure-key-v1`): a failed static retrieval with one of the crawler's retained
  operational error types is detected at high severity. A usable fetch is clear; missing or
  unclassified failure evidence is unknown. This remains distinct from HTTP response errors.
- `page-noindex-v1` (`page_noindex`, `page-noindex-key-v1`): an exact applicable `noindex` token in
  retained meta robots or generic `X-Robots-Tag` evidence is detected at medium severity. Supported
  evidence without noindex is clear. Ambiguous agent-scoped syntax and unusable evidence are
  unknown. Raw directive values remain in assessment details.
- `page-indexability-conflict-v1` (`page_indexability_conflict`,
  `page-indexability-conflict-key-v1`): applicable explicit `index` and `noindex` directives in the
  retained supported sources are detected at medium severity. Absence is not an implicit `index`.
  Interpretable non-conflicting evidence is clear; ambiguous or unusable evidence is unknown.
- `page-missing-title-v1` (`page_missing_title`, `page-missing-title-key-v1`): a usable HTML
  representation with a null, empty, or whitespace-only title is detected at medium severity.
  Non-HTML and unusable evidence is unknown. No title-length preference is inferred.
- `page-invalid-canonical-v1` (`page_invalid_canonical`, `page-invalid-canonical-key-v1`): a
  declared canonical that cannot be resolved under the source Scan's exact URL-normalization
  contract is detected at medium severity. No canonical or a normalizable canonical is clear.
- `page-multiple-canonicals-v1` (`page_multiple_canonicals`,
  `page-multiple-canonicals-key-v1`): more than one retained head `link` declaration whose exact
  `rel` token set contains `canonical` is detected at medium severity. Missing parsed-head evidence
  is unknown.
- `page-canonical-target-http-error-v1` (`page_canonical_target_http_error`,
  `page-canonical-target-http-error-key-v1`): a subject canonical is resolved with the source Scan's
  recorded URL normalization version and configuration. A usable same-Scan target with HTTP
  400-599 is detected at high severity. A usable non-error target, self-canonical, or absent
  canonical is clear. An unresolved, missing, failed, or unusable same-Scan target is unknown. The
  evaluator never performs a new fetch.
- `page-non-html-representation-v1` (`page_non_html_representation`,
  `page-non-html-representation-key-v1`): an active Page whose current same-Scan usable snapshot is
  classified as a non-HTML representation is detected at medium severity. Failed or unclassified
  representation evidence is unknown.
- `page-broken-internal-links-v1` (`page_broken_internal_links`,
  `page-broken-internal-links-key-v1`): a source Page with an eligible internal anchor occurrence
  whose same-Scan target has usable HTTP 4xx/5xx evidence is detected. Any 5xx target makes severity
  high; an exclusively 4xx set is medium. Duplicate occurrences are counted while target counts are
  distinct.
- `page-internal-links-to-redirects-v1` (`page_internal_links_to_redirects`,
  `page-internal-links-to-redirects-key-v1`): a source Page with an eligible internal anchor whose
  same-Scan target has an actual retained redirect chain ending at a different normalized URL is
  detected at medium severity. Normalization-equivalent spelling changes alone are clear.

All detectors use only retained `ResourceSnapshot`, `ResourceOccurrence`, and `Scan` evidence.
Render, Performance, Accessibility, Structured Content, Sources, analytics, and Comparison are not
first-class Finding evidence in this contract. That boundary is deliberate and requires a later
typed evidence-contract evolution rather than hidden provenance in assessment JSON.

## Identity And Evaluation

A logical fingerprint contains Site ID, Finding type, logical key version, subject kind, and
WebResource ID. Scan, snapshot, status, severity, timestamps, and database Finding ID are excluded.
The V1 HTTP payload is preserved byte-for-byte, so V2 continues an existing HTTP Finding rather
than duplicating it.

The current evaluation input fingerprint includes `finding-evaluator-v2`, `finding-detectors-v4`,
the deterministic detector-manifest checksum, Site, source Scan, and the frozen
active-Page-universe checksum. A V4 bundle evaluation can therefore evaluate a Scan that previously
received a V1, V2, or V3 bundle evaluation. Historical terminal evaluations remain readable;
nonterminal historical evaluations do not execute through newer detector code. Within one bundle,
an older evidence horizon fails closed after a newer completed evaluation.

The manifest is derived in registry order from each production detector's `finding_type`,
`detector_identity`, `logical_key_version`, and `subject_kind`, then hashed as canonical JSON with
SHA-256. The explicit bundle identity remains the primary compatibility contract; the manifest is a
second deterministic safety boundary, not a replacement for semantic versioning or a hash of source
code.

Detector semantic changes require a new `detector_identity`. Logical Finding identity changes
require a new `logical_key_version`. Production detector membership or ordering changes require a
new `detector_bundle_identity`. Evaluator execution-contract changes require a new
`evaluator_version`. Reusing any of these semantic identities after changing its contract is a
compatibility bug, even when implementation code alone changed.

Counts cover detector-subject outcomes. Eleven detectors over 100 active Pages produce 1,100 outcomes,
while `active_page_count` remains 100. The evaluation checksum hashes the complete deterministic
outcome set, including clean and unknown outcomes, plus the persisted per-detector summary.

`detector_summary_json` records each detector identity and its detected, clear, unknown, and stable
machine-reason counts. It is computed from the complete in-memory outcome set rather than sparse
Finding rows. Historical evaluations remain readable with an empty summary and are not rewritten.

Persistence remains sparse. A newly detected condition creates a Finding and assessment. An
existing Finding receives detected, clear, or unknown assessments. Clean or unknown outcomes with
no logical Finding create no Finding or assessment rows.

## Internal-Link Topology

Topology detectors consume immutable duplicate-preserving `ResourceOccurrence` evidence from the
evaluation's source Scan. An eligible edge has `relation_type=page_link`, a retained
`target_resource_id`, an internal scope decision of `crawlable` or `already_seen`, and is not an
email, telephone, or download role. External, unsupported, targetless, and embedded-resource
references are excluded. The evaluator batch-loads occurrences for source snapshots and target
snapshots once; detectors perform no HTTP requests and never substitute evidence from another Scan.

A usable source Page with no eligible internal occurrences is clear. Existing eligible links whose
same-Scan target is absent or unusable are unknown, not broken. Unknown evidence never resolves an
existing Finding.

Each topology assessment always references its primary source snapshot and evaluation-horizon Scan.
Detected assessments additionally retain at most 20 deterministically ordered occurrence/target
snapshot pairs. `evidence_sample_count`, total occurrence counts, and `evidence_truncated` make the
fixed bound explicit. Deleting the owning Scan may remove snapshots and occurrences; Finding and
assessment history survives with those typed references reported as no longer retained.

## Lifecycle And Time

The current states are detected, unknown, and resolved. Reopen is the transition from a previously
resolved condition back to detected. Only trustworthy clear evidence resolves a Finding. Missing,
failed, deleted, insufficient, ambiguous, or unresolvable evidence is unknown and never proves
resolution.

Finding lifecycle timestamps use evidence observation time. Evaluation execution timestamps and
mutable acknowledgement timestamps remain separate clocks. Acknowledgement never changes condition
state. Resolution retains acknowledgement; reopening clears it and records the prior acknowledgement
timestamp in the assessment.

Each evaluation stages every detector's Findings, assessments, typed evidence references, and
lifecycle transitions in the guarded BackgroundJob transaction. Ownership loss or terminal job
persistence failure rolls the whole evaluation back. There are no per-detector commits.

## Evidence And Reads

Evidence references are ordered durable typed pointers. A normal Page detector records the primary
ResourceSnapshot followed by the evaluation-horizon Scan. A canonical-target assessment records:

```text
0 primary: subject ResourceSnapshot
1 canonical_target: target ResourceSnapshot
2 evaluation_horizon: Scan
```

Evidence deletion preserves Finding and assessment history while reads report that the referenced
source is no longer retained. Raw evidence is never copied into Finding tables. Detail reads batch
assessment, evaluation, job, Scan, ResourceSnapshot, and ResourceOccurrence resolution so typed
provenance does not introduce N+1 queries. Downgrading migration `202609020031` to `202609010030`
intentionally deletes only `resource_occurrence` evidence-reference rows because the older CHECK
constraint cannot represent them. Findings, assessments, `resource_snapshot` references, and `scan`
references remain; retained evidence positions may therefore be non-contiguous.

Current lists and Site Intelligence use active Site Pages by default. Suppression hides a Finding
from that operational view but neither resolves nor deletes it. Direct history remains available.
