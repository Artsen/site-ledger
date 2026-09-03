# Optional root `AGENTS.md` pointer

Add this small pointer to the repository root `AGENTS.md`:

```text
For unfamiliar or cross-domain work, use docs/brain/AGENT_GUIDE.md to retrieve
minimum safe context before editing. The second brain is a navigation layer only;
current source, migrations, and tests remain authoritative.
Update affected brain files in the same PR when domain boundaries, durable invariants,
major workflows, semantic relationships, or minimum context packs materially change.
```

Do not copy the full second brain into root agent instructions; doing so defeats the context-compression goal.
