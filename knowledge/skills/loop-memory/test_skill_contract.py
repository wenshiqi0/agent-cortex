#!/usr/bin/env python3
"""Thin contract tests for loop-memory SKILL.md vs CLI surface.

Mirrors code-workflow/tests/test_skill_contracts.py: existence, line cap,
required keywords, forbidden model-slug tokens, plus CLI --help parity for
every `loop-memory.py <cmd>` token in the SKILL Commands block.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent
SKILL = SKILL_DIR / "SKILL.md"
SCRIPT = SKILL_DIR / "loop-memory.py"

REQUIRED = (
    "loop-memory.py",
    "snapshot",
    "archive",
    "doctor",
)

FORBIDDEN = (
    "model",
    "fallback",
    "kimi-k3-max",
    "cursor-grok-4.5-high",
    "composer-2.5-fast",
)

_CMD_BLOCK_RE = re.compile(r"```sh\n(.*?)```", re.DOTALL)
_CMD_TOKEN_RE = re.compile(r"loop-memory\.py\s+(\S+)")


def _skill_command_tokens(text: str) -> list[str]:
    """Unique subcommands listed in the first ```sh``` Commands block."""
    match = _CMD_BLOCK_RE.search(text)
    if not match:
        return []
    seen: list[str] = []
    for token in _CMD_TOKEN_RE.findall(match.group(1)):
        if token not in seen:
            seen.append(token)
    return seen


class TestSkillContract(unittest.TestCase):
    def test_skill_exists_and_under_line_cap(self) -> None:
        self.assertTrue(SKILL.exists(), f"missing {SKILL}")
        text = SKILL.read_text(encoding="utf-8")
        lines = text.splitlines()
        self.assertLessEqual(
            len(lines), 120, f"SKILL.md is {len(lines)} lines; cap is 120"
        )

    def test_required_keywords(self) -> None:
        text = SKILL.read_text(encoding="utf-8")
        for needle in REQUIRED:
            with self.subTest(needle=needle):
                self.assertIn(needle, text)

    def test_no_model_fallback_or_known_slugs(self) -> None:
        text = SKILL.read_text(encoding="utf-8")
        lower = text.lower()
        for needle in FORBIDDEN:
            with self.subTest(needle=needle):
                self.assertNotIn(needle.lower(), lower)

    def test_skill_command_block_cli_help_parity(self) -> None:
        self.assertTrue(SCRIPT.is_file(), f"missing {SCRIPT}")
        text = SKILL.read_text(encoding="utf-8")
        cmds = _skill_command_tokens(text)
        self.assertTrue(
            cmds,
            "SKILL.md Commands ```sh``` block must list loop-memory.py <cmd> tokens",
        )
        with tempfile.TemporaryDirectory() as tmp:
            env = os.environ.copy()
            env["LOOP_MEMORY_HOME"] = tmp
            env["LOOP_MEMORY_SESSION"] = "contract-session"
            for cmd in cmds:
                with self.subTest(cmd=cmd):
                    proc = subprocess.run(
                        [sys.executable, str(SCRIPT), cmd, "--help"],
                        capture_output=True,
                        text=True,
                        env=env,
                    )
                    self.assertEqual(
                        proc.returncode,
                        0,
                        msg=(
                            f"{cmd} --help failed (exit {proc.returncode})\n"
                            f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
                        ),
                    )


if __name__ == "__main__":
    unittest.main()
