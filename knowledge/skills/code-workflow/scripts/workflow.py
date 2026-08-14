#!/usr/bin/env python3
"""code-workflow facade — state machine over progress.py + loop-memory.py.

No own state file. Validates transitions from the folded progress ledger and
folds cognition into loop-memory. Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

TODO_STAGES = ("test_write", "verify_red", "implement", "verify_green")
RUN_DIRS = (
    "briefs",
    "reports",
    "snapshots",
    "loop-memory",
    "loop-memory-archive",
    "artifacts",
)

STAGE_ROLE = {
    "test_write": "code-workflow-test-writer",
    "verify_red": "code-workflow-verifier",
    "implement": "code-workflow-implementer",
    "verify_green": "code-workflow-verifier",
}

STAGE_SCOPE = {
    "test_write": ["tests-only"],
    "verify_red": ["read-only"],
    "implement": ["task-scope"],
    "verify_green": ["read-only"],
}

STAGE_GOAL = {
    "test_write": "Write failing tests that lock the task requirements",
    "verify_red": "Run the new tests and confirm they fail for the right reason",
    "implement": "Implement the minimal change that makes the tests pass",
    "verify_green": "Re-run the tests and confirm they pass",
}

STAGE_CONSTRAINTS = {
    "test_write": [
        "write tests only; do not run them; no production code",
    ],
    "verify_red": [
        "read-only; run tests; do not edit production or test code",
    ],
    "implement": [
        "edit only within the allowed task scope; do not weaken tests",
    ],
    "verify_green": [
        "read-only; run tests; do not edit production or test code",
    ],
}

ARTIFACT_POLICY = [
    "write required outputs only to caller-given paths",
    "put transient evidence only in artifact_dir",
    "never create repo-root artifacts/",
    "never persist secrets",
]

PLAN_CONSTRAINTS = [
    "write only plan and briefs; no source, tests, or other docs",
]

# After accepting stage S, snapshot through this cognition stage (skip after verify_green).
STAGE_SNAPSHOT_THROUGH = {
    "test_write": "WT",
    "verify_red": "VER",
    "implement": "IMPL",
}

# Cognition stage used when folding accept-stage into loop-memory.
STAGE_COGNITION = {
    "test_write": "WT",
    "verify_red": "VER",
    "implement": "IMPL",
    "verify_green": "VER",
}

# Snapshot file tag expected as snapshot_in for the *next* stage after prior accept.
SNAPSHOT_IN_FOR_STAGE = {
    "test_write": None,
    "verify_red": "WT",
    "implement": "VER",
    "verify_green": "IMPL",
}

ARTIFACT_KEYS = {
    "test_write": "test_writer_report",
    "verify_red": "red_verification_report",
    "implement": "implement_report",
    "verify_green": "green_verification_report",
}

SCRIPTS_DIR = Path(__file__).resolve().parent
PROGRESS_PY = SCRIPTS_DIR / "progress.py"
LOOP_MEMORY_PY = SCRIPTS_DIR.parent.parent / "loop-memory" / "loop-memory.py"


def fail(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def wt_path(raw: str) -> Path:
    """Absolute worktree path without resolving symlinks (/var vs /private/var)."""
    return Path(os.path.abspath(raw))


def run_dir(worktree: Path) -> Path:
    return worktree / ".cortex" / "code-workflow"


def ledger_path(worktree: Path) -> Path:
    return run_dir(worktree) / "progress.jsonl"


def loop_env(worktree: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["LOOP_MEMORY_HOME"] = str(run_dir(worktree) / "loop-memory")
    env["LOOP_MEMORY_SESSION"] = "default"
    return env


def run_progress(worktree: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, str(PROGRESS_PY), *args, "--worktree", str(worktree)]
    proc = subprocess.run(cmd, capture_output=True, text=True, env=loop_env(worktree))
    if check and proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip() or f"progress.py failed ({proc.returncode})"
        if err.startswith("error:"):
            print(err, file=sys.stderr)
            sys.exit(1)
        fail(err)
    return proc


def run_loop(worktree: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, str(LOOP_MEMORY_PY), *args]
    proc = subprocess.run(cmd, capture_output=True, text=True, env=loop_env(worktree))
    if check and proc.returncode != 0:
        exit_proc_error(proc, "loop-memory.py")
    return proc


def proc_error_text(proc: subprocess.CompletedProcess[str], label: str) -> str:
    return (proc.stderr or proc.stdout or "").strip() or f"{label} failed ({proc.returncode})"


def exit_proc_error(proc: subprocess.CompletedProcess[str], label: str) -> None:
    err = proc_error_text(proc, label)
    if err.startswith("error:"):
        print(err, file=sys.stderr)
        sys.exit(1)
    fail(err)


def compensate_stage_not_done(worktree: Path, todo_id: str, stage: str) -> None:
    """Append-only rollback after cognition/snapshot/archive failure.

    Ledger mark must not permanently stay ahead of loop-memory SSOT: set the
    stage back to pending and overall todo to in_progress so next --json still
    dispatches the same stage (including after verify_green had flipped todo
    status to done).
    """
    run_progress(
        worktree,
        "mark",
        "--id",
        todo_id,
        "--stage",
        stage,
        "--stage-status",
        "pending",
        "--status",
        "in_progress",
    )


def load_state(worktree: Path) -> dict[str, Any]:
    ledger = ledger_path(worktree)
    if not ledger.exists():
        fail(f"ledger missing: {ledger}")
    proc = run_progress(worktree, "show", "--json")
    return json.loads(proc.stdout)


def ack(**extra: Any) -> None:
    print(json.dumps({"ok": True, **extra}, ensure_ascii=False))


def abs_path(p: str | Path) -> str:
    return str(Path(p).resolve())


def goal_slug(goal: str) -> str:
    """Lowercase [a-z0-9-] slug, max 24 chars, for Fast Lane artifact dirs."""
    slug = re.sub(r"[^a-z0-9]+", "-", goal.lower()).strip("-")
    slug = re.sub(r"-+", "-", slug)[:24].rstrip("-")
    return slug or "goal"


def ensure_artifact_dir(path: Path) -> str:
    path.mkdir(parents=True, exist_ok=True)
    return abs_path(path)


def next_pending_stage(todo: dict[str, Any]) -> str | None:
    for stage in TODO_STAGES:
        if todo["stages"].get(stage) in ("pending", "in_progress"):
            return stage
    return None


def find_todo(state: dict[str, Any], todo_id: str) -> dict[str, Any]:
    for todo in state.get("todos") or []:
        if todo.get("id") == todo_id:
            return todo
    fail(f"unknown todo: {todo_id}")
    raise AssertionError("unreachable")


def prior_report_paths(todo: dict[str, Any], up_to_stage: str) -> list[str]:
    paths: list[str] = []
    for stage in TODO_STAGES:
        if stage == up_to_stage:
            break
        key = ARTIFACT_KEYS[stage]
        art = (todo.get("artifacts") or {}).get(key) or ""
        if art:
            paths.append(abs_path(art))
    return paths


def snapshot_path(worktree: Path, todo_id: str, through: str) -> Path:
    return run_dir(worktree) / "snapshots" / f"{todo_id}.{through}.json"


def build_dispatch(
    *,
    worktree: Path,
    state: dict[str, Any],
    todo: dict[str, Any],
    stage: str,
) -> dict[str, Any]:
    role = STAGE_ROLE[stage]
    brief = abs_path(todo.get("brief") or "")
    report = abs_path(run_dir(worktree) / "reports" / f"{todo['id']}.{stage}.md")
    snap_tag = SNAPSHOT_IN_FOR_STAGE[stage]
    snap_in = abs_path(snapshot_path(worktree, todo["id"], snap_tag)) if snap_tag else None
    inputs: list[str] = []
    if brief:
        inputs.append(brief)
    inputs.extend(prior_report_paths(todo, stage))
    if snap_in:
        inputs.append(snap_in)
    artifact_dir = ensure_artifact_dir(
        run_dir(worktree) / "artifacts" / todo["id"]
    )
    return {
        "role": role,
        "goal": STAGE_GOAL[stage],
        "inputs": inputs,
        "constraints": list(STAGE_CONSTRAINTS[stage]) + list(ARTIFACT_POLICY),
        "report_path": report,
        "allowed_edit_scope": list(STAGE_SCOPE[stage]),
        "snapshot_in": snap_in,
        "artifact_dir": artifact_dir,
    }


def build_plan_dispatch(*, worktree: Path, state: dict[str, Any]) -> dict[str, Any]:
    rd = run_dir(worktree)
    direction = abs_path(state.get("direction") or "")
    artifact_dir = ensure_artifact_dir(rd / "artifacts" / "plan")
    return {
        "role": "code-workflow-planner",
        "goal": "Expand the confirmed direction into a plan and per-task briefs",
        "inputs": [direction],
        "outputs": {
            "plan": abs_path(rd / "plan.md"),
            "briefs_dir": abs_path(rd / "briefs"),
        },
        "constraints": list(PLAN_CONSTRAINTS) + list(ARTIFACT_POLICY),
        "report_path": abs_path(rd / "reports" / "plan.md"),
        "allowed_edit_scope": ["plan-docs"],
        "snapshot_in": None,
        "artifact_dir": artifact_dir,
    }


def cmd_start(args: argparse.Namespace) -> None:
    worktree = wt_path(args.worktree)
    rd = run_dir(worktree)
    ledger = ledger_path(worktree)
    if ledger.exists() and ledger.stat().st_size > 0 and not args.force:
        fail(f"ledger already exists: {ledger} (pass --force to re-init)")
    for name in RUN_DIRS:
        (rd / name).mkdir(parents=True, exist_ok=True)
    prog_args = ["init", "--goal", args.goal]
    for c in args.constraint or []:
        prog_args.extend(["--constraint", c])
    if args.force:
        prog_args.append("--force")
    run_progress(worktree, *prog_args)
    ack(ledger=str(ledger))


def cmd_confirm_direction(args: argparse.Namespace) -> None:
    worktree = wt_path(args.worktree)
    state = load_state(worktree)
    if state.get("direction_confirmed"):
        fail("direction already confirmed")
    src = Path(args.file)
    if not src.is_file():
        fail(f"direction file missing: {src}")
    dest = run_dir(worktree) / "direction.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    run_progress(worktree, "set-direction", "--file", str(dest))
    ack(direction=str(dest.resolve()))


def cmd_set_plan(args: argparse.Namespace) -> None:
    worktree = wt_path(args.worktree)
    state = load_state(worktree)
    if not state.get("direction_confirmed"):
        fail("direction not confirmed — run confirm-direction first")
    plan = Path(args.plan)
    if not plan.is_file():
        fail(f"plan file missing: {plan}")
    run_progress(worktree, "set-plan", "--plan", abs_path(plan), "--mark-done")
    ack(plan=abs_path(plan))


def cmd_add_task(args: argparse.Namespace) -> None:
    worktree = wt_path(args.worktree)
    state = load_state(worktree)
    if state.get("run", {}).get("plan") != "done":
        fail("plan not set — run set-plan first")
    brief = Path(args.brief)
    if not brief.is_file():
        fail(f"brief file missing: {brief}")
    brief_abs = abs_path(brief)
    run_progress(
        worktree,
        "add-todo",
        "--id",
        args.id,
        "--title",
        args.title,
        "--brief",
        brief_abs,
    )
    run_loop(
        worktree,
        "init",
        args.id,
        "--repo",
        worktree.name,
        "--worktree",
        str(worktree),
        "--task",
        args.title,
    )
    ack(id=args.id)


def fold_accept_cognition(
    worktree: Path, args: argparse.Namespace, stage: str
) -> subprocess.CompletedProcess[str] | None:
    """Fold stage cognition into loop-memory. Returns failed proc or None."""
    cog = STAGE_COGNITION[stage]
    if stage in ("test_write", "implement"):
        proc = run_loop(
            worktree, "put", args.id, "--stage", cog, "--patch", "{}", check=False
        )
        if proc.returncode != 0:
            return proc
        for decision in args.decision or []:
            proc = run_loop(
                worktree,
                "add-decision",
                args.id,
                "--stage",
                cog,
                "--text",
                decision,
                check=False,
            )
            if proc.returncode != 0:
                return proc
        for fpath in args.file or []:
            proc = run_loop(
                worktree,
                "add-file",
                args.id,
                "--stage",
                cog,
                "--path",
                fpath,
                "--role",
                "code",
                "--symbols",
                "[]",
                check=False,
            )
            if proc.returncode != 0:
                return proc
        return None
    if stage == "verify_red":
        proc = run_loop(
            worktree,
            "set-test",
            args.id,
            "--stage",
            "VER",
            "--red",
            "--passed",
            str(args.red_passed),
            "--failed",
            str(args.red_failed),
            "--reason",
            args.red_reason,
            check=False,
        )
        return None if proc.returncode == 0 else proc
    if stage == "verify_green":
        proc = run_loop(
            worktree,
            "set-verdict",
            args.id,
            "--stage",
            "VER",
            "--verdict",
            args.verdict,
            "--test-passed",
            str(args.passed),
            "--test-failed",
            str(args.failed),
            check=False,
        )
        return None if proc.returncode == 0 else proc
    return None


def persist_accept_snapshot(
    worktree: Path, todo_id: str, stage: str
) -> subprocess.CompletedProcess[str] | None:
    """Snapshot or archive after cognition. Returns failed proc or None."""
    if stage == "verify_green":
        archive_to = run_dir(worktree) / "loop-memory-archive"
        archive_to.mkdir(parents=True, exist_ok=True)
        proc = run_loop(
            worktree, "archive", todo_id, "--to", str(archive_to), check=False
        )
        return None if proc.returncode == 0 else proc
    through = STAGE_SNAPSHOT_THROUGH[stage]
    out = snapshot_path(worktree, todo_id, through)
    out.parent.mkdir(parents=True, exist_ok=True)
    proc = run_loop(
        worktree,
        "snapshot",
        todo_id,
        "--through-stage",
        through,
        "--out",
        str(out),
        check=False,
    )
    return None if proc.returncode == 0 else proc


def cmd_accept_stage(args: argparse.Namespace) -> None:
    worktree = wt_path(args.worktree)
    state = load_state(worktree)
    todo = find_todo(state, args.id)
    stage = args.stage
    if stage not in TODO_STAGES:
        fail(f"invalid stage: {stage}")
    expected = next_pending_stage(todo)
    if expected != stage:
        fail(f"illegal stage order: expected {expected}, got {stage}")
    report = Path(args.report)
    if not report.is_file():
        fail(f"report file missing: {report}")
    report_abs = abs_path(report)

    if stage == "verify_red":
        if args.red_reason is None or args.red_passed is None or args.red_failed is None:
            fail("verify_red requires --red-reason, --red-passed, and --red-failed")
    if stage == "verify_green":
        if args.verdict is None or args.passed is None or args.failed is None:
            fail("verify_green requires --verdict, --passed, and --failed")

    # Ledger mark first (brief order), then cognition + snapshot/archive.
    # Any loop-memory failure compensates via append so the stage is not
    # permanently done and next still targets the same stage.
    run_progress(
        worktree,
        "mark",
        "--id",
        args.id,
        "--stage",
        stage,
        "--artifact",
        report_abs,
    )

    failed = fold_accept_cognition(worktree, args, stage)
    if failed is None:
        failed = persist_accept_snapshot(worktree, args.id, stage)
    if failed is not None:
        compensate_stage_not_done(worktree, args.id, stage)
        exit_proc_error(failed, "loop-memory.py")

    ack(id=args.id, stage=stage)


def cmd_next(args: argparse.Namespace) -> None:
    worktree = wt_path(args.worktree)
    state = load_state(worktree)
    run_block = {
        "goal": state.get("goal", ""),
        "worktree": str(worktree),
        "plan": state.get("plan") or "",
        "direction": state.get("direction") or "",
    }
    if state["direction_confirmed"] and state["run"]["plan"] != "done":
        payload = {
            "done": False,
            "run": run_block,
            "stage": "plan",
            "dispatch": build_plan_dispatch(worktree=worktree, state=state),
        }
        print(json.dumps(payload, ensure_ascii=False))
        return
    for todo in state.get("todos") or []:
        if todo.get("status") in ("done", "skipped"):
            continue
        if todo.get("status") == "blocked":
            fail(f"todo blocked: {todo.get('id')}")
        stage = next_pending_stage(todo)
        if stage is None:
            continue
        payload = {
            "done": False,
            "run": run_block,
            "task": {
                "id": todo["id"],
                "title": todo.get("title") or "",
                "brief": abs_path(todo["brief"]) if todo.get("brief") else "",
            },
            "stage": stage,
            "dispatch": build_dispatch(
                worktree=worktree, state=state, todo=todo, stage=stage
            ),
        }
        print(json.dumps(payload, ensure_ascii=False))
        return
    print(json.dumps({"done": True}, ensure_ascii=False))


def cmd_show(args: argparse.Namespace) -> None:
    worktree = wt_path(args.worktree)
    state = load_state(worktree)
    if args.json:
        print(json.dumps(state, ensure_ascii=False, indent=2))
    else:
        # Reuse progress text rendering via progress show
        proc = run_progress(worktree, "show")
        sys.stdout.write(proc.stdout)


def loop_files_remain(worktree: Path) -> list[Path]:
    home = run_dir(worktree) / "loop-memory"
    if not home.exists():
        return []
    return sorted(
        p for p in home.rglob("*.json") if p.is_file() and p.name != "index.json"
    )


def cmd_closeout(args: argparse.Namespace) -> None:
    worktree = wt_path(args.worktree)
    for cmd_str in args.verify_cmd or []:
        argv = shlex.split(cmd_str)
        if not argv:
            fail(f"empty --verify-cmd: {cmd_str!r}")
        proc = subprocess.run(
            argv,
            cwd=str(worktree),
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            out = (proc.stdout or "") + (proc.stderr or "")
            if out:
                sys.stderr.write(out if out.endswith("\n") else out + "\n")
            fail(f"verify-cmd failed ({proc.returncode}): {cmd_str}")
    state = load_state(worktree)
    todos = state.get("todos") or []
    pending = [t for t in todos if t.get("status") not in ("done", "skipped")]
    if pending:
        fail(f"pending todos remain: {', '.join(t['id'] for t in pending)}")
    remain = loop_files_remain(worktree)
    if remain:
        fail(f"loop-memory files remain: {', '.join(str(p) for p in remain)}")
    run_progress(worktree, "mark-run", "--stage", "closeout", "--status", "done")
    run_progress(worktree, "compact")
    ack()


def default_tests_dir() -> Path:
    return SCRIPTS_DIR.parent / "tests"


def cmd_test(args: argparse.Namespace) -> None:
    tests_dir = Path(args.tests_dir) if args.tests_dir else default_tests_dir()
    if not tests_dir.is_dir():
        fail(f"tests dir missing: {tests_dir}")
    files = sorted(p for p in tests_dir.glob("test_*.py") if p.is_file())
    failed = 0
    for path in files:
        proc = subprocess.run(
            [sys.executable, str(path)],
            capture_output=True,
            text=True,
        )
        status = "PASS" if proc.returncode == 0 else "FAIL"
        print(f"{status} {path.name}")
        if proc.returncode != 0:
            failed += 1
    sys.exit(1 if failed else 0)


def cmd_doctor(args: argparse.Namespace) -> None:
    """Read-only consistency check over ledger + expected artifact paths."""
    worktree = wt_path(args.worktree)
    checks: list[dict[str, Any]] = []

    proc = run_progress(worktree, "show", "--json", check=False)
    if proc.returncode != 0:
        checks.append(
            {
                "status": "FAIL",
                "name": "ledger",
                "detail": proc_error_text(proc, "progress show"),
            }
        )
        _emit_doctor(checks, json_mode=args.json)
        sys.exit(1)

    checks.append(
        {"status": "OK", "name": "ledger", "detail": "progress show --json ok"}
    )
    state = json.loads(proc.stdout)

    if state.get("direction_confirmed"):
        direction = state.get("direction") or str(run_dir(worktree) / "direction.md")
        if Path(direction).is_file():
            checks.append({"status": "OK", "name": "direction", "detail": direction})
        else:
            checks.append(
                {"status": "FAIL", "name": "direction", "detail": f"missing {direction}"}
            )

    if (state.get("run") or {}).get("plan") == "done":
        plan = state.get("plan") or str(run_dir(worktree) / "plan.md")
        if plan and Path(plan).is_file():
            checks.append({"status": "OK", "name": "plan", "detail": plan})
        else:
            checks.append(
                {
                    "status": "FAIL",
                    "name": "plan",
                    "detail": f"missing {plan or '(empty)'}",
                }
            )

    for todo in state.get("todos") or []:
        tid = todo.get("id") or "?"
        brief = todo.get("brief") or ""
        if brief and Path(brief).is_file():
            checks.append({"status": "OK", "name": "brief", "detail": f"{tid} {brief}"})
        else:
            checks.append(
                {
                    "status": "FAIL",
                    "name": "brief",
                    "detail": f"{tid} missing {brief or '(empty)'}",
                }
            )
        if todo.get("status") not in ("done", "skipped"):
            loop_path = run_dir(worktree) / "loop-memory" / "default" / f"{tid}.json"
            if loop_path.is_file():
                checks.append(
                    {"status": "OK", "name": "loop", "detail": f"{tid} {loop_path}"}
                )
            else:
                checks.append(
                    {
                        "status": "FAIL",
                        "name": "loop",
                        "detail": f"{tid} missing {loop_path}",
                    }
                )

    ok = all(c["status"] == "OK" for c in checks)
    _emit_doctor(checks, json_mode=args.json)
    sys.exit(0 if ok else 1)


def _emit_doctor(checks: list[dict[str, Any]], *, json_mode: bool) -> None:
    ok = all(c["status"] == "OK" for c in checks)
    if json_mode:
        print(json.dumps({"checks": checks, "ok": ok}, ensure_ascii=False))
    else:
        for c in checks:
            print(f"{c['status']} {c['name']} {c['detail']}")


def cmd_fast(args: argparse.Namespace) -> None:
    worktree = wt_path(args.worktree)
    kind = args.kind
    role = (
        "code-workflow-implementer"
        if kind == "code"
        else "code-workflow-prose-editor"
    )
    files = [abs_path(f) if Path(f).exists() else f for f in (args.files or [])]
    verify = list(args.verify or [])
    artifact_dir = ensure_artifact_dir(
        run_dir(worktree)
        / "artifacts"
        / f"fast-{goal_slug(args.goal)}-{uuid.uuid4().hex[:8]}"
    )
    dispatch = {
        "role": role,
        "goal": args.goal,
        "inputs": files,
        "constraints": [
            "edit only the listed files",
            ("verify with: " + " && ".join(verify)) if verify else "run the listed verify commands",
        ]
        + list(ARTIFACT_POLICY),
        "report_path": "",
        "allowed_edit_scope": ["task-scope"] if kind == "code" else ["read-only"],
        "snapshot_in": None,
        "artifact_dir": artifact_dir,
    }
    print(
        json.dumps(
            {
                "done": False,
                "run": {
                    "goal": args.goal,
                    "worktree": str(worktree),
                    "plan": "",
                    "direction": "",
                },
                "dispatch": dispatch,
            },
            ensure_ascii=False,
        )
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="workflow.py", description=__doc__)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--worktree", required=True, help="worktree / repo root")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("start", parents=[common], help="init ledger + run dirs")
    sp.add_argument("--goal", required=True)
    sp.add_argument("--constraint", action="append", default=[])
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(func=cmd_start)

    sp = sub.add_parser(
        "confirm-direction", parents=[common], help="confirm direction after user OK"
    )
    sp.add_argument("--file", required=True)
    sp.set_defaults(func=cmd_confirm_direction)

    sp = sub.add_parser("set-plan", parents=[common], help="attach plan (direction required)")
    sp.add_argument("--plan", required=True)
    sp.set_defaults(func=cmd_set_plan)

    sp = sub.add_parser("add-task", parents=[common], help="add todo + init loop-memory")
    sp.add_argument("--id", required=True)
    sp.add_argument("--title", required=True)
    sp.add_argument("--brief", required=True)
    sp.set_defaults(func=cmd_add_task)

    sp = sub.add_parser("accept-stage", parents=[common], help="accept a todo stage")
    sp.add_argument("--id", required=True)
    sp.add_argument("--stage", required=True, choices=TODO_STAGES)
    sp.add_argument("--report", required=True)
    sp.add_argument("--decision", action="append", default=[])
    sp.add_argument("--file", action="append", default=[])
    sp.add_argument("--red-reason", default=None)
    sp.add_argument("--red-passed", type=int, default=None)
    sp.add_argument("--red-failed", type=int, default=None)
    sp.add_argument("--verdict", choices=("GREEN", "RED"), default=None)
    sp.add_argument("--passed", type=int, default=None)
    sp.add_argument("--failed", type=int, default=None)
    sp.set_defaults(func=cmd_accept_stage)

    sp = sub.add_parser("next", parents=[common], help="print next dispatch contract")
    sp.add_argument("--json", action="store_true", required=True)
    sp.set_defaults(func=cmd_next)

    sp = sub.add_parser("show", parents=[common], help="show folded state")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_show)

    sp = sub.add_parser("closeout", parents=[common], help="mark closeout + compact")
    sp.add_argument(
        "--verify-cmd",
        action="append",
        default=[],
        dest="verify_cmd",
        help="run before closeout checks (repeatable; shlex.split, no shell)",
    )
    sp.set_defaults(func=cmd_closeout)

    sp = sub.add_parser(
        "doctor",
        parents=[common],
        help="read-only ledger/artifact consistency check",
    )
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_doctor)

    sp = sub.add_parser(
        "test",
        help="run test_*.py files in skill tests/ (or --tests-dir)",
    )
    sp.add_argument(
        "--tests-dir",
        default=None,
        help="directory of test_*.py files (default: skill tests/)",
    )
    sp.set_defaults(func=cmd_test)

    sp = sub.add_parser("fast", parents=[common], help="stateless fast-lane dispatch")
    sp.add_argument("--kind", required=True, choices=("code", "prose"))
    sp.add_argument("--goal", required=True)
    sp.add_argument("--files", action="append", default=[], dest="files")
    sp.add_argument("--verify", action="append", default=[], dest="verify")
    sp.set_defaults(func=cmd_fast)

    return p


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
