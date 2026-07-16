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

| Role | Model (required) | Cursor Task `model` slug |
|------|------------------|--------------------------|
| Main / orchestrator | GPT 5.6 Sol Medium | session must already be this model |
| Plan subagent | GPT 5.6 Sol High | `gpt-5.6-sol-high` |
| Test subagent (per task) | GPT 5.6 Sol Medium | `gpt-5.6-sol-medium` |
| Implement subagent (per task) | Grok 4.5 High Fast | `cursor-grok-4.5-high-fast` |

Rules:

1. Before starting, confirm the **main session model is GPT 5.6 Sol Medium**.
   If not, stop and ask the user to switch. Do not continue under another model.
2. Every `Task` / subagent dispatch **must** set `model` to the slug above.
   Never omit `model` (omit inherits the session model and breaks the contract).
3. If a required model or slug is unavailable, **stop and ask the user**.
   Do not substitute another model, do not fall back to Auto, do not run the
   stage on the main model.
4. Main model only: scope task, dispatch, read short status, update ledger,
   resolve blockers. No planning prose, no writing tests, no production code
   on the main thread.

## Context Budget (256K)

Each subagent prompt + readable inputs for **one task stage** must fit about
**256K tokens**. Treat this as a hard planning limit.

- Split oversized work into more tasks until each stage's brief, interfaces,
  and named files fit.
- Prefer absolute paths + "read these files" over pasting source.
- Do not paste prior-task summaries into later dispatches — only interfaces
  the brief cannot know, plus global constraints.
- If a subagent returns `NEEDS_CONTEXT` that would blow the budget, split the
  task instead of stuffing more files.

## Loop

```text
1. Preflight (main)
2. Plan          -> GPT 5.6 Sol High subagent
3. For each task:
     Test (RED)  -> GPT 5.6 Sol Medium subagent
     Implement   -> Grok 4.5 High Fast subagent (GREEN + refactor)
4. Closeout (main): verify tests, report status
```

### 1. Preflight (main)

- Stay at agent-cortex root. Do not move workspace into a subproject.
- Target path is either the agent-cortex root (this repo) or a
  `repositories/<repo>.worktrees/<branch>/` worktree.
- If work is under `repositories/`, start a worktree per `feature-workflow`.
  Agent-cortex root edits stay in this repo (no nested worktree required unless
  the user asks).
- Create a progress ledger file (e.g. `.superpowers/code-workflow/progress.md`
  under the worktree or cortex scratch) and append status after each stage.
- Gather only coordinates for the planner: goal, repo/worktree absolute path,
  constraints, related paths from `bun run inventory` when needed.

### 2. Plan (GPT 5.6 Sol High)

Dispatch a **new** subagent. Prompt must require:

- Bite-sized tasks; each task's implement+test stage inputs ≤ ~256K.
- Explicit files, interfaces, commands, and acceptance checks per task.
- TDD order baked into the plan: tests before production code.
- Output path for the plan file (write the full plan to disk).

Main reads only: plan path, task list summary, any blockers. Do not re-plan on
main unless the planner failed or the user changed scope.

### 3. Per task — Test RED (GPT 5.6 Sol Medium)

Dispatch a **new** subagent with:

- Task brief path (task text only; not the whole plan if large)
- Worktree / repo absolute path
- Instruction: write the failing tests for this task only; run them; confirm
  RED for the right reason; **no production implementation**
- Report file path

Accept only when report shows: tests added, command run, expected failure.
If tests pass immediately → reject; re-dispatch test agent to fix the test.
If production code appeared → delete it (TDD iron law) and re-dispatch test.

### 4. Per task — Implement GREEN (Grok 4.5 High Fast)

Dispatch a **new** subagent with:

- Same task brief path
- Test report path / test file paths
- Instruction: minimal code to pass; run tests to GREEN; then refactor while
  staying green; no extra features
- Report file path

Accept only when report shows: commands, pass evidence, commit hash if
committing was requested. On failure → fix via another implement subagent,
not on main.

### 5. Closeout (main)

- Confirm ledger: every task has RED then GREEN evidence.
- Run or dispatch a final verification command if needed.
- Report to user: plan path, tasks done, test commands, remaining risks.
- PR / worktree release still follows `feature-workflow` + `submitting-prs`.

## File Handoff Contract

| Artifact | Who writes | Who reads |
|----------|------------|-----------|
| Plan file | Plan subagent | Main + later briefs |
| Task brief | Main (extract from plan) | Test + Implement |
| Test report | Test subagent | Main + Implement |
| Implement report | Implement subagent | Main |
| Progress ledger | Main | Main (resume after compaction) |

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
- Implement before confirmed RED
- Keeping "reference" implementation written before tests
- Pasting large source/history into subagent prompts past ~256K
- Moving Cursor workspace root into `repositories/` or a worktree
- Omitting `model` on Task dispatch
- Continuing when Sol High / Grok slug is unavailable without asking user

## Rationalizations

| Excuse | Reality |
|--------|---------|
| "Main can just write the small test" | Violates stage isolation. Dispatch test subagent. |
| "Sol High unavailable, use Sol Medium for plan" | Fail-fast. Ask user. No silent substitute. |
| "Implement and test in one subagent is faster" | Breaks TDD proof and model contract. Split. |
| "Task is tiny, skip RED verify" | No GREEN without watched RED. |
| "Paste the whole repo so Grok has context" | Split tasks; 256K budget; paths not dumps. |
| "Omit model, Auto is fine" | Contract requires explicit slugs every dispatch. |
