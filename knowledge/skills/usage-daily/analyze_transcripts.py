#!/usr/bin/env python3
"""Analyze Cursor agent-transcripts for recent model/cost usage.

Read-only: scans transcript jsonl files under a transcripts root, never writes
outside --out, and does not touch Cursor state.vscdb.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

CATEGORIES = ("medeo-dev", "mcap-lane-model-test", "code-workflow", "other")

DEFAULT_TRANSCRIPTS_ROOT = (
    "/Users/wenshiqi/.cursor/projects/"
    "Users-wenshiqi-Documents-agent-cortex/agent-transcripts"
)

_USER_QUERY_RE = re.compile(
    r"</?user_query>", re.IGNORECASE
)
_TIMESTAMP_LINE_RE = re.compile(
    r"^\s*<timestamp>.*?</timestamp>\s*$", re.IGNORECASE | re.MULTILINE
)


def human_bytes(n: int) -> str:
    if n >= 1024 * 1024:
        return f"{n / (1024 * 1024):.2f} MB"
    if n >= 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n} B"


def kb(n: int) -> str:
    return f"{n / 1024:.1f}"


def mb(n: int) -> str:
    return f"{n / (1024 * 1024):.2f}"


def extract_text(obj) -> str:
    if isinstance(obj, str):
        return obj
    if isinstance(obj, list):
        parts = []
        for item in obj:
            if isinstance(item, dict):
                if item.get("type") == "text" and "text" in item:
                    parts.append(str(item["text"]))
                elif "text" in item:
                    parts.append(str(item["text"]))
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(parts)
    if isinstance(obj, dict):
        if "text" in obj:
            return str(obj["text"])
        if "content" in obj:
            return extract_text(obj["content"])
    return ""


def clean_snippet(raw: str, limit: int = 200) -> str:
    text = _TIMESTAMP_LINE_RE.sub("", raw)
    text = _USER_QUERY_RE.sub("", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        return text[:limit]
    return text


def categorize(snippet: str) -> str:
    s = snippet.lower()
    if "medeo-dev" in s or "medeo dev" in s:
        return "medeo-dev"
    if (
        "mcap-lane-model-test" in s
        or "mcap_lane_model_test" in s
        or "grpc-execute" in s
        or "swim lane" in s
    ):
        return "mcap-lane-model-test"
    if (
        "code-workflow" in s
        or "implement green" in s
        or "test write" in s
        or "verify red" in s
        or "verify green" in s
        or "plan 阶段" in s
        or "fast lane" in s
    ):
        return "code-workflow"
    return "other"


def count_user_turns(path: Path) -> int:
    count = 0
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if obj.get("role") == "user":
                    count += 1
    except OSError:
        return 0
    return count


def first_user_snippet(path: Path) -> str:
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if obj.get("role") != "user":
                    continue
                msg = obj.get("message", obj)
                raw = extract_text(msg.get("content") if isinstance(msg, dict) else msg)
                if not raw and isinstance(msg, dict):
                    raw = extract_text(msg)
                return clean_snippet(raw, 200)
    except OSError:
        return ""
    return ""


def analyze_session(session_dir: Path, cutoff_ts: float) -> dict | None:
    sid = session_dir.name
    main_path = session_dir / f"{sid}.jsonl"
    if not main_path.is_file():
        return None
    try:
        st = main_path.stat()
    except OSError:
        return None
    if st.st_mtime < cutoff_ts:
        return None

    main_bytes = st.st_size
    user_turns = count_user_turns(main_path)
    subagents = []
    cat_bytes = {c: 0 for c in CATEGORIES}
    cat_counts = {c: 0 for c in CATEGORIES}
    sub_dir = session_dir / "subagents"
    if sub_dir.is_dir():
        for sub_path in sorted(sub_dir.glob("*.jsonl")):
            try:
                sub_st = sub_path.stat()
            except OSError:
                continue
            snippet = first_user_snippet(sub_path)
            category = categorize(snippet)
            entry = {
                "id": sub_path.stem,
                "size": sub_st.st_size,
                "category": category,
                "snippet": snippet,
            }
            subagents.append(entry)
            cat_bytes[category] += sub_st.st_size
            cat_counts[category] += 1

    sub_total = sum(s["size"] for s in subagents)
    return {
        "session": sid,
        "mtime": st.st_mtime,
        "mtime_iso": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc)
        .astimezone()
        .strftime("%Y-%m-%d %H:%M"),
        "main_bytes": main_bytes,
        "user_turns": user_turns,
        "subagents": subagents,
        "sub_count": len(subagents),
        "sub_bytes": sub_total,
        "total_bytes": main_bytes + sub_total,
        "category_bytes": cat_bytes,
        "category_counts": cat_counts,
    }


def scan(transcripts_root: Path, hours: float) -> list[dict]:
    now = datetime.now(tz=timezone.utc).timestamp()
    cutoff = now - hours * 3600
    sessions = []
    for child in sorted(transcripts_root.iterdir()):
        if not child.is_dir():
            continue
        result = analyze_session(child, cutoff)
        if result is not None:
            sessions.append(result)
    return sessions


def build_totals(sessions: list[dict]) -> dict:
    totals = {
        "session_count": len(sessions),
        "subagent_count": 0,
        "main_bytes": 0,
        "sub_bytes": 0,
        "total_bytes": 0,
        "category_counts": {c: 0 for c in CATEGORIES},
        "category_bytes": {c: 0 for c in CATEGORIES},
    }
    for s in sessions:
        totals["subagent_count"] += s["sub_count"]
        totals["main_bytes"] += s["main_bytes"]
        totals["sub_bytes"] += s["sub_bytes"]
        totals["total_bytes"] += s["total_bytes"]
        for c in CATEGORIES:
            totals["category_counts"][c] += s["category_counts"][c]
            totals["category_bytes"][c] += s["category_bytes"][c]
    return totals


def top_sessions(sessions: list[dict], n: int = 10) -> list[dict]:
    return sorted(sessions, key=lambda s: s["total_bytes"], reverse=True)[:n]


def top_subagents(sessions: list[dict], n: int = 10) -> list[dict]:
    rows = []
    for s in sessions:
        for sub in s["subagents"]:
            rows.append(
                {
                    "size": sub["size"],
                    "session": s["session"],
                    "category": sub["category"],
                    "snippet": sub["snippet"],
                    "id": sub["id"],
                }
            )
    rows.sort(key=lambda r: r["size"], reverse=True)
    return rows[:n]


def render_markdown(
    generated_at: str,
    hours: float,
    sessions: list[dict],
    totals: dict,
    tops: list[dict],
    top_subs: list[dict],
) -> str:
    lines = [
        "# agent-cortex usage report",
        "",
        f"- generated-at: {generated_at}",
        f"- window: last {hours:g}h",
        "",
    ]
    if not sessions:
        lines.extend(
            [
                "No sessions in window",
                "",
                "Generated by knowledge/skills/usage-daily/analyze_transcripts.py",
                "",
            ]
        )
        return "\n".join(lines)

    lines.extend(
        [
            "## Summary",
            "",
            f"- sessions: {totals['session_count']}",
            f"- total subagents: {totals['subagent_count']}",
            f"- total transcript: {human_bytes(totals['total_bytes'])}",
            f"- main-thread: {human_bytes(totals['main_bytes'])}",
            "",
            "Per category:",
            "",
        ]
    )
    for c in CATEGORIES:
        lines.append(
            f"- {c}: {totals['category_counts'][c]} subagents, "
            f"{human_bytes(totals['category_bytes'][c])}"
        )
    lines.extend(
        [
            "",
            "## Top sessions",
            "",
            "| rank | session | mtime | main_KB | sub_count | total_MB | medeo | mcap | codewf | other |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for i, s in enumerate(tops, 1):
        cb = s["category_bytes"]
        lines.append(
            "| {rank} | {sid} | {mtime} | {main} | {subs} | {total} | {medeo} | {mcap} | {cw} | {other} |".format(
                rank=i,
                sid=s["session"][:8],
                mtime=s["mtime_iso"],
                main=kb(s["main_bytes"]),
                subs=s["sub_count"],
                total=mb(s["total_bytes"]),
                medeo=kb(cb["medeo-dev"]),
                mcap=kb(cb["mcap-lane-model-test"]),
                cw=kb(cb["code-workflow"]),
                other=kb(cb["other"]),
            )
        )
    lines.extend(
        [
            "",
            "## Top subagents",
            "",
            "| rank | size_KB | session | category | snippet |",
            "| --- | ---: | --- | --- | --- |",
        ]
    )
    for i, r in enumerate(top_subs, 1):
        snip = r["snippet"][:60].replace("|", "/")
        lines.append(
            f"| {i} | {kb(r['size'])} | {r['session'][:8]} | {r['category']} | {snip} |"
        )
    lines.extend(
        [
            "",
            "## Model consumption notes",
            "",
            "Cost centers: medeo-dev + main-orchestrator (gpt-5.6-sol-medium) and "
            "code-workflow (kimi-k3-max + cursor-grok-4.5-high). Subagent count is "
            "the primary lever — fewer/shorter spawn prompts cut spend fastest.",
            "",
            "Generated by knowledge/skills/usage-daily/analyze_transcripts.py",
            "",
        ]
    )
    return "\n".join(lines)


def build_json_payload(
    generated_at: str,
    hours: float,
    sessions: list[dict],
    totals: dict,
    tops: list[dict],
    top_subs: list[dict],
) -> dict:
    return {
        "generated_at": generated_at,
        "window_hours": hours,
        "totals": totals,
        "sessions": [
            {
                "session": s["session"],
                "mtime": s["mtime"],
                "mtime_iso": s["mtime_iso"],
                "main_bytes": s["main_bytes"],
                "user_turns": s["user_turns"],
                "sub_count": s["sub_count"],
                "sub_bytes": s["sub_bytes"],
                "total_bytes": s["total_bytes"],
                "category_bytes": s["category_bytes"],
                "category_counts": s["category_counts"],
                "subagents": s["subagents"],
            }
            for s in sessions
        ],
        "top_sessions": [
            {
                "session": s["session"],
                "mtime_iso": s["mtime_iso"],
                "main_bytes": s["main_bytes"],
                "sub_count": s["sub_count"],
                "total_bytes": s["total_bytes"],
                "category_bytes": s["category_bytes"],
            }
            for s in tops
        ],
        "top_subagents": top_subs,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Analyze Cursor agent-transcripts for recent usage/cost."
    )
    parser.add_argument("--hours", type=float, default=24.0)
    parser.add_argument(
        "--transcripts-root",
        type=Path,
        default=Path(DEFAULT_TRANSCRIPTS_ROOT),
    )
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    root = args.transcripts_root.expanduser()
    if not root.is_dir():
        print(f"error: transcripts-root not found: {root}", file=sys.stderr)
        return 1

    sessions = scan(root, args.hours)
    totals = build_totals(sessions)
    tops = top_sessions(sessions)
    top_subs = top_subagents(sessions)
    generated_at = datetime.now(tz=timezone.utc).astimezone().isoformat(timespec="seconds")

    if args.json:
        payload = build_json_payload(
            generated_at, args.hours, sessions, totals, tops, top_subs
        )
        text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    else:
        text = render_markdown(
            generated_at, args.hours, sessions, totals, tops, top_subs
        )

    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
