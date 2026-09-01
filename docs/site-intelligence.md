# Site Intelligence

Site Intelligence is the read-only Overview composition for one saved Site. It queries current
workspace state, retained evidence, and compatible deterministic derivatives without persisting a
dashboard record, preparing evidence, or enqueueing work.

Active `SitePage` rows define the operational Page denominator. Suppressed Pages and deleted
workspace membership do not inflate current coverage, while their retained historical evidence
remains available in domain history. Every coverage value exposes its observed and eligible counts;
missing evidence never implies a healthy result.

Each evidence domain keeps an independent observation and completion clock. A recent Scan does not
make Render, Performance, Accessibility, Structured Content, Source, or Comparison evidence recent.
Source IDs and algorithm identities remain visible where the domain provides them.

## Accessibility Compatibility

Current Accessibility coverage, outcome totals, and run clock use the same evidence identity as
Accessibility Collection Plans:

- responsive profile
- axe-core version
- detector bundle SHA-256
- integration version
- normalization version
- ruleset profile
- ruleset SHA-256

Evidence with an older or otherwise incompatible identity remains immutable historical evidence,
but it is not selected as current merely because its observation or run timestamp is newer.

Aggregate Accessibility profile coverage uses Page/profile slots. Its eligible count is the number
of active Pages multiplied by the two current supported profiles (`desktop` and `mobile`), and its
observed count is the number of distinct current-compatible `(Page, profile)` observations. Five
active Pages with only five desktop observations therefore report 5 of 10 rather than 5 of 5.
Outcome fields named as Pages, including Pages with violations and failed Pages, remain distinct
Page counts rather than profile-slot counts.

## Collection Coverage

Collection Plan previews and Site Intelligence coverage share the deterministic selectors in
`services.collection_plans`. Performance contexts, Accessibility profiles, Render collection
profiles, and Structured Content extractor identities therefore use the same definition of covered,
in flight, missing, and ineligible Pages.

Site Intelligence does not create Findings or a global health score. Findings are separately
persisted deterministic interpretations linked back to evidence.
