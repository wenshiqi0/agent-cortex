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
   root, into `knowledge/`, or anywhere else. The cortex CLI enforces this.
2. **Cloning** an existing remote — use cortex (creates `repositories/` if needed,
   derives `<name>` from the URL unless `--name` is set):
   ```sh
   scripts/cortex repo clone <url> [--name <name>] [--dry-run]
   ```
3. **Creating** a brand-new repo:
   ```sh
   scripts/cortex repo init <name> [--dry-run]
   ```
4. **Listing** repos/worktrees is inventory — do not invent a second lister:
   ```sh
   bun run inventory --json
   ```
5. Each repo under `repositories/` is **independent** — its own `.git`, its own
   `CLAUDE.md`/`AGENTS.md`/skills. agent-cortex does not track their contents.
6. Before working inside one, read that repo's own context first (its
   `CLAUDE.md` / `AGENTS.md` and skills) — it overrides anything at the root.

## Do not

- Do not add a repo as a git submodule of agent-cortex.
- Do not place repos at the agent-cortex root or inside `knowledge/`.
- Do not copy a repo's skills into `knowledge/` — they stay with the repo.
- Do not hand-run `git clone` / `git init` outside `scripts/cortex repo …`.
