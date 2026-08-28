# Findings

Findings are deterministic, persistent logical conditions inferred from retained evidence. They
are not evidence, Scan observations, comparisons, or AI interpretations.

```text
Evidence -> deterministic derivatives -> deterministic Finding evaluation
         -> persistent Findings -> Site Intelligence and workflow -> future AI interpretation
```

## V1 Contract

`finding-evaluator-v1` runs `finding-detectors-v1`, which contains exactly one production detector:
`page-http-error-v1`. It evaluates a frozen ordered universe of active SitePage WebResource IDs
against one server-selected terminal static Scan. A fetched ResourceSnapshot with an effective
400-599 status is detected; a fetched snapshot with another HTTP status is clear; missing, failed,
or incomplete evidence is unknown. A transport attempt is not usable Page evidence by itself.

The logical key is `page-http-error-key-v1`: Site, Finding type, key version, subject kind, and
WebResource ID. Scan, snapshot, status, severity, timestamps, and database Finding ID are excluded,
so 404 and 500 observations update one logical Finding.

## Lifecycle And Time

The current states are detected, unknown, and resolved. Reopen is the transition from a previously
resolved condition back to detected. Only newer trustworthy clear evidence resolves a Finding.
Missing, failed, deleted, insufficient, or suppressed evidence never proves resolution.

Finding lifecycle timestamps use evidence observation time. Evaluation execution timestamps and
mutable acknowledgement timestamps remain separate clocks. An evaluation whose evidence horizon
is older than the latest completed evaluation for the same Site and detector bundle fails closed;
V1 does not provide historical time-travel evaluation.

Assessments are immutable and are stored only for newly detected Findings and existing Findings.
Clean or unknown Pages with no Finding do not create rows. Exact-input fingerprints deduplicate
evaluations and their assessments.

A completed exact input is immutable and never reruns. An input with queued or running execution
also deduplicates to that active attempt. A user may explicitly rerun the same failed or cancelled
input: V1 reuses its frozen FindingEvaluation and BackgroundJob, preserves job events and attempt
count, verifies that the failed transaction committed no assessments, and resets only execution
result state. This is manual recovery, not an automatic retry policy.

If a running Finding job loses its lease, recovery interrupts the BackgroundJob and marks the
FindingEvaluation failed with `lease_expired` provenance. The abandoned evaluation transaction is
rolled back, so no partial Finding, assessment, evidence reference, or lifecycle transition is
applied. The user can then explicitly rerun that exact immutable input.

## Workflow And Visibility

Acknowledgement is mutable workflow and never changes condition state. Resolution retains current
acknowledgement. Reopening clears current acknowledgement so the active condition needs a fresh
decision; the reopened assessment records the prior acknowledgement timestamp.

Current lists and Site Intelligence use active SitePages by default. Suppression hides a Finding
from that operational view but neither resolves nor deletes it. Direct history remains available.

Evidence references are ordered durable typed pointers rather than polymorphic foreign keys.
Creation validates the referenced Scan or ResourceSnapshot. Evidence deletion therefore preserves
Finding and assessment history, while reads truthfully report that a source is no longer retained.
Raw evidence is never copied into Finding tables.

Evaluation and detail reads batch BackgroundJob and retained-evidence resolution by evidence kind.
Evaluation SELECT work remains bounded as the active Page universe grows. Write volume currently
scales with persisted operational Findings, assessments, and evidence references rather than with
every clean Page; bulk write optimization is deferred until detector packs materially increase
Finding volume.

Future detector packs may add indexability and other deterministic conditions. They must preserve
these identity, chronology, evidence, and unknown-state contracts.
