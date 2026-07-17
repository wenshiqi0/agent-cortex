---
name: code-workflow
description: >-
  Use when developing agent-cortex itself or any repositories/ subproject —
  features, bug fixes, scripts, skill mechanization, or when the user asks for
  code-workflow / a multi-model plan-test-implement loop with subagents.
---

# Code Workflow

Orchestrator-only loop. Applies to **agent-cortex root work** (skills, scripts,
knowledge tooling) **and** `repositories/<repo>/` work. Main session stays
rooted at **agent-cortex**, keeps a thin ledger, and never does
plan/test/implement work itself. Every stage is a **fresh subagent** with an
explicit model. Hand artifacts as **files**, not pasted bodies.

**REQUIRED BACKGROUND:** `feature-workflow` when touching `repositories/`.
**REQUIRED SUB-SKILL:** `superpowers:test-driven-development` for RED/GREEN.

Agent-cortex is not exempt. Shared rules require this skill for development in
this repo; only pure one-shot prose rule/doc edits with no behavior change may
skip it.

## Model Contract (fail-fast)

| Role | Model | Cursor Task `model` slug |
|------|-------|--------------------------|
| Main / orchestrator | GPT 5.6 Sol High | session must already be this model |
| Plan subagent | GPT 5.6 Sol High | `gpt-5.6-sol-high` |
| Test writer (per task) | GPT 5.6 Sol High | `gpt-5.6-sol-high` |
| Test verifier (per task) | GPT 5.6 Terra Medium | `gpt-5.6-terra-medium` |
| Implement subagent (per task) | Grok 4.5 | `cursor-grok-4.5-high-fast` |

Rules:

1. Before starting, confirm the **main session model is GPT 5.6 Sol High**.
   If not, stop and ask the user to switch. Do not continue under another model.
2. Every `Task` / subagent dispatch **must** set `model` to the slug above.
   Never omit `model` (omit inherits the session model and breaks the contract).
3. If a required model or slug is unavailable, **stop and ask the user**.
   Do not substitute another model, do not fall back to Auto, do not run the
   stage on the main model.
4. Main model only: scope task, dispatch, read short status, update ledger,
   resolve blockers. No planning prose, no writing tests, no production code
   on the main thread.

## Progress Ledger (JSONL — required)

Dual files under `<worktree-or-cortex-root>/.cortex/code-workflow/`:

| File | Role |
|------|------|
| `progress.jsonl` | **Active** ledger only (small). `show` / `next` / fold read this. |
| `history.jsonl` | Optional archive of completed/removed work (append-only). |

Not `.superpowers/` — host repos rarely ignore that name and it pollutes
`git status` / reviews. `progress.py` writes a self-ignore
`.cortex/.gitignore` (`*` / `!.gitignore`) so scratch stays out of commits
even when the target repo has no root ignore entry.

Append-only until `compact`. **Never hand-edit.** Drive it only via:

```sh
SCRIPT=knowledge/skills/code-workflow/scripts/progress.py
# or the linked path: .claude/skills/code-workflow/scripts/progress.py

python3 $SCRIPT init --worktree "$WT" --goal "..." \
  --constraint "..." --constraint "..."
python3 $SCRIPT set-plan --worktree "$WT" --plan "$PLAN" --mark-done
python3 $SCRIPT add-todo --worktree "$WT" --id T1 --title "..." --brief "$BRIEF"
python3 $SCRIPT mark --worktree "$WT" --id T1 --stage test_write \
  --stage-status in_progress
python3 $SCRIPT mark --worktree "$WT" --id T1 --stage test_write \
  --artifact "$REPORT"   # stage defaults to done when --stage-status omitted
python3 $SCRIPT mark --worktree "$WT" --id T1 --status blocked --note "..."
python3 $SCRIPT mark-run --worktree "$WT" --stage closeout --status done
python3 $SCRIPT show --worktree "$WT"            # human fold (progress only)
python3 $SCRIPT show --worktree "$WT" --json     # machine fold (progress only)
python3 $SCRIPT next --worktree "$WT"            # next todo+stage (progress only)
python3 $SCRIPT compact --worktree "$WT"         # archive done/skipped → history;
                                                 # rewrite progress as active snapshot
```

