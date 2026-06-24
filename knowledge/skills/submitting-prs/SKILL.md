---
name: submitting-prs
description: Use when committing code changes, creating a GitHub pull request, updating an existing PR description, or asked to submit changes for review.
---

# Submitting PRs

Use this skill to turn local changes into a stable commit + PR without hand-rolling
git/gh command chains.

## Core Contract

This is a two-step workflow:

1. **Model writes the review content from diff evidence.** Inspect only the paths
   that should be submitted, then draft:
   - PR title: Conventional Commit style, e.g. `feat: ...`, `fix: ...`, `chore: ...`
   - commit message: same intent as the PR title; add a body only when the why is not obvious
   - PR body: `## Summary` and `## Test plan`
2. **Bun script performs the mechanical submission.** Pass the title, body file,
   commit message, and every path explicitly to the script.

The model chooses content and paths. The script stages, commits, pushes, creates
or updates the PR, and returns stable JSON.

## Required Preparation

Run these from the repo root before writing PR text:

```sh
git status --short
git diff -- <path>...
git log -5 --oneline
```

Rules:

- Never submit all changes by default. Pass one `--path` per intended path.
- Do not include `.env`, credentials, private keys, tokens, or generated secrets
  unless the user explicitly asked and `--allow-sensitive` is justified.
- If there is an existing PR for the branch, the script appends the new body under
  `## Updates` instead of replacing the previous description.
- If no existing PR exists, the script creates one with the generated body.

## Command

Create a temporary body file with your file-editing tool, then call the root
script from the repository you are submitting:

```sh
bun scripts/submit-pr.js \
  --title "feat: add stable PR submission" \
  --commit-message "feat: add stable PR submission" \
  --body-file /tmp/pr-body.md \
  --path knowledge/skills/submitting-prs/SKILL.md \
  --path scripts/submit-pr.js
```

Use `--dry-run` first when validating behavior or when the user has not clearly
asked to submit. Use `--base <branch>` when the PR should target a non-default
base. Use `--draft` only for a new draft PR.

The maintained script lives at the agent-cortex root: `scripts/submit-pr.js`.

## Return To User

Report:

- commit/PR action from the JSON (`created`, `updated`, or `dry-run`)
- PR URL when present
- title used
- paths submitted
- tests or checks run before submission

If the script exits with `status: error`, fix the cause before retrying unless it
requires a user decision.
