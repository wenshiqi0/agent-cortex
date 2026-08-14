#!/usr/bin/env python3
"""RED tests for scripts/skill-audit.py (stdlib unittest only).

Locks discovery under knowledge/skills/, all five checks, text/JSON output,
skill-dir-first path resolution, and a real-repo exit-0 run.

Fixture runs invoke the real script with cwd=<fixture repo root> so the
implementer must resolve the audit root from the process cwd (not only from
__file__). Public CLI remains: python3 scripts/skill-audit.py [--json].

Run: python3 tests/test_skill_audit.py
"""

from __future__ import annotations

import json
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
AUDIT = REPO_ROOT / "scripts" / "skill-audit.py"

LINE_RE = re.compile(r"^(OK|WARN|FAIL) (\S+) (\S+) (.+)$")


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body).lstrip("\n"), encoding="utf-8")


def _make_executable(path: Path) -> None:
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


class SkillAuditTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.assertTrue(
            AUDIT.is_file(),
            f"skill-audit.py missing (RED until implementer lands it): {AUDIT}",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    # --- fixture helpers -------------------------------------------------

    def _skill_dir(self, name: str) -> Path:
        return self.root / "knowledge" / "skills" / name

    def _write_skill(
        self,
        name: str,
        *,
        frontmatter_name: str | None = None,
        description: str = "Fixture skill for skill-audit tests.",
        body: str = "# {name}\n\nProse only.\n",
    ) -> Path:
        fm_name = name if frontmatter_name is None else frontmatter_name
        skill = self._skill_dir(name)
        text = (
            f"---\nname: {fm_name}\ndescription: {description}\n---\n\n"
            + body.format(name=name)
        )
        _write(skill / "SKILL.md", text)
        return skill

    def _write_cli_js(self, *commands: str) -> None:
        cases = "\n".join(f"    case '{cmd}': return 0;" for cmd in commands)
        _write(
            self.root / "scripts" / "cli.js",
            f"""\
            switch (cmd) {{
            {cases}
              default: process.exit(1);
            }}
            """,
        )

    def _write_py_cli(self, rel: Path, *subcommands: str) -> Path:
        """Minimal argparse CLI; listed subcommands exit 0 on --help."""
        path = self.root / rel
        cmds = ", ".join(repr(c) for c in subcommands)
        _write(
            path,
            f"""\
            #!/usr/bin/env python3
            import argparse
            import sys

            def main(argv=None):
                p = argparse.ArgumentParser()
                sub = p.add_subparsers(dest="cmd", required=True)
                for name in [{cmds}]:
                    sub.add_parser(name)
                p.parse_args(argv)
                return 0

            if __name__ == "__main__":
                raise SystemExit(main())
            """,
        )
        _make_executable(path)
        return path

    def _run(self, *args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(AUDIT), *args],
            capture_output=True,
            text=True,
            cwd=str(cwd if cwd is not None else self.root),
            timeout=60,
        )

    def _fail_lines(self, proc: subprocess.CompletedProcess[str]) -> list[str]:
        return [
            line
            for line in (proc.stdout or "").splitlines()
            if line.startswith("FAIL ")
        ]

    def _assert_line_shape(self, proc: subprocess.CompletedProcess[str]) -> list[re.Match[str]]:
        matches: list[re.Match[str]] = []
        for line in (proc.stdout or "").splitlines():
            if not line.strip():
                continue
            m = LINE_RE.match(line)
            self.assertIsNotNone(m, f"bad output line: {line!r}\nfull:\n{proc.stdout}")
            assert m is not None
            matches.append(m)
        return matches

    # --- discovery / happy path ------------------------------------------

    def test_valid_skill_passes_exit_0(self) -> None:
        self._write_skill("good-skill")
        self._write_cli_js("relink", "list")
        proc = self._run()
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
        matches = self._assert_line_shape(proc)
        self.assertTrue(matches, "expected at least one OK/WARN/FAIL line")
        self.assertFalse(self._fail_lines(proc), msg=proc.stdout)
        skills = {m.group(2) for m in matches}
        self.assertEqual(skills, {"good-skill"})

    def test_external_skills_dir_ignored(self) -> None:
        self._write_skill("builtin-only")
        # External tree must never be scanned even when present at repo root.
        _write(
            self.root / "skills" / "external-skill" / "SKILL.md",
            """\
            ---
            name: external-skill
            description: Must be ignored by skill-audit.
            ---

            # external-skill
            """,
        )
        self._write_cli_js("relink")
        proc = self._run("--json")
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
        payload = json.loads(proc.stdout)
        names = [s["name"] for s in payload["skills"]]
        self.assertEqual(names, ["builtin-only"])
        self.assertNotIn("external-skill", names)

    # --- check 1: frontmatter --------------------------------------------

    def test_frontmatter_name_mismatch_fails(self) -> None:
        self._write_skill("mismatch", frontmatter_name="other-name")
        self._write_cli_js("relink")
        proc = self._run()
        self.assertEqual(proc.returncode, 1, msg=proc.stdout + proc.stderr)
        joined = "\n".join(self._fail_lines(proc))
        self.assertRegex(joined, r"(?m)^FAIL mismatch frontmatter\b", msg=proc.stdout)

    def test_frontmatter_empty_description_fails(self) -> None:
        skill = self._skill_dir("nodesc")
        _write(
            skill / "SKILL.md",
            """\
            ---
            name: nodesc
            description: ""
            ---

            # nodesc
            """,
        )
        self._write_cli_js("relink")
        proc = self._run()
        self.assertEqual(proc.returncode, 1, msg=proc.stdout + proc.stderr)
        joined = "\n".join(self._fail_lines(proc))
        self.assertRegex(joined, r"(?m)^FAIL nodesc frontmatter\b", msg=proc.stdout)

    # --- check 2: SKILL.md line cap --------------------------------------

    def _write_n_line_skill(self, name: str, n: int) -> Path:
        """Write SKILL.md with exactly ``n`` lines (splitlines count)."""
        skill = self._skill_dir(name)
        skill.mkdir(parents=True, exist_ok=True)
        lines = [
            "---",
            f"name: {name}",
            "description: Fixture skill for skill-audit line-cap tests.",
            "---",
            "",
            f"# {name}",
            "",
        ]
        while len(lines) < n:
            lines.append(f"Padding line {len(lines)}.")
        self.assertEqual(len(lines), n)
        text = "\n".join(lines) + "\n"
        self.assertEqual(len(text.splitlines()), n)
        (skill / "SKILL.md").write_text(text, encoding="utf-8")
        return skill

    def test_skill_md_over_120_lines_fails(self) -> None:
        self._write_n_line_skill("overcap", 121)
        self._write_cli_js("relink")
        proc = self._run()
        self.assertEqual(proc.returncode, 1, msg=proc.stdout + proc.stderr)
        joined = "\n".join(self._fail_lines(proc))
        self.assertRegex(joined, r"(?m)^FAIL overcap lines\b", msg=proc.stdout)
        self.assertIn("120", joined)

    def test_skill_md_exactly_120_lines_ok(self) -> None:
        self._write_n_line_skill("atcap", 120)
        self._write_cli_js("relink")
        proc = self._run()
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
        self.assertFalse(
            any(
                line.startswith("FAIL ") and re.search(r"\blines\b", line)
                for line in self._fail_lines(proc)
            ),
            msg=proc.stdout,
        )
        # Stronger lock: lines check must emit OK (RED until implemented).
        self.assertRegex(proc.stdout or "", r"(?m)^OK atcap lines\b", msg=proc.stdout)

    # --- check 3: referenced local paths (skill-dir-first) ---------------

    def test_dangling_scripts_reference_fails(self) -> None:
        self._write_skill(
            "dangling",
            body="""\
            # dangling

            Run `scripts/missing.py` for setup.
            """,
        )
        self._write_cli_js("relink")
        proc = self._run()
        self.assertEqual(proc.returncode, 1, msg=proc.stdout + proc.stderr)
        joined = "\n".join(self._fail_lines(proc))
        self.assertRegex(joined, r"(?m)^FAIL dangling paths\b", msg=proc.stdout)
        self.assertIn("missing.py", joined)

    def test_scripts_token_resolved_skill_dir_first_ok(self) -> None:
        """scripts/x.py exists only under the skill dir → OK (skill-dir-first)."""
        skill = self._write_skill(
            "local-script",
            body="""\
            # local-script

            Facade: `scripts/x.py`.
            """,
        )
        _write(
            skill / "scripts" / "x.py",
            """\
            #!/usr/bin/env python3
            print("skill-local")
            """,
        )
        # Co-located test so check 5 does not fire (same pattern as cli-ok).
        _write(skill / "tests" / "test_x.py", "import unittest\n")
        # Deliberately no repo-root scripts/x.py.
        self._write_cli_js("relink")
        proc = self._run()
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
        self.assertFalse(
            any("paths" in line and line.startswith("FAIL ") for line in self._fail_lines(proc)),
            msg=proc.stdout,
        )
        joined = proc.stdout or ""
        self.assertRegex(joined, r"(?m)^OK local-script paths\b", msg=joined)

    def test_scripts_token_resolved_repo_root_ok(self) -> None:
        """scripts/x.py exists only at fixture repo root → OK (fallback)."""
        self._write_skill(
            "root-script",
            body="""\
            # root-script

            Drive `scripts/x.py` from the repo root.
            """,
        )
        _write(
            self.root / "scripts" / "x.py",
            """\
            #!/usr/bin/env python3
            print("repo-root")
            """,
        )
        self._write_cli_js("relink")
        proc = self._run()
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
        joined = proc.stdout or ""
        self.assertRegex(joined, r"(?m)^OK root-script paths\b", msg=joined)

    def test_url_and_env_prefixed_tokens_skipped(self) -> None:
        self._write_skill(
            "skip-tokens",
            body="""\
            # skip-tokens

            See https://example.com/tools/foo.py and http://cdn.example/bar.sh.
            Install to `$HOME/.local/bin/helper.py` or $HOME/bin/tool.py.
            """,
        )
        self._write_cli_js("relink")
        proc = self._run()
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
        self.assertFalse(self._fail_lines(proc), msg=proc.stdout)
        joined = proc.stdout or ""
        self.assertRegex(joined, r"(?m)^OK skip-tokens paths\b", msg=joined)

    # --- check 4: stale cortex command references ------------------------

    def test_unknown_cortex_command_fails(self) -> None:
        self._write_skill(
            "bad-cortex",
            body="""\
            # bad-cortex

            ```sh
            scripts/cortex frobnicate
            ```
            """,
        )
        self._write_cli_js("relink", "list", "verify")
        proc = self._run()
        self.assertEqual(proc.returncode, 1, msg=proc.stdout + proc.stderr)
        joined = "\n".join(self._fail_lines(proc))
        self.assertRegex(joined, r"(?m)^FAIL bad-cortex cortex\b", msg=proc.stdout)
        self.assertIn("frobnicate", joined)

    # --- check 5: documented skill CLI subcommands --help ----------------

    def test_documented_cli_subcommand_help_ok(self) -> None:
        skill = self._write_skill(
            "cli-ok",
            body="""\
            # cli-ok

            Facade: `scripts/tool.py`.

            ```sh
            python3 scripts/tool.py greet --help
            python3 scripts/tool.py wave
            ```
            """,
        )
        self._write_py_cli(Path("knowledge/skills/cli-ok/scripts/tool.py"), "greet", "wave")
        # Co-located test so check 5 does not fire.
        _write(skill / "tests" / "test_tool.py", "import unittest\n")
        self._write_cli_js("relink")
        proc = self._run()
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
        joined = proc.stdout or ""
        self.assertRegex(joined, r"(?m)^OK cli-ok cli\b", msg=joined)

    def test_documented_cli_subcommand_help_fails(self) -> None:
        skill = self._write_skill(
            "cli-bad",
            body="""\
            # cli-bad

            Facade: `scripts/tool.py`.

            ```sh
            python3 scripts/tool.py missingcmd
            ```
            """,
        )
        self._write_py_cli(Path("knowledge/skills/cli-bad/scripts/tool.py"), "only-real")
        _write(skill / "test_tool.py", "import unittest\n")
        self._write_cli_js("relink")
        proc = self._run()
        self.assertEqual(proc.returncode, 1, msg=proc.stdout + proc.stderr)
        joined = "\n".join(self._fail_lines(proc))
        self.assertRegex(joined, r"(?m)^FAIL cli-bad cli\b", msg=proc.stdout)

    # --- check 6: scripts required for unmechanized commands -------------

    def test_unmechanized_command_without_scripts_fails(self) -> None:
        """aws CLI in fence, no co-located *.py → FAIL scripts (paths/cli stay green)."""
        self._write_skill(
            "aws-doc",
            body="""\
            # aws-doc

            ```sh
            aws sqs list-queues --queue-name-prefix billing
            ```
            """,
        )
        self._write_cli_js("relink")
        proc = self._run()
        self.assertEqual(proc.returncode, 1, msg=proc.stdout + proc.stderr)
        joined = "\n".join(self._fail_lines(proc))
        self.assertRegex(joined, r"(?m)^FAIL aws-doc scripts\b", msg=proc.stdout)

    def test_repo_tooling_python3_scripts_is_mechanized_ok(self) -> None:
        """python3 scripts/x.py with repo-root scripts/x.py → OK scripts."""
        self._write_skill(
            "mech-py",
            body="""\
            # mech-py

            ```sh
            python3 scripts/x.py
            ```
            """,
        )
        _write(
            self.root / "scripts" / "x.py",
            """\
            #!/usr/bin/env python3
            print("repo-tooling")
            """,
        )
        self._write_cli_js("relink")
        proc = self._run()
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
        self.assertFalse(self._fail_lines(proc), msg=proc.stdout)
        self.assertRegex(proc.stdout or "", r"(?m)^OK mech-py scripts\b", msg=proc.stdout)

    def test_task_runner_bun_run_is_mechanized_ok(self) -> None:
        self._write_skill(
            "mech-bun",
            body="""\
            # mech-bun

            ```sh
            bun run inventory
            ```
            """,
        )
        self._write_cli_js("relink")
        proc = self._run()
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
        self.assertFalse(self._fail_lines(proc), msg=proc.stdout)
        self.assertRegex(proc.stdout or "", r"(?m)^OK mech-bun scripts\b", msg=proc.stdout)

    def test_unmechanized_but_ships_scripts_ok(self) -> None:
        """Unmechanized command short-circuits OK when skill ships co-located *.py."""
        skill = self._write_skill(
            "ships-scripts",
            body="""\
            # ships-scripts

            ```sh
            somecli do thing
            ```
            """,
        )
        _write(
            skill / "scripts" / "tool.py",
            """\
            #!/usr/bin/env python3
            print("tool")
            """,
        )
        _write(skill / "tests" / "test_tool.py", "import unittest\n")
        self._write_cli_js("relink")
        proc = self._run()
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
        self.assertFalse(self._fail_lines(proc), msg=proc.stdout)
        self.assertRegex(
            proc.stdout or "", r"(?m)^OK ships-scripts scripts\b", msg=proc.stdout
        )

    def test_directory_tree_fence_not_command_lines_ok(self) -> None:
        self._write_skill(
            "tree-doc",
            body="""\
            # tree-doc

            ```
            repositories/
            <repo>/ …
            ```
            """,
        )
        self._write_cli_js("relink")
        proc = self._run()
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
        self.assertFalse(self._fail_lines(proc), msg=proc.stdout)
        self.assertRegex(proc.stdout or "", r"(?m)^OK tree-doc scripts\b", msg=proc.stdout)

    # --- check 7: co-located scripts/tests -------------------------------

    def test_script_without_test_fails(self) -> None:
        skill = self._write_skill(
            "no-test",
            body="""\
            # no-test

            Uses `scripts/orphan.py`.
            """,
        )
        _write(
            skill / "scripts" / "orphan.py",
            """\
            #!/usr/bin/env python3
            print("orphan")
            """,
        )
        self._write_cli_js("relink")
        proc = self._run()
        self.assertEqual(proc.returncode, 1, msg=proc.stdout + proc.stderr)
        joined = "\n".join(self._fail_lines(proc))
        self.assertRegex(joined, r"(?m)^FAIL no-test tests\b", msg=proc.stdout)

    def test_script_with_colocated_test_ok(self) -> None:
        skill = self._write_skill(
            "with-test",
            body="""\
            # with-test

            Uses `scripts/ok.py`.
            """,
        )
        _write(
            skill / "scripts" / "ok.py",
            """\
            #!/usr/bin/env python3
            print("ok")
            """,
        )
        _write(skill / "tests" / "test_ok.py", "import unittest\n")
        self._write_cli_js("relink")
        proc = self._run()
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
        joined = proc.stdout or ""
        self.assertRegex(joined, r"(?m)^OK with-test tests\b", msg=joined)

    # --- output / exit codes ---------------------------------------------

    def test_json_shape_and_exit_codes(self) -> None:
        self._write_skill("json-ok")
        self._write_skill("json-bad", frontmatter_name="not-json-bad")
        self._write_cli_js("relink")

        bad = self._run("--json")
        self.assertEqual(bad.returncode, 1, msg=bad.stdout + bad.stderr)
        payload = json.loads(bad.stdout)
        self.assertEqual(set(payload.keys()), {"skills", "ok"})
        self.assertIsInstance(payload["skills"], list)
        self.assertIs(payload["ok"], False)
        names = [s["name"] for s in payload["skills"]]
        self.assertEqual(names, sorted(names), "skills must be sorted by name")
        self.assertEqual(set(names), {"json-ok", "json-bad"})
        for skill in payload["skills"]:
            self.assertEqual(set(skill.keys()) & {"name", "path", "checks"}, {"name", "path", "checks"})
            self.assertIsInstance(skill["checks"], list)
            self.assertTrue(skill["path"])
            for check in skill["checks"]:
                self.assertIsInstance(check, dict)
                # status/name/detail mirrors doctor-style check objects
                self.assertIn(check.get("status"), ("OK", "WARN", "FAIL"))
                self.assertTrue(check.get("name"))

        # Clean tree → exit 0 and ok true.
        for name in ("json-ok", "json-bad"):
            shutil.rmtree(self._skill_dir(name))
        self._write_skill("json-clean")
        good = self._run("--json")
        self.assertEqual(good.returncode, 0, msg=good.stdout + good.stderr)
        clean = json.loads(good.stdout)
        self.assertIs(clean["ok"], True)
        self.assertEqual([s["name"] for s in clean["skills"]], ["json-clean"])

    def test_text_warn_does_not_force_exit_1(self) -> None:
        """WARN must never affect exit code when there is no FAIL.

        If the implementation emits no WARN on a clean skill, exit 0 still holds.
        """
        self._write_skill("warn-ok")
        self._write_cli_js("relink")
        proc = self._run()
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
        self.assertFalse(self._fail_lines(proc), msg=proc.stdout)

    # --- real repo (capstone) --------------------------------------------

    def test_real_repo_exits_0(self) -> None:
        """Live agent-cortex tree must audit clean — makes T8 last."""
        proc = subprocess.run(
            [sys.executable, str(AUDIT), "--json"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            timeout=120,
        )
        self.assertEqual(
            proc.returncode,
            0,
            msg=(
                "real-repo skill-audit must exit 0\n"
                f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
            ),
        )
        payload = json.loads(proc.stdout)
        self.assertIs(payload["ok"], True)
        names = [s["name"] for s in payload["skills"]]
        self.assertEqual(names, sorted(names))
        # Inventory-discovered builtins only; external skills/ never appear.
        self.assertNotIn("external-skill", names)
        self.assertGreaterEqual(len(names), 1)
        for name in names:
            skill_md = REPO_ROOT / "knowledge" / "skills" / name / "SKILL.md"
            self.assertTrue(skill_md.is_file(), f"audited skill missing SKILL.md: {name}")


if __name__ == "__main__":
    unittest.main()
