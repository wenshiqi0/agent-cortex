#!/usr/bin/env python3
"""code-workflow progress ledger — append-only JSONL + fold to current state.

Ledger default: <worktree-or-root>/.cortex/code-workflow/progress.jsonl
Archive (compact): same dir history.jsonl

Ops:
  init           create ledger with goal / worktree / constraints
  set-direction  attach confirmed direction path (direction + direction_confirmed)
  set-plan       attach plan path after Plan stage
  add-todo       append a todo (id, title, optional brief)
  mark           mark todo overall status and/or a stage (+ optional artifact)
  mark-run       mark run-level stage (preflight|plan|closeout)
  show           fold events → current state (text or --json)
  next           print next incomplete todo+stage for orchestrator
  compact        archive done/skipped todos to history.jsonl; rewrite progress
                 as a minimal snapshot (active todos only). Explicit — mark does
                 not auto-compact; run after finishing todos / at closeout.

Examples:
  python3 progress.py compact --worktree "$WT"
  python3 progress.py compact --ledger /path/to/progress.jsonl

No third-party deps — Python stdlib only.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TODO_STAGES = ("test_write", "verify_red", "implement", "verify_green")
RUN_STAGES = ("preflight", "plan", "closeout")
STAGE_STATUSES = ("pending", "in_progress", "done", "blocked", "skipped")
TODO_STATUSES = ("pending", "in_progress", "done", "blocked", "skipped")
ARTIFACT_KEYS = {
    "test_write": "test_writer_report",
    "verify_red": "red_verification_report",
    "implement": "implement_report",
    "verify_green": "green_verification_report",
}


def fail(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def default_ledger(worktree: str | None) -> Path:
    base = Path(worktree) if worktree else Path.cwd()
    return base / ".cortex" / "code-workflow" / "progress.jsonl"


def default_history(ledger: Path) -> Path:
    """Archive path beside the progress ledger: history.jsonl."""
    return ledger.parent / "history.jsonl"


def ensure_cortex_gitignore(ledger: Path) -> None:
    """Self-ignore .cortex/ so host repos without a root entry stay clean."""
    cortex_dir = None
    for parent in [ledger.parent, *ledger.parents]:
        if parent.name == ".cortex":
            cortex_dir = parent
            break
    if cortex_dir is None:
        return
    gi = cortex_dir / ".gitignore"
    if gi.exists():
        return
    cortex_dir.mkdir(parents=True, exist_ok=True)
    gi.write_text("*\n!.gitignore\n", encoding="utf-8")


def resolve_ledger(path: str | None, worktree: str | None) -> Path:
    if path:
        return Path(path)
    return default_ledger(worktree)


def append_event(ledger: Path, event: dict[str, Any]) -> None:
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ensure_cortex_gitignore(ledger)
    event = {"ts": now_iso(), **event}
    with ledger.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")


def read_events(ledger: Path) -> list[dict[str, Any]]:
    if not ledger.exists():
        return []
    events: list[dict[str, Any]] = []
    with ledger.open(encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError as e:
                fail(f"{ledger}:{lineno}: invalid JSON: {e}")
    return events


def rewrite_ledger(ledger: Path, events: list[dict[str, Any]]) -> None:
    """Atomically replace ledger contents (temp + os.replace)."""
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ensure_cortex_gitignore(ledger)
    tmp = ledger.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
    os.replace(tmp, ledger)


def empty_todo(todo_id: str, title: str, brief: str = "") -> dict[str, Any]:
    return {
        "id": todo_id,
        "title": title,
        "brief": brief,
        "status": "pending",
        "stages": {s: "pending" for s in TODO_STAGES},
        "artifacts": {ARTIFACT_KEYS[s]: "" for s in TODO_STAGES},
        "notes": [],
    }


def fold(events: list[dict[str, Any]]) -> dict[str, Any]:
    state: dict[str, Any] = {
        "goal": "",
        "worktree": "",
        "plan": "",
        "direction": "",
        "direction_confirmed": False,
        "constraints": [],
        "run": {s: "pending" for s in RUN_STAGES},
        "todos": {},  # id -> todo
        "todo_order": [],
    }
    for ev in events:
        op = ev.get("op")
        if op == "init":
            state["goal"] = ev.get("goal", "")
            state["worktree"] = ev.get("worktree", "")
            state["plan"] = ev.get("plan", "") or state["plan"]
            state["constraints"] = list(ev.get("constraints") or [])
            if "run" in ev and isinstance(ev["run"], dict):
                for k, v in ev["run"].items():
                    if k in state["run"]:
                        state["run"][k] = v
        elif op == "snapshot":
            # Minimal rewrite from compact: replace run metadata + todos wholesale.
            state["goal"] = ev.get("goal", "")
            state["worktree"] = ev.get("worktree", "")
            state["plan"] = ev.get("plan", "")
            state["direction"] = ev.get("direction", "") or ""
            state["direction_confirmed"] = bool(ev.get("direction_confirmed", False))
            state["constraints"] = list(ev.get("constraints") or [])
            state["run"] = {s: "pending" for s in RUN_STAGES}
            if "run" in ev and isinstance(ev["run"], dict):
                for k, v in ev["run"].items():
                    if k in state["run"]:
                        state["run"][k] = v
            state["todos"] = {}
            state["todo_order"] = []
            for todo_src in ev.get("todos") or []:
                if not isinstance(todo_src, dict):
                    continue
                tid = todo_src.get("id")
                if not tid:
                    continue
                state["todos"][tid] = copy.deepcopy(todo_src)
                state["todo_order"].append(tid)
        elif op == "set-direction":
            state["direction"] = ev.get("direction", "") or ""
            state["direction_confirmed"] = bool(ev.get("direction_confirmed", True))
        elif op == "set-plan":
            state["plan"] = ev.get("plan", "")
        elif op == "add-todo":
            tid = ev.get("id")
            if not tid:
                continue
            if tid in state["todos"]:
                # idempotent re-add: refresh title/brief if provided
                todo = state["todos"][tid]
                if ev.get("title"):
                    todo["title"] = ev["title"]
                if "brief" in ev:
                    todo["brief"] = ev.get("brief") or ""
                continue
            todo = empty_todo(tid, ev.get("title") or tid, ev.get("brief") or "")
            if ev.get("status") in TODO_STATUSES:
                todo["status"] = ev["status"]
            state["todos"][tid] = todo
            state["todo_order"].append(tid)
        elif op == "mark":
            tid = ev.get("id")
            if not tid or tid not in state["todos"]:
                continue
            todo = state["todos"][tid]
            if ev.get("status") in TODO_STATUSES:
                todo["status"] = ev["status"]
            stage = ev.get("stage")
            stage_status = ev.get("stage_status")
            if stage in TODO_STAGES and stage_status in STAGE_STATUSES:
                todo["stages"][stage] = stage_status
                # auto overall status
                if todo["status"] == "pending" and stage_status == "in_progress":
                    todo["status"] = "in_progress"
                if stage_status == "blocked":
                    todo["status"] = "blocked"
                if all(todo["stages"][s] in ("done", "skipped") for s in TODO_STAGES):
                    todo["status"] = "done"
            artifact = ev.get("artifact")
            if stage in ARTIFACT_KEYS and artifact:
                todo["artifacts"][ARTIFACT_KEYS[stage]] = artifact
            note = ev.get("note")
            if note:
                todo["notes"].append({"ts": ev.get("ts", ""), "text": note})
        elif op == "mark-run":
            stage = ev.get("stage")
            status = ev.get("status")
            if stage in RUN_STAGES and status in STAGE_STATUSES:
                state["run"][stage] = status
        elif op == "note":
            # freeform; attach to last touched todo if id given, else ignore in fold
            tid = ev.get("id")
            text = ev.get("text")
            if tid and tid in state["todos"] and text:
                state["todos"][tid]["notes"].append(
                    {"ts": ev.get("ts", ""), "text": text}
                )
    return state


def state_as_list(state: dict[str, Any]) -> dict[str, Any]:
    todos = [state["todos"][tid] for tid in state["todo_order"] if tid in state["todos"]]
    return {
        "goal": state["goal"],
        "worktree": state["worktree"],
        "plan": state["plan"],
        "direction": state.get("direction", ""),
        "direction_confirmed": bool(state.get("direction_confirmed", False)),
        "constraints": state["constraints"],
        "run": state["run"],
        "todos": todos,
    }


def find_next(state: dict[str, Any]) -> dict[str, Any] | None:
    for tid in state["todo_order"]:
        todo = state["todos"][tid]
        if todo["status"] in ("done", "skipped"):
            continue
        if todo["status"] == "blocked":
            return {"id": tid, "title": todo["title"], "status": "blocked", "stage": None}
        for stage in TODO_STAGES:
            st = todo["stages"][stage]
            if st in ("pending", "in_progress"):
                return {
                    "id": tid,
                    "title": todo["title"],
                    "status": todo["status"],
                    "stage": stage,
                    "stage_status": st,
                    "brief": todo.get("brief") or "",
                }
    return None


def cmd_init(args: argparse.Namespace) -> None:
    ledger = resolve_ledger(args.ledger, args.worktree)
    if ledger.exists() and ledger.stat().st_size > 0 and not args.force:
        fail(f"ledger already exists: {ledger} (pass --force to append new init)")
    constraints = list(args.constraint or [])
    append_event(
        ledger,
        {
            "op": "init",
            "goal": args.goal,
            "worktree": args.worktree or "",
            "plan": args.plan or "",
            "constraints": constraints,
            "run": {"preflight": "done", "plan": "pending", "closeout": "pending"},
        },
    )
    print(json.dumps({"ok": True, "ledger": str(ledger)}, ensure_ascii=False))


def cmd_set_direction(args: argparse.Namespace) -> None:
    ledger = resolve_ledger(args.ledger, args.worktree)
    if not ledger.exists():
        fail(f"ledger missing: {ledger}")
    path = Path(args.file)
    if not path.is_file():
        fail(f"direction file missing: {path}")
    direction = str(path.resolve())
    append_event(
        ledger,
        {
            "op": "set-direction",
            "direction": direction,
            "direction_confirmed": True,
        },
    )
    print(json.dumps({"ok": True, "direction": direction}, ensure_ascii=False))


def cmd_set_plan(args: argparse.Namespace) -> None:
    ledger = resolve_ledger(args.ledger, args.worktree)
    if not ledger.exists():
        fail(f"ledger missing: {ledger}")
    append_event(ledger, {"op": "set-plan", "plan": args.plan})
    if args.mark_done:
        append_event(ledger, {"op": "mark-run", "stage": "plan", "status": "done"})
    print(json.dumps({"ok": True, "plan": args.plan}, ensure_ascii=False))


def cmd_add_todo(args: argparse.Namespace) -> None:
    ledger = resolve_ledger(args.ledger, args.worktree)
    if not ledger.exists():
        fail(f"ledger missing: {ledger} — run init first")
    events = read_events(ledger)
    state = fold(events)
    if args.id in state["todos"] and not args.force:
        fail(f"todo already exists: {args.id} (pass --force to refresh title/brief)")
    append_event(
        ledger,
        {
            "op": "add-todo",
            "id": args.id,
            "title": args.title,
            "brief": args.brief or "",
        },
    )
    print(json.dumps({"ok": True, "id": args.id}, ensure_ascii=False))


def cmd_mark(args: argparse.Namespace) -> None:
    ledger = resolve_ledger(args.ledger, args.worktree)
    if not ledger.exists():
        fail(f"ledger missing: {ledger}")
    events = read_events(ledger)
    state = fold(events)
    if args.id not in state["todos"]:
        fail(f"unknown todo: {args.id}")
    if not args.status and not args.stage:
        fail("need --status and/or --stage")
    if args.stage and not args.stage_status and not args.status:
        # default: marking a stage means stage done
        args.stage_status = "done"
    if args.stage and args.stage not in TODO_STAGES:
        fail(f"invalid stage: {args.stage}; want one of {', '.join(TODO_STAGES)}")
    if args.stage_status and args.stage_status not in STAGE_STATUSES:
        fail(f"invalid stage_status: {args.stage_status}")
    if args.status and args.status not in TODO_STATUSES:
        fail(f"invalid status: {args.status}")
    event: dict[str, Any] = {"op": "mark", "id": args.id}
    if args.status:
        event["status"] = args.status
    if args.stage:
        event["stage"] = args.stage
        event["stage_status"] = args.stage_status or "done"
    if args.artifact:
        event["artifact"] = args.artifact
    if args.note:
        event["note"] = args.note
    append_event(ledger, event)
    print(json.dumps({"ok": True, **{k: event[k] for k in event if k != "op"}}, ensure_ascii=False))


def cmd_mark_run(args: argparse.Namespace) -> None:
    ledger = resolve_ledger(args.ledger, args.worktree)
    if not ledger.exists():
        fail(f"ledger missing: {ledger}")
    if args.stage not in RUN_STAGES:
        fail(f"invalid run stage: {args.stage}; want one of {', '.join(RUN_STAGES)}")
    if args.status not in STAGE_STATUSES:
        fail(f"invalid status: {args.status}")
    append_event(
        ledger,
        {"op": "mark-run", "stage": args.stage, "status": args.status},
    )
    print(json.dumps({"ok": True, "stage": args.stage, "status": args.status}, ensure_ascii=False))


def render_text(view: dict[str, Any]) -> str:
    lines = [
        f"goal: {view['goal']}",
        f"worktree: {view['worktree']}",
        f"plan: {view['plan'] or '(none)'}",
    ]
    if view["constraints"]:
        lines.append("constraints:")
        for c in view["constraints"]:
            lines.append(f"  - {c}")
    run = view["run"]
    lines.append(
        "run: "
        + " | ".join(f"{k}={run[k]}" for k in RUN_STAGES)
    )
    lines.append("todos:")
    if not view["todos"]:
        lines.append("  (none)")
    for t in view["todos"]:
        stages = " ".join(f"{s}:{t['stages'][s]}" for s in TODO_STAGES)
        lines.append(f"  [{t['status']}] {t['id']}: {t['title']}")
        if t.get("brief"):
            lines.append(f"    brief: {t['brief']}")
        lines.append(f"    stages: {stages}")
        arts = [f"{k}={v}" for k, v in t["artifacts"].items() if v]
        if arts:
            lines.append(f"    artifacts: {'; '.join(arts)}")
    nxt = find_next(fold_from_view(view))
    if nxt:
        if nxt.get("status") == "blocked":
            lines.append(f"next: {nxt['id']} BLOCKED")
        else:
            lines.append(
                f"next: {nxt['id']} / {nxt['stage']} ({nxt.get('stage_status', 'pending')})"
            )
    else:
        lines.append("next: (all done)")
    return "\n".join(lines)


def fold_from_view(view: dict[str, Any]) -> dict[str, Any]:
    """Rebuild internal fold shape from show-view (for next hint)."""
    state = {
        "goal": view["goal"],
        "worktree": view["worktree"],
        "plan": view["plan"],
        "constraints": view["constraints"],
        "run": view["run"],
        "todos": {},
        "todo_order": [],
    }
    for t in view["todos"]:
        state["todos"][t["id"]] = t
        state["todo_order"].append(t["id"])
    return state


def cmd_show(args: argparse.Namespace) -> None:
    ledger = resolve_ledger(args.ledger, args.worktree)
    if not ledger.exists():
        fail(f"ledger missing: {ledger}")
    view = state_as_list(fold(read_events(ledger)))
    if args.json:
        print(json.dumps(view, ensure_ascii=False, indent=2))
    else:
        print(render_text(view))


def cmd_next(args: argparse.Namespace) -> None:
    ledger = resolve_ledger(args.ledger, args.worktree)
    if not ledger.exists():
        fail(f"ledger missing: {ledger}")
    nxt = find_next(fold(read_events(ledger)))
    if nxt is None:
        print(json.dumps({"done": True}, ensure_ascii=False))
        return
    print(json.dumps({"done": False, **nxt}, ensure_ascii=False))


def cmd_compact(args: argparse.Namespace) -> None:
    """Archive completed todos to history.jsonl; rewrite progress as snapshot.

    Explicit only — mark never auto-compacts. Orchestrator should run after
    finishing todos / at closeout.
    """
    ledger = resolve_ledger(args.ledger, args.worktree)
    if not ledger.exists():
        fail(f"ledger missing: {ledger}")
    history = default_history(ledger)
    events = read_events(ledger)
    events_before = len(events)
    state = fold(events)

    active: list[dict[str, Any]] = []
    completed: list[dict[str, Any]] = []
    for tid in state["todo_order"]:
        todo = state["todos"][tid]
        if todo["status"] in ("done", "skipped"):
            completed.append(copy.deepcopy(todo))
        else:
            active.append(copy.deepcopy(todo))

    if completed:
        archive = {
            "op": "archive",
            "reason": "compact",
            "goal": state["goal"],
            "worktree": state["worktree"],
            "plan": state["plan"],
            "run": copy.deepcopy(state["run"]),
            "todos": completed,
            "events_archived": events_before,
        }
        append_event(history, archive)

    snapshot = {
        "ts": now_iso(),
        "op": "snapshot",
        "goal": state["goal"],
        "worktree": state["worktree"],
        "plan": state["plan"],
        "direction": state.get("direction", ""),
        "direction_confirmed": bool(state.get("direction_confirmed", False)),
        "constraints": list(state["constraints"]),
        "run": copy.deepcopy(state["run"]),
        "todos": active,
    }
    rewrite_ledger(ledger, [snapshot])

    print(
        json.dumps(
            {
                "ok": True,
                "progress": str(ledger),
                "history": str(history),
                "archived_todos": len(completed),
                "active_todos": len(active),
                "events_before": events_before,
                "events_after": 1,
            },
            ensure_ascii=False,
        )
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="progress.py", description=__doc__)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--ledger",
        help="path to progress.jsonl (default: <worktree>/.cortex/code-workflow/progress.jsonl)",
    )
    common.add_argument(
        "--worktree",
        help="worktree/root used to resolve default ledger path",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("init", parents=[common], help="create ledger")
    sp.add_argument("--goal", required=True)
    sp.add_argument("--plan", default="")
    sp.add_argument("--constraint", action="append", default=[])
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(func=cmd_init)

    sp = sub.add_parser(
        "set-direction",
        parents=[common],
        help="attach confirmed direction path",
    )
    sp.add_argument("--file", required=True, help="path to direction.md")
    sp.set_defaults(func=cmd_set_direction)

    sp = sub.add_parser("set-plan", parents=[common], help="attach plan path")
    sp.add_argument("--plan", required=True)
    sp.add_argument("--mark-done", action="store_true", help="also mark run.plan=done")
    sp.set_defaults(func=cmd_set_plan)

    sp = sub.add_parser("add-todo", parents=[common], help="append a todo")
    sp.add_argument("--id", required=True)
    sp.add_argument("--title", required=True)
    sp.add_argument("--brief", default="")
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(func=cmd_add_todo)

    sp = sub.add_parser("mark", parents=[common], help="mark todo / stage status")
    sp.add_argument("--id", required=True)
    sp.add_argument("--status", choices=TODO_STATUSES)
    sp.add_argument("--stage", choices=TODO_STAGES)
    sp.add_argument("--stage-status", choices=STAGE_STATUSES)
    sp.add_argument("--artifact", default="")
    sp.add_argument("--note", default="")
    sp.set_defaults(func=cmd_mark)

    sp = sub.add_parser("mark-run", parents=[common], help="mark run-level stage")
    sp.add_argument("--stage", required=True, choices=RUN_STAGES)
    sp.add_argument("--status", required=True, choices=STAGE_STATUSES)
    sp.set_defaults(func=cmd_mark_run)

    sp = sub.add_parser("show", parents=[common], help="print folded state")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_show)

    sp = sub.add_parser("next", parents=[common], help="next incomplete todo+stage")
    sp.set_defaults(func=cmd_next)

    sp = sub.add_parser(
        "compact",
        parents=[common],
        help="archive done/skipped todos; rewrite progress as active snapshot",
    )
    sp.set_defaults(func=cmd_compact)

    return p


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    # init needs worktree on args even when only --ledger given
    if args.cmd == "init" and not getattr(args, "worktree", None):
        # allow --ledger-only init; worktree field may be empty
        pass
    args.func(args)


if __name__ == "__main__":
    main()
