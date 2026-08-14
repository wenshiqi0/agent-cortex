#!/usr/bin/env python3
"""Repo-level builtin skill audit (stdlib only).

Usage:
  python3 scripts/skill-audit.py [--json]

Discovers directories under knowledge/skills/ that contain SKILL.md (sorted).
External skills/ is never scanned. Read-only and non-interactive.

Exit 1 on any FAIL; WARN never affects the exit code.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

CHECK_FRONTMATTER = "frontmatter"
CHECK_LINES = "lines"
CHECK_PATHS = "paths"
CHECK_CORTEX = "cortex"
CHECK_CLI = "cli"
CHECK_SCRIPTS = "scripts"
CHECK_TESTS = "tests"

SKILL_LINE_CAP = 120
HELP_TIMEOUT_SEC = 30

TASK_RUNNER_PREFIXES = (("bun", "run"), ("npm", "run"))
TASK_RUNNERS = frozenset({"pnpm", "yarn", "make", "just"})
INTERPRETERS = frozenset({"python3", "python", "bun", "node", "sh", "bash"})
REPO_SCRIPT_PATH_RE = re.compile(r"^(?:scripts|knowledge)/.+\.(?:py|sh|js)$")

# Path tokens: extension form (boundary-safe so .jsonl ≠ .js), or scripts/…
PATH_EXT_RE = re.compile(r"[\w][\w./-]*\.(?:py|sh|js|md)(?![\w])")
SCRIPTS_PREFIX_RE = re.compile(r"scripts/[\w][\w./-]*")
CORTEX_CMD_RE = re.compile(r"scripts/cortex\s+(\S+)")
CORTEX_CMD_NAME_RE = re.compile(r"^[a-z][\w-]*$")
CASE_LABEL_RE = re.compile(r"case\s+'([^']+)':")
FENCE_RE = re.compile(r"```(?:[^\n`]*)\n(.*?)```", re.DOTALL)
PYTHON_SCRIPT_CMD_RE = re.compile(
    r"python3[^\S\n]+(\S+\.py)[^\S\n]+([A-Za-z_][\w-]*)"
)
FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.DOTALL)


def _clean_cmd_token(raw: str) -> str:
    return raw.strip(".,;:)\"'`")


def _is_scripts_path_token(token: str) -> bool:
    """Accept scripts/cortex or scripts/… with a known file extension."""
    if token == "scripts/cortex" or token.startswith("scripts/cortex/"):
        return True
    return bool(re.search(r"\.(?:py|sh|js|md)$", token))


def repo_root() -> Path:
    """Audit root is process cwd so fixture tests can isolate a mini-repo."""
    return Path.cwd().resolve()


def discover_skills(root: Path) -> list[Path]:
    base = root / "knowledge" / "skills"
    if not base.is_dir():
        return []
    skills: list[Path] = []
    for child in sorted(base.iterdir(), key=lambda p: p.name):
        if child.is_dir() and (child / "SKILL.md").is_file():
            skills.append(child)
    return skills


def _word_at(text: str, start: int, end: int) -> str:
    ls = start
    while ls > 0 and not text[ls - 1].isspace() and text[ls - 1] not in "`\"'":
        ls -= 1
    re_ = end
    while re_ < len(text) and not text[re_].isspace() and text[re_] not in "`\"'":
        re_ += 1
    return text[ls:re_]


def _should_skip_token(text: str, start: int, end: int, token: str) -> bool:
    if "://" in token:
        return True
    if token.startswith("$"):
        return True
    if any(ch in token for ch in "<>*…"):
        return True
    if start > 0 and text[start - 1] in "$/":
        return True
    word = _word_at(text, start, end)
    if "://" in word or word.startswith("$"):
        return True
    return False


def extract_path_tokens(text: str) -> list[str]:
    """Extract referenced local path tokens (order-stable, unique)."""
    found: list[str] = []
    seen: set[str] = set()

    def add(token: str) -> None:
        token = token.rstrip(".,;:)")
        if not token or token in seen:
            return
        seen.add(token)
        found.append(token)

    for m in SCRIPTS_PREFIX_RE.finditer(text):
        tok = m.group(0).rstrip(".,;:)")
        if _should_skip_token(text, m.start(), m.end(), tok):
            continue
        if not _is_scripts_path_token(tok):
            continue
        add(tok)

    for m in PATH_EXT_RE.finditer(text):
        tok = m.group(0)
        if _should_skip_token(text, m.start(), m.end(), tok):
            continue
        # Prefer scripts/ + knowledge/ refs and bare tool filenames.
        # Skip example paths like src/auth.py or tmp/usage.md.
        if "/" in tok and not (
            tok.startswith("scripts/") or tok.startswith("knowledge/")
        ):
            continue
        # Bare *.md is usually prose (direction.md, README.md); only enforce
        # when path-qualified (knowledge/… or scripts/…).
        if "/" not in tok and tok.endswith(".md"):
            continue
        add(tok)

    return found


def resolve_path_token(token: str, skill_dir: Path, root: Path) -> Path | None:
    """Skill-dir first, then repo root; bare names also try scripts/."""
    candidates = [
        skill_dir / token,
        root / token,
    ]
    if "/" not in token:
        candidates.extend(
            [
                skill_dir / "scripts" / token,
                root / "scripts" / token,
            ]
        )
    for cand in candidates:
        if cand.exists():
            return cand
    return None


def parse_frontmatter(text: str) -> dict[str, str]:
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}
    block = m.group(1)
    data: dict[str, str] = {}
    lines = block.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#"):
            i += 1
            continue
        if ":" not in line:
            i += 1
            continue
        key, _, raw = line.partition(":")
        key = key.strip()
        raw = raw.strip()
        if raw in (">", ">-", "|", "|-"):
            # Folded/literal block: gather indented continuation lines.
            chunks: list[str] = []
            i += 1
            while i < len(lines):
                cont = lines[i]
                if cont.startswith(" ") or cont.startswith("\t"):
                    chunks.append(cont.strip())
                    i += 1
                    continue
                if cont.strip() == "":
                    chunks.append("")
                    i += 1
                    continue
                break
            data[key] = " ".join(c for c in chunks if c).strip()
            continue
        if (raw.startswith('"') and raw.endswith('"')) or (
            raw.startswith("'") and raw.endswith("'")
        ):
            data[key] = raw[1:-1]
        else:
            data[key] = raw
        i += 1
    return data


def check_frontmatter(skill_dir: Path, text: str) -> dict[str, Any]:
    fm = parse_frontmatter(text)
    name = fm.get("name", "")
    desc = fm.get("description", "")
    expected = skill_dir.name
    if name != expected:
        return {
            "status": "FAIL",
            "name": CHECK_FRONTMATTER,
            "detail": f"name {name!r} != directory {expected!r}",
        }
    if not desc.strip():
        return {
            "status": "FAIL",
            "name": CHECK_FRONTMATTER,
            "detail": "description missing or empty",
        }
    return {
        "status": "OK",
        "name": CHECK_FRONTMATTER,
        "detail": f"name={name}",
    }


def check_lines(text: str) -> dict[str, Any]:
    n = len(text.splitlines())
    if n > SKILL_LINE_CAP:
        return {
            "status": "FAIL",
            "name": CHECK_LINES,
            "detail": f"SKILL.md is {n} lines; cap is {SKILL_LINE_CAP}",
        }
    return {
        "status": "OK",
        "name": CHECK_LINES,
        "detail": f"{n} lines",
    }


def check_paths(skill_dir: Path, root: Path, text: str) -> dict[str, Any]:
    tokens = extract_path_tokens(text)
    missing: list[str] = []
    checked = 0
    for tok in tokens:
        # Bare names that only exist via scripts/ fallback are still OK.
        # Require existence for scripts/ and knowledge/ tokens always;
        # bare filenames also must resolve (with scripts/ fallback).
        if "/" in tok and not (
            tok.startswith("scripts/") or tok.startswith("knowledge/")
        ):
            continue
        checked += 1
        if resolve_path_token(tok, skill_dir, root) is None:
            missing.append(tok)
    if missing:
        return {
            "status": "FAIL",
            "name": CHECK_PATHS,
            "detail": "missing: " + ", ".join(missing),
        }
    return {
        "status": "OK",
        "name": CHECK_PATHS,
        "detail": f"checked {checked} path token(s)",
    }


def load_cortex_commands(root: Path) -> set[str] | None:
    cli = root / "scripts" / "cli.js"
    if not cli.is_file():
        return None
    return set(CASE_LABEL_RE.findall(cli.read_text(encoding="utf-8")))


def check_cortex(text: str, commands: set[str] | None) -> dict[str, Any]:
    refs: list[str] = []
    for raw in CORTEX_CMD_RE.findall(text):
        cmd = _clean_cmd_token(raw)
        # Prose like "scripts/cortex CLI" is not a subcommand reference.
        if not CORTEX_CMD_NAME_RE.match(cmd):
            continue
        if any(ch in cmd for ch in "<>*…"):
            continue
        refs.append(cmd)
    if not refs:
        return {
            "status": "OK",
            "name": CHECK_CORTEX,
            "detail": "no scripts/cortex references",
        }
    if commands is None:
        return {
            "status": "FAIL",
            "name": CHECK_CORTEX,
            "detail": "scripts/cli.js missing; cannot validate cortex commands",
        }
    unknown = sorted({cmd for cmd in refs if cmd not in commands})
    if unknown:
        return {
            "status": "FAIL",
            "name": CHECK_CORTEX,
            "detail": "unknown command(s): " + ", ".join(unknown),
        }
    return {
        "status": "OK",
        "name": CHECK_CORTEX,
        "detail": f"validated {len(refs)} reference(s)",
    }


def _skill_local_py_scripts(
    skill_dir: Path, root: Path, text: str
) -> dict[str, Path]:
    """Map referenced script tokens -> absolute paths under the skill dir."""
    out: dict[str, Path] = {}
    for tok in extract_path_tokens(text):
        if not tok.endswith(".py"):
            continue
        resolved = resolve_path_token(tok, skill_dir, root)
        if resolved is None:
            continue
        try:
            resolved.relative_to(skill_dir)
        except ValueError:
            continue
        out[tok] = resolved
        out[resolved.name] = resolved
        # Also key by skill-relative posix path
        rel = resolved.relative_to(skill_dir).as_posix()
        out[rel] = resolved
        out[f"scripts/{resolved.name}"] = resolved
    return out


def check_cli(skill_dir: Path, root: Path, text: str) -> dict[str, Any]:
    local_scripts = _skill_local_py_scripts(skill_dir, root, text)
    if not local_scripts:
        return {
            "status": "OK",
            "name": CHECK_CLI,
            "detail": "no skill-local *.py references",
        }

    # Documented subcommands live in fenced command blocks.
    blocks = FENCE_RE.findall(text)
    body = "\n".join(blocks) if blocks else ""
    pairs: list[tuple[Path, str]] = []
    seen: set[tuple[str, str]] = set()
    for m in PYTHON_SCRIPT_CMD_RE.finditer(body):
        script_tok, cmd = m.group(1), m.group(2)
        resolved = local_scripts.get(script_tok)
        if resolved is None:
            # Try resolving the token normally, then require skill-local.
            cand = resolve_path_token(script_tok, skill_dir, root)
            if cand is None:
                continue
            try:
                cand.relative_to(skill_dir)
            except ValueError:
                continue
            resolved = cand
        key = (str(resolved), cmd)
        if key in seen:
            continue
        seen.add(key)
        pairs.append((resolved, cmd))

    if not pairs:
        return {
            "status": "OK",
            "name": CHECK_CLI,
            "detail": "no documented <script> <cmd> tokens in command blocks",
        }

    failures: list[str] = []
    for script, cmd in pairs:
        try:
            proc = subprocess.run(
                [sys.executable, str(script), cmd, "--help"],
                capture_output=True,
                text=True,
                timeout=HELP_TIMEOUT_SEC,
                cwd=str(root),
            )
        except subprocess.TimeoutExpired:
            failures.append(f"{script.name} {cmd} (--help timed out)")
            continue
        if proc.returncode != 0:
            failures.append(f"{script.name} {cmd} (exit {proc.returncode})")

    if failures:
        return {
            "status": "FAIL",
            "name": CHECK_CLI,
            "detail": "help failed: " + ", ".join(failures),
        }
    return {
        "status": "OK",
        "name": CHECK_CLI,
        "detail": f"validated {len(pairs)} subcommand(s)",
    }


def _skill_ships_scripts(skill_dir: Path) -> bool:
    if any(skill_dir.glob("*.py")):
        return True
    scripts = skill_dir / "scripts"
    if scripts.is_dir() and any(scripts.glob("*.py")):
        return True
    return False


def _is_command_line(line: str) -> bool:
    s = line.strip()
    if not s or s.startswith("#"):
        return False
    if any(ch in s for ch in "<>*…"):
        return False
    first = s.split(None, 1)[0]
    if first.endswith("/"):
        return False
    if first in ("export", "set"):
        return False
    return True


def _logical_fence_lines(body: str) -> list[str]:
    """Join shell line-continuations (trailing \\) into single logical lines."""
    logical: list[str] = []
    buf: list[str] = []
    for raw in body.splitlines():
        stripped = raw.rstrip()
        if stripped.endswith("\\"):
            buf.append(stripped[:-1].rstrip())
            continue
        if buf:
            buf.append(stripped.strip())
            logical.append(" ".join(part for part in buf if part))
            buf = []
        else:
            logical.append(raw)
    if buf:
        logical.append(" ".join(part for part in buf if part))
    return logical


def _fenced_command_lines(text: str) -> list[str]:
    found: list[str] = []
    for body in FENCE_RE.findall(text):
        for raw in _logical_fence_lines(body):
            if _is_command_line(raw):
                found.append(raw.strip())
    return found


def _is_repo_relative_script_path(token: str) -> bool:
    return bool(REPO_SCRIPT_PATH_RE.match(token))


def _next_non_flag_token(tokens: list[str], start: int) -> str | None:
    for tok in tokens[start:]:
        if tok.startswith("-"):
            continue
        return tok
    return None


def _is_mechanized_command(line: str, skill_dir: Path, root: Path) -> bool:
    tokens = line.split()
    if not tokens:
        return False
    if len(tokens) >= 2 and (tokens[0], tokens[1]) in TASK_RUNNER_PREFIXES:
        return True
    if tokens[0] in TASK_RUNNERS:
        return True
    first = tokens[0]
    if first == "scripts/cortex" or first.startswith("scripts/cortex/"):
        return True
    if first in INTERPRETERS:
        nxt = _next_non_flag_token(tokens, 1)
        if (
            nxt is not None
            and _is_repo_relative_script_path(nxt)
            and resolve_path_token(nxt, skill_dir, root) is not None
        ):
            return True
        return False
    if (
        _is_repo_relative_script_path(first)
        and resolve_path_token(first, skill_dir, root) is not None
    ):
        return True
    return False


def check_scripts(skill_dir: Path, root: Path, text: str) -> dict[str, Any]:
    if _skill_ships_scripts(skill_dir):
        return {
            "status": "OK",
            "name": CHECK_SCRIPTS,
            "detail": "co-located scripts present",
        }
    commands = _fenced_command_lines(text)
    if not commands:
        return {
            "status": "OK",
            "name": CHECK_SCRIPTS,
            "detail": "no command blocks",
        }
    offenders = [
        line
        for line in commands
        if not _is_mechanized_command(line, skill_dir, root)
    ]
    if not offenders:
        return {
            "status": "OK",
            "name": CHECK_SCRIPTS,
            "detail": "all command lines mechanized",
        }
    shown = offenders[:3]
    return {
        "status": "FAIL",
        "name": CHECK_SCRIPTS,
        "detail": "unmechanized: " + "; ".join(shown),
    }


def _skill_has_tests(skill_dir: Path) -> bool:
    if any(skill_dir.glob("test_*.py")):
        return True
    tests = skill_dir / "tests"
    if tests.is_dir() and any(tests.glob("test_*.py")):
        return True
    return False


def check_tests(skill_dir: Path) -> dict[str, Any]:
    if not _skill_ships_scripts(skill_dir):
        return {
            "status": "OK",
            "name": CHECK_TESTS,
            "detail": "no co-located *.py scripts",
        }
    if not _skill_has_tests(skill_dir):
        return {
            "status": "FAIL",
            "name": CHECK_TESTS,
            "detail": "scripts present but no test_*.py or tests/test_*.py",
        }
    return {
        "status": "OK",
        "name": CHECK_TESTS,
        "detail": "co-located tests present",
    }


def audit_skill(
    skill_dir: Path, root: Path, cortex_cmds: set[str] | None
) -> dict[str, Any]:
    text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    checks = [
        check_frontmatter(skill_dir, text),
        check_lines(text),
        check_paths(skill_dir, root, text),
        check_cortex(text, cortex_cmds),
        check_cli(skill_dir, root, text),
        check_scripts(skill_dir, root, text),
        check_tests(skill_dir),
    ]
    rel = skill_dir.relative_to(root).as_posix()
    return {
        "name": skill_dir.name,
        "path": rel,
        "checks": checks,
    }


def format_text_lines(skills: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for skill in skills:
        for check in skill["checks"]:
            lines.append(
                f"{check['status']} {skill['name']} {check['name']} {check['detail']}"
            )
    return "\n".join(lines) + ("\n" if lines else "")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit builtin knowledge/skills")
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit JSON report instead of text lines",
    )
    args = parser.parse_args(argv)

    root = repo_root()
    cortex_cmds = load_cortex_commands(root)
    skills = [audit_skill(d, root, cortex_cmds) for d in discover_skills(root)]
    ok = all(
        check["status"] != "FAIL" for skill in skills for check in skill["checks"]
    )
    payload = {"skills": skills, "ok": ok}

    if args.json:
        sys.stdout.write(json.dumps(payload, indent=2, sort_keys=False) + "\n")
    else:
        sys.stdout.write(format_text_lines(skills))

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
