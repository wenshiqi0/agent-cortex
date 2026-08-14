---
name: code-workflow
description: >-
  Use when developing agent-cortex itself or any repositories/ subproject —
  features, bug fixes, scripts, skill mechanization, or when the user asks for
  code-workflow / a multi-model plan-test-implement loop with subagents.
---

# Code Workflow

Orchestrator-only. Main never writes code/tests/plans. Execution agents are
protocol-blind and receive file paths only. Facade: `scripts/workflow.py`.

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
- `closeout` — all todos done, loops archived, compact
- `fast --kind code|prose --goal G --files F --verify V` — stateless dispatch

Details: `python3 …/workflow.py <cmd> --help`.

## Role → model (primary / fallback)

| Role / kind | primary (`model`) | fallback (`fallback_models`) |
|-------------|-------------------|------------------------------|
| plan | `kimi-k3-max` | `[]` |
| test_writer | `kimi-k3-max` | `["cursor-grok-4.5-high"]` |
| verify_red | `kimi-k3-max` | `[]` |
| implement | `kimi-k3-max` | `["cursor-grok-4.5-high"]` |
| verify_green | `kimi-k3-max` | `[]` |
| fast_coder code | `kimi-k3-max` | `["cursor-grok-4.5-high"]` |
| fast_coder prose | `kimi-k3-max` | `[]` |

Code-writing roles: K3 primary, Grok fallback when K3 unavailable. Verify /
plan / prose: K3 only.

## Role boundary

- Main orchestrates only; never writes code, tests, or plans.
- Plan expands `direction.md` into plan + briefs.
- Execution agents stay protocol-blind; hand paths only (brief / reports /
  snapshots), never paste artifact bodies or this protocol.

## Hard safety

- Never omit `model` or `fallback_models` on dispatch.
- Never substitute models outside the emitted candidate list.
- Never hand-edit `progress.jsonl`; use `workflow.py` / `progress.py`.
- Hand off direction and snapshots by path only; do not auto-spawn.
