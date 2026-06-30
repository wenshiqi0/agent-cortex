---
name: cortex-inventory
description: Use when looking for agent-cortex skills, agents, generated tool links, repositories, projects, or worktrees, especially when grep/search may miss gitignored paths.
---

# cortex-inventory

Default repo-wide grep/search may respect `.gitignore` and miss `skills/`,
`agents/`, `repositories/`, `.claude/skills/`, and generated tool dirs.

Run inventory first:

```sh
bun run inventory
```

Need machine-readable output:

```sh
bun run inventory -- --json
```

Use returned paths as explicit search/read roots. Do not conclude a skill, agent,
repo, or worktree is absent from a root-level search that skipped ignored paths.
