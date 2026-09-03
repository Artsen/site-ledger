# Findings

Findings are deterministic, persistent logical conditions inferred from retained evidence. A
Finding is not evidence, a Comparison result, or AI interpretation.

```text
Evidence -> deterministic derivatives -> deterministic Finding evaluation
         -> persistent Findings -> Site Intelligence and workflow -> future AI interpretation
```

## V5 Detector Bundle Contract

`finding-evaluator-v3` runs the fixed `finding-detectors-v5` bundle over one frozen ordered
universe of active Site Page resource IDs and a composite `finding-evidence-manifest-v1`. The
manifest pins one server-selected terminal static Scan and the exact current membership selection
for every active sitemap Source. It contains exactly these 14 production detectors:

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
- `sitemap-page-http-error-v1` (`sitemap_page_http_error`,
  `sitemap-page-http-error-key-v1`): proven frozen sitemap membership plus a usable same-manifest
  static response with HTTP 4xx is medium and HTTP 5xx is high.
- `sitemap-page-noindex-v1` (`sitemap_page_noindex`, `sitemap-page-noindex-key-v1`): proven frozen
  sitemap membership plus applicable explicit `noindex` evidence is medium. It reuses the Page
  robots-directive parser exactly.
- `sitemap-page-redirect-v1` (`sitemap_page_redirect`, `sitemap-page-redirect-key-v1`): proven
  frozen sitemap membership plus an actual retained redirect chain ending at a different normalized
  URL is medium. URL spelling or normalization differences alone are not redirects.

All detectors use only retained `ResourceSnapshot`, `ResourceOccurrence`, `Scan`, and
`SourceEntryObservation` evidence. Render, Performance, Accessibility, Structured Content,
analytics, and Comparison are not first-class Finding evidence in this contract. No detector
fetches external evidence during evaluation.

## Sitemap Evidence

`SourceRefresh` is the collection envelope. For a sitemap `urlset`, each declaration creates one
immutable `SourceEntryObservation` at its deterministic source position, including duplicates,
raw and normalized URLs, the exact normalization version, sitemap metadata, validation state, scope
decision, and optional WebResource identity. The rows are staged and committed in the owning
Source-refresh transaction. Recursive sitemap observations belong to the exact child Source and
child refresh that declared them. Every sitemap refresh also records its document type. A
`sitemapindex` refresh stores the ordered IDs of the exact child refreshes produced by that
execution, while a `urlset` stores an empty child list and materializes Page membership directly.

`UrlSourceEntry` is different: it is the mutable current Inventory projection. Refresh can update
or reactivate that row, so a Finding assessment never points to it as historical evidence. Existing
pre-`202609030032` refreshes are not backfilled because current Inventory cannot reconstruct their
historical declarations. Their immutable sitemap evidence is explicitly unavailable.

At evaluation creation, active configured and robots-discovered sitemap roots are represented in
deterministic Source-ID order. Sitemap-index-discovered descendants enter only through their exact
parent refresh tree; mutable descendant activation cannot make stale membership current. A root's
selected refresh is its latest terminal refresh by `finished_at, id` when completed or completed
with errors. A latest failed or cancelled root has a null tree; queued and running work does not
replace the latest terminal selection. The frozen manifest recursively records exact refresh IDs:

```json
{
  "schema": "finding-evidence-manifest-v1",
  "static": {"scan_id": 123},
  "sitemap_roots": [
    {
      "url_source_id": 4,
      "refresh_tree": {
        "url_source_id": 4,
        "source_refresh_id": 91,
        "sitemap_document_type": "sitemapindex",
        "status": "completed",
        "membership_materialized": false,
        "children": [
          {
            "url_source_id": 5,
            "source_refresh_id": 92,
            "sitemap_document_type": "urlset",
            "status": "completed",
            "membership_materialized": true,
            "children": []
          }
        ]
      }
    },
    {"url_source_id": 7, "refresh_tree": null}
  ]
}
```