`compact` folds `progress.jsonl`, appends one `archive` event to `history.jsonl`
for completed (`done` / `skipped`) todos, then atomically rewrites `progress.jsonl`
as a single `snapshot` of active todos. If nothing is completed, it still rewrites
progress to a snapshot but does **not** append an empty archive. Idempotent.

`mark` does **not** auto-compact when a todo becomes `done`. Orchestrator should
run `compact` after finishing todos and/or at closeout so the active ledger stays
small.

What the active ledger stores:

| Field | Meaning |
|-------|---------|
| `goal` / `worktree` / `plan` / `constraints` | run basics (`init` / `set-plan` / `snapshot`) |
| `todos[]` | id, title, brief path, overall `status` |
| `todos[].stages` | `test_write` → `verify_red` → `implement` → `verify_green` |
| `todos[].artifacts` | report paths per stage |
| `run` | `preflight` / `plan` / `closeout` |

Todo / stage status values: `pending` | `in_progress` | `done` | `blocked` | `skipped`.

Main must `mark` after every accepted stage and use `next` to pick work after
compaction. Do not keep a parallel `progress.md`.

## Loop

```text
1. Preflight (main)
2. Plan          -> GPT 5.6 Sol High subagent
3. For each task:
     Test write   -> GPT 5.6 Sol High subagent
     Verify RED  -> GPT 5.6 Terra Medium subagent
     Implement   -> Grok 4.5 subagent (GREEN + refactor)
     Verify GREEN-> GPT 5.6 Terra Medium subagent
4. Closeout (main): verify tests, report status
```

### 1. Preflight (main)

- Stay at agent-cortex root. Do not move workspace into a subproject.
- Target path is either the agent-cortex root (this repo) or a
  `repositories/<repo>.worktrees/<branch>/` worktree.
- If work is under `repositories/`, start a worktree per `feature-workflow`.
  Agent-cortex root edits stay in this repo (no nested worktree required unless
  the user asks).
- `progress.py init --worktree "$WT" --goal "..."` (constraints via repeated
  `--constraint`). Gather only coordinates for the planner: goal, worktree path,
  related paths from `bun run inventory` when needed.

### 2. Plan (GPT 5.6 Sol High)

Dispatch a **new** subagent. Prompt must require:

- Bite-sized tasks with explicit files, interfaces, commands, and acceptance
  checks.
- Prefer absolute paths + "read these files" over pasting source.
- TDD order baked into the plan: tests before production code.
- Output path for the plan file (write the full plan to disk).

Main reads only: plan path, task list summary, any blockers. Then:

```sh
python3 $SCRIPT set-plan --worktree "$WT" --plan "$PLAN" --mark-done
# one add-todo per planned task (brief = extracted task file)
python3 $SCRIPT add-todo --worktree "$WT" --id T1 --title "..." --brief "$BRIEF"
```

Do not re-plan on main unless the planner failed or the user changed scope.

### 3. Per task — Write tests (GPT 5.6 Sol High)

Dispatch a **new** subagent with:

- Task brief path (task text only; not the whole plan if large)
- Worktree / repo absolute path
- Instruction: write tests for this task only; **do not run them** and **do not
  write production implementation**
- Test-writer report path listing tests added and expected failure

If production code appeared → delete it (TDD iron law) and re-dispatch test.
On accept: `mark --id Tn --stage test_write --artifact "$REPORT"`.

### 4. Per task — Verify RED (GPT 5.6 Terra Medium)

Dispatch a **new** verifier subagent with:

- Task brief path
- Test-writer report path / test file paths
- Instruction: review test relevance, run tests, confirm RED for the right
  reason; **do not edit tests or production code**
