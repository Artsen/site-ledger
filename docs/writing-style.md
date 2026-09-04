# Site Ledger Writing Style

This guide applies to the README, user-facing documentation, setup material, and public project
presentation. Architecture references may be more technical, but they should follow the same
evidence discipline.

## Write For The Reader

Start with what a person can do, learn, or verify. Introduce implementation detail only after the
product concept is clear. A website owner should not need to understand database models before
understanding why Site Ledger retains history.

Use short paragraphs, concrete examples, descriptive headings, and progressive disclosure. Put
common workflows before internals and exceptional operator procedures.

## Use Product Terms First

Prefer the established terms **Site**, **Page**, **Scan**, **Source**, **Observation**, **Finding**,
and **Collection Plan** in product copy. Add an internal class or artifact name only when it helps
the intended reader.

Good:

> A Page is a persistent URL identity within a Site. `SitePage` stores its mutable workspace state,
> while `WebResource` stores normalized URL identity.

Avoid opening with the class names and requiring the reader to infer the product concept.

## Use Plain Technical English

Prefer direct verbs and concrete nouns:

- "Run an Accessibility audit," not "initiate automated accessibility observation collection."
- "Open the retained HTML," not "access the source-content evidence payload."
- "The worker is offline," not "execution capacity is unavailable."

Keep exact algorithm identities, schema terms, and field names where provenance or developer
contracts require them. Explain their purpose before listing them.

## Separate Current Capability From Future Direction

Never describe planned work as implemented. Use **Available**, **Planned**, or **Not yet
implemented** when ambiguity is possible. Roadmaps are non-binding direction, not product claims.

Verify public capability statements against current source, tests, and canonical documentation.
Current code wins when old prose disagrees.

## Preserve Evidence Semantics

State only what the evidence proves:

- automated Accessibility evidence is not WCAG certification;
- correlation is not causation;
- sitemap absence is not proof that a Page was deleted;
- not observed in a Scan is not removed from the live Site;
- missing Performance evidence is not good performance;
- a technology detected later was not necessarily installed earlier;
- a derived Finding or comparison does not replace its source evidence.

Use "observed," "declared," "detected," "inferred," and "unknown" deliberately. Do not collapse
these states for smoother prose.

## Explain Independent Clocks

Static Scans, Source refreshes, Render Runs, Performance observations, Accessibility audits, and
derived artifacts can have different collection times. Do not describe them as one universal
current snapshot. Include coverage, observation time, compatibility, or provenance when relevant.

## Describe Local-First Boundaries

Say what remains local and when an external service is contacted. Do not imply that local-first
means no network activity: crawling visits configured Sites, and Performance collection contacts
configured providers when initiated.

## Explain Destructive Actions Before The Command

Describe what will be deleted and what will be preserved. Distinguish evidence deletion, mutable
workspace deletion, suppression/removal, and rebuildable derivative reset. Never use "clear" or
"reset" when the retention boundary is ambiguous.

## Avoid Hype

Do not use claims such as "revolutionary," "magical," "best-in-class," "perfect," or "AI-powered."
Prefer a verifiable description of behavior. Define necessary jargon at first useful use and keep
internal version identities out of introductory copy.

## Maintain Screenshots

README review captures come from deterministic mocked Playwright fixtures. Run:

```powershell
cd frontend
npm run review:readme-screens
```

The command writes temporary captures to `.tmp/readme-screenshots/`, which remains untracked. Only
manually reviewed images should be copied to `docs/screenshots/readme/` and committed.

- Use fictional Sites, URLs, timestamps, counts, and evidence. Never use retained, customer,
  company, or personal data.
- Show implemented states that could truthfully coexist. Do not create controls or capabilities
  only for a screenshot.
- Inspect every capture for loading states, weak cropping, hidden content, illegible text, and
  private data.
- Refresh a committed image when it materially misrepresents the current product.
- Avoid screenshot churn for cosmetic internal refactors that do not change the represented
  workflow.
- Keep the existing workspace navigation review captures separate from the curated README gallery.

## Review Checklist

Before publishing user-facing documentation, verify:

1. The intended reader can identify the outcome before encountering internals.
2. Product terms precede implementation terms.
3. Current, planned, and unavailable capabilities are distinguishable.
4. Evidence claims preserve absence, uncertainty, clock, and provenance semantics.
5. Local storage, external calls, and destructive behavior are explicit where relevant.
6. Commands, links, versions, screenshots, and status claims match the repository.