A valid, resource-bound observation in any usable selected leaf proves membership even when a
sibling is unavailable. Absence is clear only when every frozen root branch reaches usable
`urlset` membership evidence; index containers are not membership leaves. Otherwise absence is
unknown. With no active sitemap roots, sitemap detectors are clear/not applicable.
Duplicate declarations and multiple Sources still produce one logical Page Finding; assessments
retain exact Source and observation totals and at most 20 deterministic membership pointers with an
explicit truncation flag.

## Identity And Evaluation

A logical fingerprint contains Site ID, Finding type, logical key version, subject kind, and
WebResource ID. Scan, snapshot, status, severity, timestamps, and database Finding ID are excluded.
The V1 HTTP payload is preserved byte-for-byte, so V2 continues an existing HTTP Finding rather
than duplicating it.

The current evaluation input fingerprint includes `finding-evaluator-v3`, `finding-detectors-v5`,
the deterministic detector-manifest checksum, Site, source Scan, frozen composite evidence manifest,
and active-Page-universe checksum. A new Scan with unchanged Sources or a new eligible Source
refresh with the same Scan therefore creates a new evaluation. Historical terminal evaluations
remain readable; nonterminal historical evaluators do not execute through V3 code. Within one
bundle, the monotonic FindingEvaluation ID is the evidence-selection generation guard: after a
later evaluation completes, an older queued manifest fails closed and cannot mutate current
Findings. Job completion time is not treated as evidence time.

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

Counts cover detector-subject outcomes. Fourteen detectors over 100 active Pages produce 1,400 outcomes,
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

Finding lifecycle timestamps use evidence observation time. Cross-stream assessments preserve the
static snapshot `fetched_at` and each Source refresh `finished_at` independently; they do not imply
simultaneous collection. Evaluation execution timestamps and mutable acknowledgement timestamps
remain separate clocks. Acknowledgement never changes condition state. Resolution retains
acknowledgement; reopening clears it and records the prior acknowledgement timestamp in the
assessment.

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
assessment, evaluation, job, Scan, ResourceSnapshot, ResourceOccurrence, and
SourceEntryObservation resolution so typed
provenance does not introduce N+1 queries. Downgrading migration `202609020031` to `202609010030`
intentionally deletes only `resource_occurrence` evidence-reference rows because the older CHECK
constraint cannot represent them. Findings, assessments, `resource_snapshot` references, and `scan`
references remain; retained evidence positions may therefore be non-contiguous.

Downgrading `202609030032` to `202609020031` similarly deletes only unsupported
`source_entry_observation` evidence-reference rows before dropping immutable Source observations
and evaluation manifests. Compatible Findings, assessments, snapshot/occurrence/Scan references,
and non-contiguous positions remain. A Finding is not evidence, a mutable current Inventory row, a
Comparison, or AI interpretation.

Current lists and Site Intelligence use active Site Pages by default. Suppression hides a Finding
from that operational view but neither resolves nor deletes it. Direct history remains available.

## Administrative Deletion And Reset

Finding history is durable by default. Normal evidence deletion, Page suppression, and later
evaluations preserve lifecycle and assessment history. Two explicit destructive operations define
a narrow administrative/testing boundary:

- `DELETE /api/sites/{site_id}/findings/{finding_id}` removes one logical Finding, its assessments,
  typed evidence references, lifecycle timestamps, and acknowledgement. The completed frozen
  `FindingEvaluation`, detector summary, and Finding-evaluation job history remain unchanged. The
  same frozen input therefore still deduplicates; individual deletion is not a clean rerun.
- `POST /api/sites/{site_id}/findings/reset` with `{"confirm": true}` atomically removes all
  Site-scoped Findings, assessments, typed references, Finding evaluations, and terminal
  `finding_evaluation` BackgroundJobs/JobEvents. It preserves every collected evidence domain,
  including Scans, snapshots, occurrences, content, recursive Source refresh topology, and
  `SourceEntryObservation` rows. Removing the evaluation fingerprint and terminal job dedupe state
  allows the same retained evidence to be evaluated again deterministically.

Both operations return conflict while either a Site FindingEvaluation or its BackgroundJob is
queued/running. They never cancel active work implicitly. Site reset does not delete collected
website evidence, recollect evidence, change detector/evaluator identities, or rewrite historical
evaluation counters.
