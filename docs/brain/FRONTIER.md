# Development Frontier

This file records non-canonical direction that may matter when planning a change. Canonical graph
truth is reviewed against post-PR #51 `main`:

`6e17e08e641b48660a7ed7a13d9227b288fcafc6`

PR #52 adds explicit Findings deletion/reset controls and adopts this maintained context map. Its
semantics belong in canonical documentation because these files describe the repository state the
PR will create; unimplemented work below does not.

## Immediate follow-up

The next PR is a dedicated README and project-presentation overhaul, using
`Artsen/web-video-optimizer` as a quality benchmark without mechanically copying it. Site Ledger's
public presentation should lead with the tagline "A historical record of your website," explain the
product in plain language before developer internals, show real current screenshots and status,
and provide a concise tour, capability summary, Quick Start, workflow and architecture diagrams,
privacy/security notes, limitations, gallery, and audience-oriented documentation map.

This is presentation/documentation work, not a new product architecture domain, and therefore does
not belong in the canonical semantic graph.

## Next substantive product feature

Collection Plans V2 remains the next intended implementation area after the README work, centered
on `refresh_current` and freshness/stale-current groundwork. It must not be described as current
capability until implemented.

Recent platform sequencing also places complexity-management work before a broad Web Estate
expansion:

- consolidate BackgroundJob lifecycle contracts;
- decompose large API/frontend workspace modules;
- establish Web Estate identity foundations;
- add host/domain evidence and discovery;
- infer technology/platform evidence.

These are planning signals, not a binding numbered constitution. PR boundaries may move as
implementation reveals better ownership boundaries.
