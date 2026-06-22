---
name: worktree-workflow
description: Use when starting feature development on a repo under repositories/. Feature work MUST be isolated in a git worktree (never on the repo's main working tree). On completion, check PR merge status with gh and confirm with the user before releasing the worktree.
---

# Worktree Workflow

Feature development is **isolated in a git worktree**, never done directly on a
repo's main working tree. Worktrees live **alongside the repo**, not inside it.

## Placement

```
repositories/
  <repo>/                        <- main working tree (untouched by feat work)
  <repo>.worktrees/<branch>/     <- one worktree per feature branch
```

Never create the worktree inside `repositories/<repo>/` — it pollutes the repo.

## Start a feature

```sh
cd repositories/<repo>
git worktree add ../<repo>.worktrees/<branch> -b <branch>
cd ../<repo>.worktrees/<branch>
```

- `<branch>` = the feature branch name (e.g. `feat/login`).
- Branch off the repo's default branch unless the user says otherwise.
- Do all feature edits, commits, and the PR from inside this worktree.

## On completion — release protocol (do in order)

Feature "done" = work committed and a PR opened. Before removing anything:

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
   git branch -d <branch>     # -d (safe). Use -D only if user confirms force.
   ```

## Rules

- One worktree per feature branch; remove it once its PR is merged + confirmed.
- If the PR is NOT merged, keep the worktree — releasing would risk losing work.
- Releasing a worktree is destructive; always confirm with the user first.
- `git worktree prune` to clean up stale entries after manual deletions.