- RED verification report path

Accept only when report shows: tests cover the task, command run, expected
failure. If tests pass immediately or fail for the wrong reason → reject and
re-dispatch the test writer with verifier findings.
On accept: `mark --id Tn --stage verify_red --artifact "$REPORT"`.

### 5. Per task — Implement GREEN (Grok 4.5)

Dispatch a **new** subagent with:

- Same task brief path
- Test-writer report, RED verification report, and test file paths
- Instruction: minimal code to pass; run tests to GREEN; then refactor while
  staying green; no extra features
- Report file path

The implement report records code changed and commands attempted, but its own
pass claim is not acceptance evidence.
After implement returns: `mark --id Tn --stage implement --artifact "$REPORT"`
(overall GREEN still needs Terra).

### 6. Per task — Verify GREEN (GPT 5.6 Terra Medium)

Dispatch a **fresh** verifier subagent with:

- Task brief path
- RED verification report, implement report, and test file paths
- Instruction: inspect scope, run the task tests independently, confirm GREEN
  and no test weakening; **do not edit tests or production code**
- GREEN verification report path

Accept only when report shows: acceptance checks met, independent command
output passes, tests were not weakened. On failure → send findings to a new
implement subagent, then verify again with a fresh verifier.
On accept: `mark --id Tn --stage verify_green --artifact "$REPORT"` (folds
todo to `done` when all stages done). Then `next` for the following task.

### 7. Closeout (main)

- `progress.py show --json`: every todo `status=done` with all four stages
  `done`/`skipped` and artifact paths set.
- `progress.py mark-run --stage closeout --status done`
- Run or dispatch a final verification command if needed.
- Report to user: plan path, tasks done, test commands, remaining risks.
- PR / worktree release still follows `feature-workflow` + `submitting-prs`.

## File Handoff Contract

| Artifact | Who writes | Who reads |
|----------|------------|-----------|
| Plan file | Plan subagent | Main + later briefs |
| Task brief | Main (extract from plan) | Test writer + Verifier + Implement |
| Test-writer report | Test writer | Main + RED verifier + Implement |
| RED verification report | Terra verifier | Main + Implement |
| Implement report | Implement subagent | Main + GREEN verifier |
| GREEN verification report | Terra verifier | Main |
| `progress.jsonl` | Main via `progress.py` only | Main (`show` / `next` after compaction) |

Subagent return to main: **status + paths + one-line summary** only.
Full detail stays in the report file.

## Status Values

Subagents report one of:

- `DONE` — stage complete with evidence in report file
- `DONE_WITH_CONCERNS` — complete; main must read concerns before next stage
- `NEEDS_CONTEXT` — main supplies missing paths/decisions, re-dispatch same role
- `BLOCKED` — main escalates to user; do not silently change models or skip TDD

## Red Flags — STOP

- Main model writes plan, tests, or production code
- Missing or substituted stage model
- Test writer runs or validates its own tests
- Implement before independently verified RED
- Accepting implementer's own GREEN claim without Terra verification
- Keeping "reference" implementation written before tests
- Moving Cursor workspace root into `repositories/` or a worktree
- Omitting `model` on Task dispatch
- Continuing when a required model slug is unavailable without asking user
- Hand-editing `progress.jsonl` or keeping a parallel `progress.md` ledger

## Rationalizations

| Excuse | Reality |
|--------|---------|
| "Main can just write the small test" | Violates stage isolation. Dispatch test agent. |
| "Implement and test in one subagent is faster" | Breaks TDD proof and model contract. Split. |
| "Task is tiny, skip RED verify" | No GREEN without watched RED. |
| "Paste the whole repo so Grok has context" | Paths not dumps; split tasks if needed. |
| "Omit model, Auto is fine" | Contract requires explicit slugs every dispatch. |
| "I'll just edit the markdown ledger" | Use `progress.py`. JSONL is the only ledger. |
