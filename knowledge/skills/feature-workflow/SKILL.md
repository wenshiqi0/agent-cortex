---
name: feature-workflow
description: Use BEFORE editing any code in a repo under repositories/ — features, bug fixes, refactors, config/build tweaks, dependency bumps, ANY change. The work MUST happen in a git worktree alongside the repo, never on the repo's main working tree. On completion, check PR status with gh and confirm with the user before releasing the worktree.
---

# Feature Workflow

**Any change to a repo under `repositories/` goes through a git worktree** — not
just big features. Bug fixes, refactors, build/config edits, dependency bumps,
one-line tweaks: all of it. If you are about to edit, create, or delete a file
inside `repositories/<repo>/`, stop and make a worktree first.

The main working tree at `repositories/<repo>/` stays clean — never commit work
directly on it. Worktrees live **alongside** the repo, never inside it.

## When this applies

Triggers on ANY of these against a repo in `repositories/`:
- add/change a feature
- fix a bug
- refactor
- change build/compile/CI config (e.g. Cargo.toml, tsconfig, Dockerfile)
- bump or change dependencies
- any edit that produces a commit

If unsure whether a task "counts" — it does. Default to a worktree.

## Placement

```
repositories/
  <repo>/                        <- main working tree (untouched)
  <repo>.worktrees/<branch>/     <- one worktree per branch
```

Never create the worktree inside `repositories/<repo>/` — it pollutes the repo.

## Start the work

```sh
cd repositories/<repo>
git worktree add ../<repo>.worktrees/<branch> -b <branch>
cd ../<repo>.worktrees/<branch>
```

- `<branch>` = a descriptive branch name (`feat/login`, `fix/target-bloat`,
  `chore/cargo-incremental`, …).
- Branch off the repo's default branch unless the user says otherwise.
- Do ALL edits, commits, and the PR from inside this worktree.

## On completion — release protocol (in order)

Done = work committed and a PR opened. Before removing anything:

1. **Check PR status with `gh`** — do not guess:
   ```sh
   gh pr view <branch> --json state,mergeStateStatus,mergedAt
   gh pr checks <branch>      # CI status
   ```
2. **Report to the user**: PR merged? CI green? Then **ask explicitly** whether
   to release the worktree. Do NOT auto-remove.
3. **Only after the user confirms**, release:
   ```sh
   cd repositories/<repo>
   git worktree remove ../<repo>.worktrees/<branch>
   git branch -d <branch>     # -d (safe). -D only if the user confirms force.
   ```

## Rules

- One worktree per branch; remove it once its PR is merged + confirmed.
- If the PR is NOT merged, keep the worktree — releasing risks losing work.
- Releasing a worktree is destructive; always confirm with the user first.
- `git worktree prune` cleans up stale entries after manual deletions.
