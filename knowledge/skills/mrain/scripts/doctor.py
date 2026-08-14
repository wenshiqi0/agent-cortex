#!/usr/bin/env python3
"""mrain availability / environment doctor (stdlib only).

Usage:
  python3 knowledge/skills/mrain/scripts/doctor.py [--json] [--smoke]

Default mode is read-only (never creates $HOME/.mrain).
--smoke writes one memory row when a provider API key is present.
Never prints secret values.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

PROVIDER_KEYS = (
    "MRAIN_ANTHROPIC_API_KEY",
    "MRAIN_OPENAI_API_KEY",
)

HELP_TIMEOUT_SEC = 15
SMOKE_TIMEOUT_SEC = 120
SMOKE_TEXT = "mrain doctor smoke"

INSTALL_HINT = (
    "install mrain onto PATH (e.g. $HOME/.local/bin/mrain or /usr/local/bin/mrain)"
)


def _has_provider_key() -> bool:
    return any(os.environ.get(k) for k in PROVIDER_KEYS)


def _is_writable_dir(path: Path) -> bool:
    return path.is_dir() and os.access(path, os.W_OK)


def check_binary() -> dict[str, Any]:
    path = shutil.which("mrain")
    if not path:
        return {
            "status": "FAIL",
            "name": "binary",
            "detail": f"mrain not found on PATH; {INSTALL_HINT}",
        }
    return {"status": "OK", "name": "binary", "detail": path}


def check_help() -> dict[str, Any]:
    try:
        proc = subprocess.run(
            ["mrain", "--help"],
            capture_output=True,
            text=True,
            timeout=HELP_TIMEOUT_SEC,
        )
    except FileNotFoundError:
        return {
            "status": "FAIL",
            "name": "help",
            "detail": f"mrain not found; {INSTALL_HINT}",
        }
    except subprocess.TimeoutExpired:
        return {
            "status": "FAIL",
            "name": "help",
            "detail": f"mrain --help timed out after {HELP_TIMEOUT_SEC}s",
        }
    if proc.returncode != 0:
        return {
            "status": "FAIL",
            "name": "help",
            "detail": f"mrain --help exited {proc.returncode}",
        }
    return {"status": "OK", "name": "help", "detail": "mrain --help ok"}


def check_provider() -> dict[str, Any]:
    if _has_provider_key():
        present = [k for k in PROVIDER_KEYS if os.environ.get(k)]
        # Name keys only — never print values.
        return {
            "status": "OK",
            "name": "provider",
            "detail": f"set: {', '.join(present)}",
        }
    return {
        "status": "FAIL",
        "name": "provider",
        "detail": (
            "need MRAIN_ANTHROPIC_API_KEY or MRAIN_OPENAI_API_KEY "
            "(values not printed)"
        ),
    }


def check_storage() -> dict[str, Any]:
    home = Path(os.environ.get("HOME") or Path.home())
    mrain_dir = home / ".mrain"
    if mrain_dir.exists():
        if _is_writable_dir(mrain_dir):
            return {
                "status": "OK",
                "name": "storage",
                "detail": f"{mrain_dir} writable",
            }
        return {
            "status": "FAIL",
            "name": "storage",
            "detail": f"{mrain_dir} exists but is not writable",
        }
    parent = home
    if _is_writable_dir(parent):
        return {
            "status": "OK",
            "name": "storage",
            "detail": f"{mrain_dir} will-be-created (parent writable)",
        }
    return {
        "status": "WARN",
        "name": "storage",
        "detail": f"{mrain_dir} missing and parent not writable",
    }


def check_smoke() -> dict[str, Any]:
    if not _has_provider_key():
        return {
            "status": "SKIP",
            "name": "smoke",
            "detail": "no provider API key; smoke not run",
        }
    try:
        mem = subprocess.run(
            [
                "mrain",
                "memory",
                "memorize",
                "--source-kind",
                "agent",
                "--source-model",
                "doctor",
                "--text",
                SMOKE_TEXT,
            ],
            capture_output=True,
            text=True,
            timeout=SMOKE_TIMEOUT_SEC,
        )
    except FileNotFoundError:
        return {
            "status": "FAIL",
            "name": "smoke",
            "detail": f"mrain not found; {INSTALL_HINT}",
        }
    except subprocess.TimeoutExpired:
        return {
            "status": "FAIL",
            "name": "smoke",
            "detail": f"memorize timed out after {SMOKE_TIMEOUT_SEC}s",
        }
    if mem.returncode != 0:
        return {
            "status": "FAIL",
            "name": "smoke",
            "detail": f"memorize exited {mem.returncode}",
        }
    try:
        recall = subprocess.run(
            ["mrain", "memory", "recall", "--query", SMOKE_TEXT],
            capture_output=True,
            text=True,
            timeout=SMOKE_TIMEOUT_SEC,
        )
    except subprocess.TimeoutExpired:
        return {
            "status": "FAIL",
            "name": "smoke",
            "detail": f"recall timed out after {SMOKE_TIMEOUT_SEC}s",
        }
    if recall.returncode != 0:
        return {
            "status": "FAIL",
            "name": "smoke",
            "detail": f"recall exited {recall.returncode}",
        }
    return {
        "status": "OK",
        "name": "smoke",
        "detail": "memorize+recall ok",
    }


def _format_line(check: dict[str, Any]) -> str:
    return f"{check['status']} {check['name']} {check['detail']}"


def _exit_code(checks: list[dict[str, Any]]) -> int:
    for c in checks:
        if c["name"] == "binary" and c["status"] == "FAIL":
            return 2
    if any(c["status"] == "FAIL" for c in checks):
        return 1
    return 0


def run(*, smoke: bool) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    binary = check_binary()
    checks.append(binary)
    if binary["status"] == "FAIL":
        # Help/smoke need the binary; stop after FAIL binary (exit 2).
        return checks

    checks.append(check_help())
    checks.append(check_provider())
    checks.append(check_storage())
    if smoke:
        checks.append(check_smoke())
    return checks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="mrain doctor (read-only by default)")
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit JSON {checks, ok} instead of text lines",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="gated write smoke (memorize+recall); skips if no provider key",
    )
    args = parser.parse_args(argv)

    checks = run(smoke=args.smoke)
    code = _exit_code(checks)
    ok = code == 0

    if args.json:
        print(json.dumps({"checks": checks, "ok": ok}, ensure_ascii=False))
    else:
        for c in checks:
            print(_format_line(c))
    return code


if __name__ == "__main__":
    sys.exit(main())
