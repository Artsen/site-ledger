# Development Frontier

This file records non-canonical direction that may matter when planning a change. Canonical graph
truth is reviewed against post-PR #51 `main`:

`6e17e08e641b48660a7ed7a13d9227b288fcafc6`

PR #52 adds explicit Findings deletion/reset controls and adopts this maintained context map. PR
#53 completes the README and public project-presentation overhaul without changing product or
architecture semantics. Unimplemented work below remains non-canonical direction.

## Completed presentation work

PR #53 restructures the public README around plain-English product outcomes, current scope,
deterministic product screenshots, a concise Quick Start, workflow and architecture diagrams,
evidence/trust boundaries, and audience-oriented documentation. It also adds a documentation house
style and screenshot maintenance workflow. This presentation work does not add a canonical semantic
graph domain.

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
