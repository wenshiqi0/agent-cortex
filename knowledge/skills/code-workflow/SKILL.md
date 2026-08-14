---
name: code-workflow
description: >-
  Use when developing agent-cortex itself or any repositories/ subproject —
  features, bug fixes, scripts, skill mechanization, or when the user asks for
  code-workflow / a multi-agent plan-test-implement loop with subagents.
---

# Code Workflow

Orchestrator-only. Main never writes code/tests/plans. Execution agents are
protocol-blind and receive file paths only. Facade: `scripts/workflow.py`.
See `README.md` for architecture, lifecycle, layout, and verification.

## When it triggers

Use for plan→test→implement work in agent-cortex or `repositories/`. Skip only
for pure one-shot prose rule/doc edits with no behavior change.

## Lane gate (Fast Lane vs Full Loop)

Fast Lane only if **all five** are clearly yes; otherwise Full Loop:

1. Blast radius — few known files, no cross-cutting design.
2. Semantic risk — no auth/billing/protocol/public API shape change.
3. Uncertainty — expected behavior already exact; no open design choices.
4. Verification — a short, concrete verify command exists.
5. Rollback — easy to revert; no multi-step migration.

## Direction (Full Loop)

Full Loop persists `direction.md` only after user confirmation, before Plan
(`confirm-direction`).

## Commands (`workflow.py --worktree <WT>`)

- `start --goal G` — init ledger + run dirs
- `confirm-direction --file PATH` — copy to stable `direction.md` after user OK
- `set-plan --plan PATH` — attach plan (requires confirmed direction)
- `add-task --id T --title T --brief PATH` — todo + loop-memory init
- `accept-stage --id T --stage S --report PATH [...]` — mark + fold + snapshot
- `next --json` — print dispatch contract (paths only; never spawns)
- `show [--json]` — folded ledger state
- `doctor [--json]` — read-only ledger/artifact consistency (exit 1 on FAIL)
- `test [--tests-dir DIR]` — run every `test_*.py` in skill tests/ (or DIR)
- `closeout [--verify-cmd CMD]` — optional pre-checks, then compact (CMD repeatable)
- `fast --kind code|prose --goal G --files F --verify V` — stateless dispatch

Details: `python3 …/workflow.py <cmd> --help`.

## Role → agent

| Role / kind | Agent |
|-------------|-------|
| plan | `code-workflow-planner` |
| plan (if primary unavailable) | `code-workflow-planner-backup` |
| test_write | `code-workflow-test-writer` |
| verify_red / verify_green | `code-workflow-verifier` |
| implement | `code-workflow-implementer` |
| fast code | `code-workflow-implementer` |
| fast prose | `code-workflow-prose-editor` |

Agent files live under `knowledge/agents/` and are linked into `.cursor/agents/`.

## Role boundary

- Main orchestrates only; never writes code, tests, or plans.
- Planner expands the direction document into plan + briefs.
- Execution agents stay protocol-blind; hand paths only (brief / reports /
  snapshots), never paste artifact bodies or this protocol.

## Hard safety

- Dispatch by role-agent name only.
- Plan stage: try `code-workflow-planner` first; if that agent is unavailable,
  dispatch `code-workflow-planner-backup` (same plan/brief scope). Do not substitute
  other roles' agents for plan.
- Never hand-edit `progress.jsonl`; use `workflow.py` / `progress.py`.
- Hand off direction and snapshots by path only; do not auto-spawn.
