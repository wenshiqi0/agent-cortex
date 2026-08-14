#!/usr/bin/env python3
"""loop-memory — session-scoped per-loop JSON cognition store.

Passive store only. No kickback / status / flow-control fields.

Ops:
  init           create a loop JSON + index entry
  get            print full loop JSON
  put            RFC 7396 merge-patch into stages.<stage>
  add-file       append/update a file entry on a stage
  add-decision   append a decision with timestamp
  set-test       write test_red (--red required)
  set-verdict    write verdict + test_green
  snapshot       meta + stages through a given stage
  list           list loops in the current session
  archive        copy loop out and remove from session
  doctor         read-only index/file consistency checks

Storage:
  $LOOP_MEMORY_HOME or ${TMPDIR:-/tmp}/loop-memory
  $LOOP_MEMORY_SESSION or "default"

No third-party deps — Python stdlib only.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STAGES = ("WT", "IMPL", "VER")
FILE_KEY = {"WT": "files", "IMPL": "files_touched", "VER": "files"}
VERDICTS = ("GREEN", "RED")


def fail(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def validate_component(name: str, value: str) -> str:
    if not value or "/" in value or ".." in value:
        fail(f"invalid {name}: {value!r} (must be a single safe path component)")
    return value


def base_dir() -> Path:
    home = os.environ.get("LOOP_MEMORY_HOME")
    if home:
        return Path(home)
    tmp = os.environ.get("TMPDIR") or "/tmp"
    return Path(tmp) / "loop-memory"


def session_id() -> str:
    return validate_component(
        "LOOP_MEMORY_SESSION", os.environ.get("LOOP_MEMORY_SESSION") or "default"
    )


def session_dir() -> Path:
    return base_dir() / session_id()


def loop_path(loop_id: str) -> Path:
    validate_component("loop_id", loop_id)
    return session_dir() / f"{loop_id}.json"


def index_path() -> Path:
    return session_dir() / "index.json"


def atomic_write_json(path: Path, data: Any, *, indent: int | None = 2) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    text = json.dumps(data, ensure_ascii=False, indent=indent)
    if not text.endswith("\n"):
        text += "\n"
    with tmp.open("w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def load_loop(loop_id: str) -> dict[str, Any]:
    path = loop_path(loop_id)
    if not path.exists():
        fail(f"loop not found: {loop_id}")
    return load_json(path)


def save_loop(data: dict[str, Any]) -> None:
    atomic_write_json(loop_path(data["loop_id"]), data)


def load_index() -> dict[str, Any]:
    path = index_path()
    if not path.exists():
        return {}
    data = load_json(path)
    if isinstance(data, dict) and "loops" in data and isinstance(data["loops"], dict):
        return data["loops"]
    if isinstance(data, dict):
        return data
    return {}


def save_index(loops: dict[str, Any]) -> None:
    atomic_write_json(index_path(), {"loops": loops})


def scan_loop_files() -> list[Path]:
    d = session_dir()
    if not d.exists():
        return []
    return sorted(
        p for p in d.glob("*.json") if p.name != "index.json" and p.is_file()
    )


def rebuild_index() -> dict[str, Any]:
    loops: dict[str, Any] = {}
    for path in scan_loop_files():
        try:
            data = load_json(path)
        except (json.JSONDecodeError, OSError):
            continue
        lid = data.get("loop_id") or path.stem
        loops[lid] = {
            "loop_id": lid,
            "repo": data.get("repo", ""),
            "task": data.get("task", ""),
            "created_at": data.get("created_at", ""),
            "updated_at": data.get("updated_at") or data.get("created_at", ""),
        }
    save_index(loops)
    return loops


def ensure_index() -> dict[str, Any]:
    """Load index; rebuild if missing or stale vs loop files on disk."""
    path = index_path()
    files = scan_loop_files()
    file_ids = {p.stem for p in files}

    if not path.exists():
        return rebuild_index()

    loops = load_index()
    index_ids = set(loops.keys())
    if index_ids != file_ids:
        return rebuild_index()

    # Also rebuild if any indexed loop file is unreadable / gone (belt+suspenders).
    for lid in index_ids:
        if not loop_path(lid).exists():
            return rebuild_index()
    return loops


def bump_index(loop_id: str, data: dict[str, Any]) -> None:
    loops = ensure_index()
    entry = loops.get(loop_id, {})
    entry.update(
        {
            "loop_id": loop_id,
            "repo": data.get("repo", entry.get("repo", "")),
            "task": data.get("task", entry.get("task", "")),
            "created_at": data.get("created_at", entry.get("created_at", "")),
            "updated_at": now_iso(),
        }
    )
    loops[loop_id] = entry
    save_index(loops)


def ensure_stage(data: dict[str, Any], stage: str) -> dict[str, Any]:
    stages = data.setdefault("stages", {})
    if stage not in stages or not isinstance(stages[stage], dict):
        stages[stage] = {}
    return stages[stage]


def touch_stage(data: dict[str, Any], stage: str) -> dict[str, Any]:
    st = ensure_stage(data, stage)
    st["ended_at"] = now_iso()
    return st


def merge_patch(target: Any, patch: Any) -> Any:
    """RFC 7396 JSON Merge Patch."""
    if not isinstance(patch, dict):
        return patch
    if not isinstance(target, dict):
        target = {}
    else:
        target = dict(target)
    for key, value in patch.items():
        if value is None:
            target.pop(key, None)
        elif isinstance(value, dict):
            target[key] = merge_patch(target.get(key), value)
        else:
            target[key] = value
    return target


def present_stages(data: dict[str, Any]) -> list[str]:
    stages = data.get("stages") or {}
    return [s for s in STAGES if s in stages]


def ack(loop_id: str) -> None:
    print(json.dumps({"ok": True, "loop_id": loop_id}, ensure_ascii=False))


def cmd_init(args: argparse.Namespace) -> None:
    loop_id = validate_component("loop_id", args.loop_id)
    path = loop_path(loop_id)
    if path.exists():
        fail(f"loop already exists: {loop_id}")
    ts = now_iso()
    data: dict[str, Any] = {
        "loop_id": loop_id,
        "repo": args.repo,
        "worktree": args.worktree,
        "task": args.task,
        "created_at": ts,
        "stages": {},
    }
    save_loop(data)
    loops = ensure_index()
    loops[loop_id] = {
        "loop_id": loop_id,
        "repo": args.repo,
        "task": args.task,
        "created_at": ts,
        "updated_at": ts,
    }
    save_index(loops)
    ack(loop_id)


def cmd_get(args: argparse.Namespace) -> None:
    data = load_loop(args.loop_id)
    print(json.dumps(data, ensure_ascii=False, indent=2))


def cmd_put(args: argparse.Namespace) -> None:
    try:
        patch = json.loads(args.patch)
    except json.JSONDecodeError as e:
        fail(f"invalid patch JSON: {e}")
    data = load_loop(args.loop_id)
    stage = args.stage
    current = ensure_stage(data, stage)
    data["stages"][stage] = merge_patch(current, patch)
    touch_stage(data, stage)
    save_loop(data)
    bump_index(args.loop_id, data)
    ack(args.loop_id)


def cmd_add_file(args: argparse.Namespace) -> None:
    try:
        symbols = json.loads(args.symbols)
    except json.JSONDecodeError as e:
        fail(f"invalid --symbols JSON: {e}")
    if not isinstance(symbols, list):
        fail("--symbols must be a JSON array")
    if not all(isinstance(s, str) for s in symbols):
        fail("--symbols must be a JSON array of strings")

    data = load_loop(args.loop_id)
    stage = args.stage
    st = touch_stage(data, stage)
    key = FILE_KEY[stage]
    files = st.setdefault(key, [])
    if not isinstance(files, list):
        files = []
        st[key] = files
    entry = {"path": args.path, "role": args.role, "symbols": symbols}
    for i, existing in enumerate(files):
        if isinstance(existing, dict) and existing.get("path") == args.path:
            files[i] = entry
            break
    else:
        files.append(entry)
    save_loop(data)
    bump_index(args.loop_id, data)
    ack(args.loop_id)


def cmd_add_decision(args: argparse.Namespace) -> None:
    data = load_loop(args.loop_id)
    st = touch_stage(data, args.stage)
    decisions = st.setdefault("decisions", [])
    if not isinstance(decisions, list):
        decisions = []
        st["decisions"] = decisions
    decisions.append({"ts": now_iso(), "text": args.text})
    save_loop(data)
    bump_index(args.loop_id, data)
    ack(args.loop_id)


def cmd_set_test(args: argparse.Namespace) -> None:
    data = load_loop(args.loop_id)
    st = touch_stage(data, args.stage)
    st["test_red"] = {
        "passed": int(args.passed),
        "failed": int(args.failed),
        "reason": args.reason,
        "ts": now_iso(),
    }
    save_loop(data)
    bump_index(args.loop_id, data)
    ack(args.loop_id)


def cmd_set_verdict(args: argparse.Namespace) -> None:
    data = load_loop(args.loop_id)
    st = touch_stage(data, args.stage)
    st["verdict"] = args.verdict
    st["test_green"] = {
        "passed": int(args.test_passed),
        "failed": int(args.test_failed),
        "ts": now_iso(),
    }
    save_loop(data)
    bump_index(args.loop_id, data)
    ack(args.loop_id)


def cmd_snapshot(args: argparse.Namespace) -> None:
    data = load_loop(args.loop_id)
    through = args.through_stage
    cutoff = STAGES.index(through)
    filtered_stages: dict[str, Any] = {}
    for i, name in enumerate(STAGES):
        if i > cutoff:
            break
        if name in (data.get("stages") or {}):
            filtered_stages[name] = data["stages"][name]
    snap = {
        "loop_id": data["loop_id"],
        "repo": data["repo"],
        "worktree": data["worktree"],
        "task": data["task"],
        "created_at": data["created_at"],
        "stages": filtered_stages,
    }
    text = json.dumps(snap, ensure_ascii=False, indent=2)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(out.suffix + ".tmp")
        payload = text if text.endswith("\n") else text + "\n"
        with tmp.open("w", encoding="utf-8") as f:
            f.write(payload)
        os.replace(tmp, out)
        # When writing to --out, still print nothing? Brief: writes atomically;
        # omit to print stdout. Tests compare file content to stdout form from
        # a separate invocation without --out. So --out should not need stdout.
        return
    print(text)


def cmd_list(_args: argparse.Namespace) -> None:
    loops = ensure_index()
    entries: list[dict[str, Any]] = []
    for lid, meta in loops.items():
        path = loop_path(lid)
        if not path.exists():
            continue
        try:
            data = load_json(path)
        except (json.JSONDecodeError, OSError):
            continue
        entries.append(
            {
                "loop_id": lid,
                "repo": meta.get("repo", data.get("repo", "")),
                "task": meta.get("task", data.get("task", "")),
                "created_at": meta.get("created_at", data.get("created_at", "")),
                "updated_at": meta.get("updated_at", data.get("created_at", "")),
                "stages": present_stages(data),
            }
        )
    print(json.dumps(entries, ensure_ascii=False, indent=2))


def cmd_archive(args: argparse.Namespace) -> None:
    loop_id = validate_component("loop_id", args.loop_id)
    path = loop_path(loop_id)
    if not path.exists():
        fail(f"loop not found: {loop_id}")
    dest_dir = Path(args.to)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{loop_id}.json"
    shutil.copy2(path, dest)
    path.unlink()
    loops = load_index() if index_path().exists() else {}
    loops.pop(loop_id, None)
    save_index(loops)
    ack(loop_id)


REQUIRED_META = ("loop_id", "repo", "worktree", "task")


def _doctor_check(status: str, name: str, detail: str) -> dict[str, str]:
    return {"status": status, "name": name, "detail": detail}


def run_doctor_checks() -> list[dict[str, str]]:
    """Read-only consistency checks against the active session home."""
    checks: list[dict[str, str]] = []
    d = session_dir()
    idx = index_path()
    indexed_ids: set[str] = set()
    index_readable = True

    if idx.exists():
        try:
            raw = load_json(idx)
        except (json.JSONDecodeError, OSError) as e:
            checks.append(
                _doctor_check("FAIL", "index", f"index.json corrupt: {e}")
            )
            index_readable = False
            raw = None
        if index_readable:
            if (
                isinstance(raw, dict)
                and "loops" in raw
                and isinstance(raw["loops"], dict)
            ):
                loops = raw["loops"]
            elif isinstance(raw, dict):
                loops = raw
            else:
                checks.append(
                    _doctor_check(
                        "FAIL", "index", "index.json must be a JSON object"
                    )
                )
                index_readable = False
                loops = {}
            if index_readable:
                indexed_ids = set(loops.keys())
                checks.append(
                    _doctor_check("OK", "index", "index.json parses")
                )
    else:
        checks.append(_doctor_check("OK", "index", "index.json absent"))

    if index_readable:
        for lid in sorted(indexed_ids):
            path = d / f"{lid}.json"
            if path.is_file():
                checks.append(
                    _doctor_check("OK", "indexed-file", f"{lid}.json present")
                )
            else:
                checks.append(
                    _doctor_check(
                        "FAIL", "indexed-file", f"missing loop file for {lid}"
                    )
                )

    for path in scan_loop_files():
        try:
            data = load_json(path)
        except (json.JSONDecodeError, OSError) as e:
            checks.append(
                _doctor_check("FAIL", "loop-parse", f"{path.name}: {e}")
            )
            continue
        if not isinstance(data, dict):
            checks.append(
                _doctor_check(
                    "FAIL", "loop-meta", f"{path.name}: not a JSON object"
                )
            )
            continue
        missing = [k for k in REQUIRED_META if k not in data]
        if missing:
            checks.append(
                _doctor_check(
                    "FAIL",
                    "loop-meta",
                    f"{path.name}: missing {', '.join(missing)}",
                )
            )
        else:
            checks.append(
                _doctor_check("OK", "loop-meta", f"{path.name} meta ok")
            )

        stages = data.get("stages", {})
        if stages is None:
            stages = {}
        if not isinstance(stages, dict):
            checks.append(
                _doctor_check(
                    "FAIL", "stages", f"{path.name}: stages not an object"
                )
            )
        else:
            bad = [k for k in stages if k not in STAGES]
            if bad:
                checks.append(
                    _doctor_check(
                        "FAIL",
                        "stages",
                        f"{path.name}: invalid stage keys {', '.join(bad)}",
                    )
                )
            else:
                checks.append(
                    _doctor_check("OK", "stages", f"{path.name} stages ok")
                )

        if index_readable and path.stem not in indexed_ids:
            checks.append(
                _doctor_check(
                    "WARN",
                    "orphan",
                    f"{path.name} not in index (reindexable)",
                )
            )

    return checks


def cmd_doctor(args: argparse.Namespace) -> None:
    checks = run_doctor_checks()
    has_fail = any(c["status"] == "FAIL" for c in checks)
    ok = not has_fail
    if args.json:
        print(json.dumps({"checks": checks, "ok": ok}, ensure_ascii=False))
    else:
        for c in checks:
            print(f"{c['status']} {c['name']} {c['detail']}")
    sys.exit(1 if has_fail else 0)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="loop-memory.py", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("init", help="create a loop JSON + index entry")
    sp.add_argument("loop_id")
    sp.add_argument("--repo", required=True)
    sp.add_argument("--worktree", required=True)
    sp.add_argument("--task", required=True)
    sp.set_defaults(func=cmd_init)

    sp = sub.add_parser("get", help="print full loop JSON")
    sp.add_argument("loop_id")
    sp.set_defaults(func=cmd_get)

    sp = sub.add_parser("put", help="RFC 7396 merge-patch into stages.<stage>")
    sp.add_argument("loop_id")
    sp.add_argument("--stage", required=True, choices=STAGES)
    sp.add_argument("--patch", required=True)
    sp.set_defaults(func=cmd_put)

    sp = sub.add_parser("add-file", help="append/update a file entry on a stage")
    sp.add_argument("loop_id")
    sp.add_argument("--stage", required=True, choices=STAGES)
    sp.add_argument("--path", required=True)
    sp.add_argument("--role", required=True)
    sp.add_argument("--symbols", required=True)
    sp.set_defaults(func=cmd_add_file)

    sp = sub.add_parser("add-decision", help="append a decision with timestamp")
    sp.add_argument("loop_id")
    sp.add_argument("--stage", required=True, choices=STAGES)
    sp.add_argument("--text", required=True)
    sp.set_defaults(func=cmd_add_decision)

    sp = sub.add_parser("set-test", help="write test_red (--red required)")
    sp.add_argument("loop_id")
    sp.add_argument("--stage", required=True, choices=STAGES)
    sp.add_argument("--red", action="store_true", required=True)
    sp.add_argument("--passed", required=True, type=int)
    sp.add_argument("--failed", required=True, type=int)
    sp.add_argument("--reason", required=True)
    sp.set_defaults(func=cmd_set_test)

    sp = sub.add_parser("set-verdict", help="write verdict + test_green")
    sp.add_argument("loop_id")
    sp.add_argument("--stage", required=True, choices=STAGES)
    sp.add_argument("--verdict", required=True, choices=VERDICTS)
    sp.add_argument("--test-passed", required=True, type=int)
    sp.add_argument("--test-failed", required=True, type=int)
    sp.set_defaults(func=cmd_set_verdict)

    sp = sub.add_parser("snapshot", help="meta + stages through a given stage")
    sp.add_argument("loop_id")
    sp.add_argument("--through-stage", required=True, choices=STAGES)
    sp.add_argument("--out", default=None)
    sp.set_defaults(func=cmd_snapshot)

    sp = sub.add_parser("list", help="list loops in the current session")
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("archive", help="copy loop out and remove from session")
    sp.add_argument("loop_id")
    sp.add_argument("--to", required=True)
    sp.set_defaults(func=cmd_archive)

    sp = sub.add_parser(
        "doctor", help="read-only index/file consistency checks"
    )
    sp.add_argument(
        "--json",
        action="store_true",
        help="emit JSON {checks, ok} instead of text lines",
    )
    sp.set_defaults(func=cmd_doctor)

    return p


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
