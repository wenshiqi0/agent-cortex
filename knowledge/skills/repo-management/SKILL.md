---
name: repo-management
description: Use when the user asks to add, clone, create, or check out a new git repository or project directory. All repositories live under the repositories/ directory at the agent-cortex root — never scatter them elsewhere.
---

# Repo Management

All git repositories and project directories belong under **`repositories/`** at
the agent-cortex root. Keep the root clean: `knowledge/` (the SSOT) and
`repositories/` (the code) are the only two content areas.

## When to use

The user asks to:
- clone a repo ("clone X", "add the Y repo", "pull down Z")
- create a new project/repo ("start a new repo", "init a project called …")
- check out / set up an existing repository locally

## Rules

1. **Destination is always `repositories/<name>/`.** Never clone or init into the
   root, into `knowledge/`, or anywhere else.
2. **Create `repositories/` if it does not exist** before the first repo:
   ```sh
   mkdir -p repositories
   ```
3. **Cloning** an existing remote:
   ```sh
   git clone <url> repositories/<name>
   ```
   Derive `<name>` from the repo name unless the user specifies one.
4. **Creating** a brand-new repo:
   ```sh
   mkdir -p repositories/<name> && git -C repositories/<name> init
   ```
5. Each repo under `repositories/` is **independent** — its own `.git`, its own
   `CLAUDE.md`/`AGENTS.md`/skills. agent-cortex does not track their contents.
6. Before working inside one, read that repo's own context first (its
   `CLAUDE.md` / `AGENTS.md` and skills) — it overrides anything at the root.

## Do not

- Do not add a repo as a git submodule of agent-cortex.
- Do not place repos at the agent-cortex root or inside `knowledge/`.
- Do not copy a repo's skills into `knowledge/` — they stay with the repo.
