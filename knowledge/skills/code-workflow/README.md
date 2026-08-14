# code-workflow

Operator/developer reference for the Full Loop and Fast Lane facade.

## Architecture

`scripts/workflow.py` is a thin facade over `scripts/progress.py` (append-only
ledger) and `loop-memory` (per-todo cognition). It owns **no** separate state
file: folded state comes from `progress show --json`. Dispatch is JSON only;
`next --json` never spawns agents.

## Lifecycle

Full Loop transitions:

1. `start` — init ledger + `.cortex/code-workflow/` run dirs
2. `confirm-direction` — persist confirmed `direction.md`
3. `next --json` — **plan** dispatch (until `set-plan`)
4. `set-plan` — attach plan; marks run plan done
5. `add-task` — todo + loop-memory init
6. Stage loop via `next --json` → agent → `accept-stage`  
   (`test_write` → `verify_red` → `implement` → `verify_green`)
7. `doctor` — optional mid-run consistency check (ledger fold + expected paths)
8. `closeout [--verify-cmd CMD]` — optional lint/fmt/typecheck cmds first, then
   all todos done, loops archived, compact

**Fast Lane** (`fast --kind code|prose`) is stateless: no ledger writes; one
dispatch then done.

## Role routing

| Stage / kind | Agent |
|--------------|-------|
| plan | `code-workflow-planner` |
| plan (if primary unavailable) | `code-workflow-planner-backup` |
| test_write | `code-workflow-test-writer` |
| verify_red / verify_green | `code-workflow-verifier` |
| implement | `code-workflow-implementer` |
| fast code | `code-workflow-implementer` |
| fast prose | `code-workflow-prose-editor` |

## Run layout (`.cortex/code-workflow/`)

| Path | Purpose |
|------|---------|
| `progress.jsonl` | ledger |
| `direction.md` | confirmed direction |
| `plan.md` / `briefs/` | plan outputs |
| `reports/` | stage reports |
| `snapshots/` | loop-memory snapshots |
| `artifacts/<id\|plan\|fast-…>/` | transient evidence |
| `loop-memory/` / `loop-memory-archive/` | cognition SSOT |

## Artifact policy

Source of truth: module constant `ARTIFACT_POLICY` in `workflow.py`. Every
stateful and Fast Lane dispatch appends those strings to `constraints`. Agents
do not embed a duplicated Artifacts section.

## Tests / verification

From repo root (aggregator; also accepts `--tests-dir` for fixtures):

```bash
python3 knowledge/skills/code-workflow/scripts/workflow.py test
```

Modules covered: `test_progress.py`, `test_workflow.py`, `test_agent_contracts.py`,
`test_skill_contracts.py`.
