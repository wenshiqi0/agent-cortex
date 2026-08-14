#!/usr/bin/env python3
"""RED tests for mrain scripts/doctor.py (stdlib unittest only).

Stub mrain binary + PATH/HOME/env. Never call a real provider or real DB.
Run: python3 knowledge/skills/mrain/tests/test_doctor.py
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
DOCTOR = SKILL_ROOT / "scripts" / "doctor.py"

PROVIDER_KEYS = (
    "MRAIN_ANTHROPIC_API_KEY",
    "MRAIN_OPENAI_API_KEY",
)


def _strip_provider_env(env: dict[str, str]) -> None:
    for key in PROVIDER_KEYS:
        env.pop(key, None)


class DoctorTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.bin_dir = self.root / "bin"
        self.bin_dir.mkdir()
        self.home = self.root / "home"
        self.home.mkdir()
        self.env = os.environ.copy()
        _strip_provider_env(self.env)
        self.env["HOME"] = str(self.home)
        self.env["PATH"] = f"{self.bin_dir}{os.pathsep}{self.env.get('PATH', '')}"
        # Avoid leaking unrelated provider config into the subprocess.
        for noise in (
            "ANTHROPIC_API_KEY",
            "OPENAI_API_KEY",
            "MRAIN_ANTHROPIC_ENDPOINT",
            "MRAIN_OPENAI_ENDPOINT",
        ):
            self.env.pop(noise, None)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write_stub(
        self,
        *,
        help_exit: int = 0,
        memorize_exit: int = 0,
        recall_exit: int = 0,
    ) -> Path:
        script = self.bin_dir / "mrain"
        body = textwrap.dedent(
            f"""\
            #!/bin/sh
            # Stub mrain — no network, no real DB.
            if [ "$1" = "--help" ]; then
              echo "mrain stub help"
              exit {help_exit}
            fi
            if [ "$1" = "memory" ] && [ "$2" = "memorize" ]; then
              exit {memorize_exit}
            fi
            if [ "$1" = "memory" ] && [ "$2" = "recall" ]; then
              echo "ok: recalled smoke"
              exit {recall_exit}
            fi
            echo "unexpected args: $*" >&2
            exit 99
            """
        )
        script.write_text(body, encoding="utf-8")
        script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        return script

    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        self.assertTrue(
            DOCTOR.is_file(),
            f"doctor.py missing (RED until implementer lands it): {DOCTOR}",
        )
        # Use sys.executable so PATH can be isolated without losing the interpreter.
        return subprocess.run(
            [sys.executable, str(DOCTOR), *args],
            capture_output=True,
            text=True,
            env=self.env,
            timeout=30,
        )

    def _lines(self, proc: subprocess.CompletedProcess[str]) -> list[str]:
        out = (proc.stdout or "").strip()
        if not out:
            return []
        return out.splitlines()

    def test_binary_missing_exits_2(self) -> None:
        # Isolate PATH to empty tmp bin only — system mrain must not leak in.
        self.env["PATH"] = str(self.bin_dir)
        proc = self._run()
        self.assertEqual(proc.returncode, 2)
        joined = "\n".join(self._lines(proc))
        self.assertRegex(joined, r"(?m)^FAIL binary\b", msg=joined)
        self.assertTrue(
            any("install" in line.lower() or "PATH" in line for line in self._lines(proc))
            or "install" in (proc.stderr or "").lower(),
            "missing binary should include a clear install hint",
        )

    def test_help_failure_is_fail(self) -> None:
        self._write_stub(help_exit=1)
        self.env["MRAIN_OPENAI_API_KEY"] = "test-key-not-real"
        proc = self._run()
        self.assertEqual(proc.returncode, 1)
        joined = "\n".join(self._lines(proc))
        self.assertRegex(joined, r"(?m)^FAIL help\b", msg=joined)

    def test_no_provider_key_without_smoke_exits_1(self) -> None:
        self._write_stub()
        proc = self._run()
        self.assertEqual(proc.returncode, 1)
        joined = "\n".join(self._lines(proc))
        self.assertRegex(joined, r"(?m)^FAIL provider\b", msg=joined)
        self.assertFalse(
            any(line.startswith("SKIP smoke") or line.startswith("OK smoke") for line in self._lines(proc)),
            "smoke check must not appear without --smoke",
        )
        # Default mode must not create $HOME/.mrain
        self.assertFalse((self.home / ".mrain").exists())

    def test_all_good_exits_0(self) -> None:
        self._write_stub()
        self.env["MRAIN_ANTHROPIC_API_KEY"] = "test-key-not-real"
        proc = self._run()
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
        lines = self._lines(proc)
        joined = "\n".join(lines)
        self.assertRegex(joined, r"(?m)^OK binary\b", msg=joined)
        self.assertRegex(joined, r"(?m)^OK help\b", msg=joined)
        self.assertRegex(joined, r"(?m)^OK provider\b", msg=joined)
        self.assertTrue(
            any(line.startswith("OK storage") or line.startswith("WARN storage") for line in lines),
            f"expected storage check: {joined}",
        )
        self.assertFalse((self.home / ".mrain").exists())

    def test_json_shape(self) -> None:
        self._write_stub()
        self.env["MRAIN_OPENAI_API_KEY"] = "test-key-not-real"
        proc = self._run("--json")
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertIsInstance(payload, dict)
        self.assertEqual(set(payload.keys()) & {"checks", "ok"}, {"checks", "ok"})
        self.assertIsInstance(payload["checks"], list)
        self.assertIsInstance(payload["ok"], bool)
        self.assertTrue(payload["ok"])
        self.assertGreaterEqual(len(payload["checks"]), 4)
        for check in payload["checks"]:
            self.assertIsInstance(check, dict)

    def test_smoke_without_api_key_skip_and_exit_1(self) -> None:
        """Corrected semantics: SKIP smoke must not mask FAIL provider → exit 1."""
        self._write_stub()
        proc = self._run("--smoke")
        self.assertEqual(
            proc.returncode,
            1,
            msg=(
                "overall exit must be 1 when provider FAILs even if smoke is SKIP; "
                f"got {proc.returncode}\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
            ),
        )
        lines = self._lines(proc)
        joined = "\n".join(lines)
        self.assertRegex(joined, r"(?m)^FAIL provider\b", msg=joined)
        self.assertRegex(joined, r"(?m)^SKIP smoke\b", msg=joined)
        # Must not claim smoke OK / run smoke successfully without a key.
        self.assertFalse(
            any(line.startswith("OK smoke") for line in lines),
            "smoke must not be OK without a provider key",
        )

    def test_smoke_with_key_against_stub_ok_exit_0(self) -> None:
        self._write_stub()
        self.env["MRAIN_OPENAI_API_KEY"] = "test-key-not-real"
        proc = self._run("--smoke")
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
        joined = "\n".join(self._lines(proc))
        self.assertRegex(joined, r"(?m)^OK smoke\b", msg=joined)
        self.assertRegex(joined, r"(?m)^OK provider\b", msg=joined)


if __name__ == "__main__":
    unittest.main()
