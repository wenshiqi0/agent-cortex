---
name: loop-memory
description: "Use when sequential subagents work the same task across loop passes and need shared per-loop context — a passive cognition store so each agent avoids repeated repo exploration. Stores files, decisions, RED test results, and verdicts per loop; the orchestrator writes each snapshot via `snapshot --out <path>` and hands the next stage the snapshot file path as an ordinary input — snapshot JSON is never pasted into a prompt."
---

# loop-memory

Passive per-loop JSON cognition store. Storage at
`$TMPDIR/loop-memory/<session_id>/<loop_id>.json` (env overrides
`LOOP_MEMORY_HOME` / `LOOP_MEMORY_SESSION`, session default `default`).
Stdlib-only script:

```text
knowledge/skills/loop-memory/loop-memory.py
```

## Commands

```sh
python3 knowledge/skills/loop-memory/loop-memory.py init D1 --repo myrepo --worktree /abs/wt --task "add login"
python3 knowledge/skills/loop-memory/loop-memory.py get D1
python3 knowledge/skills/loop-memory/loop-memory.py put D1 --stage WT --patch '{"notes":"auth uses JWT"}'
python3 knowledge/skills/loop-memory/loop-memory.py add-file D1 --stage IMPL --path src/auth.py --role edit --symbols login,logout
python3 knowledge/skills/loop-memory/loop-memory.py add-decision D1 --stage IMPL --text "chose JWT over sessions"
python3 knowledge/skills/loop-memory/loop-memory.py set-test D1 --stage VER --red --passed 3 --failed 1 --reason "login test fails"
python3 knowledge/skills/loop-memory/loop-memory.py set-verdict D1 --stage VER --verdict GREEN --test-passed 4 --test-failed 0
python3 knowledge/skills/loop-memory/loop-memory.py snapshot D1 --through-stage IMPL --out /tmp/d1.json
python3 knowledge/skills/loop-memory/loop-memory.py list
python3 knowledge/skills/loop-memory/loop-memory.py archive D1 --to /tmp/loop-archive
```

## Semantics

- `put --patch` is an RFC 7396 merge patch into `stages.<stage>`; `--stage` is `WT | IMPL | VER`.
- `add-file` keys are `files` (WT/VER) vs `files_touched` (IMPL), deduped by path.
- `snapshot --through-stage X --out <path>` writes cumulative state up to and
  including X to a file. The orchestrator hands that snapshot **file path** to
  the next stage as an ordinary input — snapshot JSON is never pasted into a
  prompt.
- `archive` moves a finished loop out of the active session dir.
- Writes are atomic and last-writer-wins.

## Orchestrator contract

- The orchestrator runs every CLI call: `init` at task start, fold cognition
  (`put` / `add-file` / `add-decision` / `set-test` / `set-verdict`) after
  each accepted stage, `snapshot --out <path>` before the next stage, and
  `archive --to <dir>` when the loop is done.
- The orchestrator hands the next stage only the snapshot **file path** as an
  ordinary input — the snapshot JSON itself is never pasted into a prompt.
- Execution subagents never run this CLI and never see a loop id or the
  `WT | IMPL | VER` stage names.
- Subagents MUST NOT call any `mrain` subcommand.
- Subagents MUST NOT read other loops' context (unless the orchestrator explicitly authorizes).

## What the store does NOT contain

No kickback, status, or flow-control fields — it is a passive cognition
store; flow control stays with the caller.
