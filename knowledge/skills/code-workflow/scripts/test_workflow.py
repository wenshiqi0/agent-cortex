#!/usr/bin/env python3
"""Behavior tests for code-workflow workflow.py — stdlib unittest only.

These tests encode the design contract from `.cortex/code-workflow/briefs/T1.md`.
They are expected to be RED until `workflow.py` is implemented and
`progress.py` gains the `set-direction` op.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "workflow.py"


def run_cli(*args: str, check: bool = True, worktree: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["LOOP_MEMORY_HOME"] = str(worktree / ".cortex" / "code-workflow" / "loop-memory")
    env["LOOP_MEMORY_SESSION"] = "default"
    cmd = [sys.executable, str(SCRIPT), *args, "--worktree", str(worktree)]
    return subprocess.run(cmd, capture_output=True, text=True, check=check, env=env)


class WorkflowBase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.wt = Path(self.tmp.name)
        self.run_dir = self.wt / ".cortex" / "code-workflow"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _start(self, *extra: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return run_cli("start", "--goal", "ship X", *extra, check=check, worktree=self.wt)

    def _direction(self) -> Path:
        path = self.wt / "direction.md"
        path.write_text("# Direction\n\n- one\n- two\n", encoding="utf-8")
        return path

    def _plan(self) -> Path:
        path = self.wt / "plan.md"
        path.write_text("# Plan\n\n- task\n", encoding="utf-8")
        return path

    def _brief(self) -> Path:
        path = self.wt / "brief.md"
        path.write_text("# Brief\n\nDo the thing.\n", encoding="utf-8")
        return path

    def _report(self, name: str) -> Path:
        path = self.run_dir / "reports" / name
        path.write_text(f"# {name}\n", encoding="utf-8")
        return path


class TestStart(WorkflowBase):
    def test_creates_layout_and_preflight_done(self) -> None:
        out = self._start()
        self.assertTrue(json.loads(out.stdout)["ok"])
        for name in ("briefs", "reports", "snapshots", "loop-memory", "loop-memory-archive"):
            self.assertTrue((self.run_dir / name).is_dir(), f"missing dir {name}")
        ledger = self.run_dir / "progress.jsonl"
        self.assertTrue(ledger.exists())
        state = json.loads(run_cli("show", "--json", worktree=self.wt).stdout)
        self.assertEqual(state["run"]["preflight"], "done")
        self.assertEqual(state["goal"], "ship X")

    def test_fails_without_force_when_ledger_exists(self) -> None:
        self._start()
        bad = self._start(check=False)
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn("error:", bad.stderr)


class TestDirectionGate(WorkflowBase):
    def test_set_plan_fails_without_confirmed_direction(self) -> None:
        self._start()
        plan = self._plan()
        bad = run_cli("set-plan", "--plan", str(plan), check=False, worktree=self.wt)
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn("error:", bad.stderr)

    def test_confirm_direction_then_set_plan(self) -> None:
        self._start()
        direction = self._direction()
        plan = self._plan()
        run_cli("confirm-direction", "--file", str(direction), worktree=self.wt)
        out = run_cli("set-plan", "--plan", str(plan), worktree=self.wt)
        self.assertTrue(json.loads(out.stdout)["ok"])
        state = json.loads(run_cli("show", "--json", worktree=self.wt).stdout)
        self.assertEqual(state["run"]["plan"], "done")
        self.assertTrue(state.get("direction"))
        self.assertTrue(state.get("direction_confirmed"))

    def test_confirm_direction_twice_fails(self) -> None:
        self._start()
        direction = self._direction()
        run_cli("confirm-direction", "--file", str(direction), worktree=self.wt)
        bad = run_cli("confirm-direction", "--file", str(direction), check=False, worktree=self.wt)
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn("error:", bad.stderr)

    def test_confirm_direction_copies_to_stable_run_path(self) -> None:
        self._start()
        direction = self._direction()
        run_cli("confirm-direction", "--file", str(direction), worktree=self.wt)
        stable = (self.run_dir / "direction.md").resolve()
        self.assertTrue(stable.exists())
        self.assertEqual(stable.read_text(encoding="utf-8"), direction.read_text(encoding="utf-8"))
        state = json.loads(run_cli("show", "--json", worktree=self.wt).stdout)
        self.assertEqual(state["direction"], str(stable))

    def test_set_plan_missing_file_fails_with_error_prefix(self) -> None:
        self._start()
        run_cli("confirm-direction", "--file", str(self._direction()), worktree=self.wt)
        bad = run_cli("set-plan", "--plan", str(self.wt / "no-such-plan.md"), check=False, worktree=self.wt)
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn("error:", bad.stderr)


class TestAddTask(WorkflowBase):
    def test_add_task_creates_todo_and_loop(self) -> None:
        self._start()
        run_cli("confirm-direction", "--file", str(self._direction()), worktree=self.wt)
        run_cli("set-plan", "--plan", str(self._plan()), worktree=self.wt)
        brief = self._brief()
        out = run_cli("add-task", "--id", "T1", "--title", "write tests", "--brief", str(brief), worktree=self.wt)
        self.assertTrue(json.loads(out.stdout)["ok"])
        state = json.loads(run_cli("show", "--json", worktree=self.wt).stdout)
        self.assertEqual(len(state["todos"]), 1)
        self.assertEqual(state["todos"][0]["id"], "T1")
        loop_file = self.run_dir / "loop-memory" / "default" / "T1.json"
        self.assertTrue(loop_file.exists())

    def test_add_task_missing_brief_fails_with_error_prefix(self) -> None:
        self._start()
        run_cli("confirm-direction", "--file", str(self._direction()), worktree=self.wt)
        run_cli("set-plan", "--plan", str(self._plan()), worktree=self.wt)
        bad = run_cli(
            "add-task", "--id", "T1", "--title", "write tests",
            "--brief", str(self.wt / "no-such-brief.md"),
            check=False,
            worktree=self.wt,
        )
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn("error:", bad.stderr)


class TestNextJson(WorkflowBase):
    def _setup_task(self) -> Path:
        self._start()
        run_cli("confirm-direction", "--file", str(self._direction()), worktree=self.wt)
        run_cli("set-plan", "--plan", str(self._plan()), worktree=self.wt)
        brief = self._brief()
        run_cli("add-task", "--id", "T1", "--title", "write tests", "--brief", str(brief), worktree=self.wt)
        return brief

    def test_exact_schema_and_fixed_role_model(self) -> None:
        brief = self._setup_task()
        out = run_cli("next", "--json", worktree=self.wt)
        data = json.loads(out.stdout)
        self.assertFalse(data["done"])
        self.assertEqual(data["run"]["goal"], "ship X")
        self.assertEqual(data["run"]["worktree"], str(self.wt))
        self.assertTrue(data["run"]["plan"])
        self.assertTrue(data["run"]["direction"])
        self.assertEqual(data["task"]["id"], "T1")
        self.assertEqual(data["task"]["title"], "write tests")
        self.assertEqual(data["task"]["brief"], str(brief.resolve()))
        self.assertEqual(data["stage"], "test_write")
        dispatch = data["dispatch"]
        self.assertEqual(dispatch["role"], "test_writer")
        self.assertEqual(dispatch["model"], "kimi-k3-max")
        self.assertIn("fallback_models", dispatch)
        self.assertEqual(dispatch["fallback_models"], ["cursor-grok-4.5-high"])
        self.assertEqual(dispatch["report_path"], str((self.run_dir / "reports" / "T1.test_write.md").resolve()))
        self.assertIn("tests-only", dispatch["allowed_edit_scope"])
        self.assertIn(str(brief.resolve()), dispatch["inputs"])
        for path in dispatch["inputs"]:
            self.assertTrue(Path(path).is_absolute(), f"not absolute: {path}")
        # no artifact bodies: only paths and short strings
        self.assertNotIn("Do the thing.", json.dumps(data))

    def test_next_at_verify_red_role_model_and_snapshot_in(self) -> None:
        self._setup_task()
        report = self._report("T1.test_write.md")
        run_cli(
            "accept-stage",
            "--id", "T1", "--stage", "test_write", "--report", str(report),
            worktree=self.wt,
        )
        data = json.loads(run_cli("next", "--json", worktree=self.wt).stdout)
        self.assertFalse(data["done"])
        self.assertEqual(data["stage"], "verify_red")
        dispatch = data["dispatch"]
        self.assertEqual(dispatch["role"], "verify_red")
        self.assertEqual(dispatch["model"], "kimi-k3-max")
        self.assertIn("fallback_models", dispatch)
        self.assertEqual(dispatch["fallback_models"], [])
        self.assertIn("read-only", dispatch["allowed_edit_scope"])
        wt_snap = (self.run_dir / "snapshots" / "T1.WT.json").resolve()
        self.assertEqual(dispatch["snapshot_in"], str(wt_snap))
        self.assertIn(str(wt_snap), dispatch["inputs"])

    def test_done_true_when_all_todos_complete(self) -> None:
        self._setup_task()
        # mark all stages done directly via progress.py
        progress = Path(__file__).resolve().parent / "progress.py"
        env = os.environ.copy()
        env["LOOP_MEMORY_HOME"] = str(self.run_dir / "loop-memory")
        env["LOOP_MEMORY_SESSION"] = "default"
        for stage in ("test_write", "verify_red", "implement", "verify_green"):
            subprocess.run(
                [sys.executable, str(progress), "mark", "--worktree", str(self.wt), "--id", "T1", "--stage", stage],
                check=True,
                env=env,
            )
        out = run_cli("next", "--json", worktree=self.wt)
        self.assertEqual(json.loads(out.stdout), {"done": True})


class TestAcceptStage(WorkflowBase):
    def _setup_task(self) -> Path:
        self._start()
        run_cli("confirm-direction", "--file", str(self._direction()), worktree=self.wt)
        run_cli("set-plan", "--plan", str(self._plan()), worktree=self.wt)
        brief = self._brief()
        run_cli("add-task", "--id", "T1", "--title", "write tests", "--brief", str(brief), worktree=self.wt)
        return brief

    def test_out_of_order_stage_rejected(self) -> None:
        self._setup_task()
        report = self._report("T1.verify_red.md")
        bad = run_cli(
            "accept-stage",
            "--id", "T1", "--stage", "verify_red", "--report", str(report),
            "--red-reason", "r", "--red-passed", "0", "--red-failed", "1",
            check=False,
            worktree=self.wt,
        )
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn("error:", bad.stderr)

    def test_test_write_acceptance_and_snapshot(self) -> None:
        self._setup_task()
        report = self._report("T1.test_write.md")
        out = run_cli(
            "accept-stage",
            "--id", "T1", "--stage", "test_write", "--report", str(report),
            "--decision", "use stdlib",
            "--file", "scripts/test_workflow.py",
            worktree=self.wt,
        )
        self.assertTrue(json.loads(out.stdout)["ok"])
        snap = self.run_dir / "snapshots" / "T1.WT.json"
        self.assertTrue(snap.exists())
        state = json.loads(run_cli("show", "--json", worktree=self.wt).stdout)
        self.assertEqual(state["todos"][0]["stages"]["test_write"], "done")

    def test_verify_red_requires_red_triple(self) -> None:
        self._setup_task()
        report = self._report("T1.test_write.md")
        run_cli(
            "accept-stage",
            "--id", "T1", "--stage", "test_write", "--report", str(report),
            worktree=self.wt,
        )
        red_report = self._report("T1.verify_red.md")
        bad = run_cli(
            "accept-stage",
            "--id", "T1", "--stage", "verify_red", "--report", str(red_report),
            check=False,
            worktree=self.wt,
        )
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn("error:", bad.stderr)

    def test_verify_red_snapshot_and_implement_dispatch(self) -> None:
        self._setup_task()
        report = self._report("T1.test_write.md")
        run_cli(
            "accept-stage",
            "--id", "T1", "--stage", "test_write", "--report", str(report),
            worktree=self.wt,
        )
        red_report = self._report("T1.verify_red.md")
        run_cli(
            "accept-stage",
            "--id", "T1", "--stage", "verify_red", "--report", str(red_report),
            "--red-reason", "workflow.py missing",
            "--red-passed", "0", "--red-failed", "16",
            worktree=self.wt,
        )
        ver_snap = (self.run_dir / "snapshots" / "T1.VER.json").resolve()
        self.assertTrue(ver_snap.exists())
        self.assertIn("workflow.py missing", ver_snap.read_text(encoding="utf-8"))
        data = json.loads(run_cli("next", "--json", worktree=self.wt).stdout)
        self.assertEqual(data["stage"], "implement")
        dispatch = data["dispatch"]
        self.assertEqual(dispatch["role"], "implement")
        self.assertEqual(dispatch["model"], "kimi-k3-max")
        self.assertIn("fallback_models", dispatch)
        self.assertEqual(dispatch["fallback_models"], ["cursor-grok-4.5-high"])
        self.assertIn("task-scope", dispatch["allowed_edit_scope"])
        self.assertEqual(dispatch["snapshot_in"], str(ver_snap))
        self.assertIn(str(ver_snap), dispatch["inputs"])

    def test_implement_snapshot_and_verify_green_dispatch(self) -> None:
        self._setup_task()
        for stage, extra in [
            ("test_write", []),
            ("verify_red", ["--red-reason", "r", "--red-passed", "0", "--red-failed", "1"]),
            ("implement", []),
        ]:
            report = self._report(f"T1.{stage}.md")
            run_cli(
                "accept-stage",
                "--id", "T1", "--stage", stage, "--report", str(report), *extra,
                worktree=self.wt,
            )
        impl_snap = (self.run_dir / "snapshots" / "T1.IMPL.json").resolve()
        self.assertTrue(impl_snap.exists())
        data = json.loads(run_cli("next", "--json", worktree=self.wt).stdout)
        self.assertEqual(data["stage"], "verify_green")
        dispatch = data["dispatch"]
        self.assertEqual(dispatch["role"], "verify_green")
        self.assertEqual(dispatch["model"], "kimi-k3-max")
        self.assertIn("fallback_models", dispatch)
        self.assertEqual(dispatch["fallback_models"], [])
        self.assertIn("read-only", dispatch["allowed_edit_scope"])
        self.assertEqual(dispatch["snapshot_in"], str(impl_snap))
        self.assertIn(str(impl_snap), dispatch["inputs"])

    def test_verify_green_requires_verdict_and_archives_loop(self) -> None:
        self._setup_task()
        for stage, extra in [
            ("test_write", []),
            ("verify_red", ["--red-reason", "missing", "--red-passed", "0", "--red-failed", "1"]),
            ("implement", []),
        ]:
            report = self._report(f"T1.{stage}.md")
            run_cli("accept-stage", "--id", "T1", "--stage", stage, "--report", str(report), *extra, worktree=self.wt)
        green_report = self._report("T1.verify_green.md")
        bad = run_cli(
            "accept-stage",
            "--id", "T1", "--stage", "verify_green", "--report", str(green_report),
            check=False,
            worktree=self.wt,
        )
        self.assertNotEqual(bad.returncode, 0)
        run_cli(
            "accept-stage",
            "--id", "T1", "--stage", "verify_green", "--report", str(green_report),
            "--verdict", "GREEN", "--passed", "1", "--failed", "0",
            worktree=self.wt,
        )
        archive = self.run_dir / "loop-memory-archive" / "T1.json"
        self.assertTrue(archive.exists())
        loop = self.run_dir / "loop-memory" / "default" / "T1.json"
        self.assertFalse(loop.exists())

    def test_verify_red_loop_memory_failure_does_not_advance_ledger(self) -> None:
        """accept-stage must not leave ledger ahead of cognition/snapshot SSOT.

        After a successful test_write, deleting the active loop forces verify_red's
        cognition/snapshot fold to fail. Ledger must remain pending at verify_red
        so next does not dispatch implement against a missing VER snapshot.
        """
        self._setup_task()
        report = self._report("T1.test_write.md")
        run_cli(
            "accept-stage",
            "--id", "T1", "--stage", "test_write", "--report", str(report),
            worktree=self.wt,
        )
        loop = self.run_dir / "loop-memory" / "default" / "T1.json"
        self.assertTrue(loop.exists())
        loop.unlink()

        red_report = self._report("T1.verify_red.md")
        bad = run_cli(
            "accept-stage",
            "--id", "T1", "--stage", "verify_red", "--report", str(red_report),
            "--red-reason", "workflow.py missing",
            "--red-passed", "0", "--red-failed", "1",
            check=False,
            worktree=self.wt,
        )
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn("error:", bad.stderr)

        ver_snap = self.run_dir / "snapshots" / "T1.VER.json"
        self.assertFalse(ver_snap.exists())

        state = json.loads(run_cli("show", "--json", worktree=self.wt).stdout)
        self.assertNotEqual(state["todos"][0]["stages"]["verify_red"], "done")

        data = json.loads(run_cli("next", "--json", worktree=self.wt).stdout)
        self.assertFalse(data["done"])
        self.assertEqual(data["stage"], "verify_red")
        self.assertNotEqual(data["stage"], "implement")
        dispatch = data["dispatch"]
        self.assertEqual(dispatch["role"], "verify_red")
        wt_snap = (self.run_dir / "snapshots" / "T1.WT.json").resolve()
        self.assertEqual(dispatch["snapshot_in"], str(wt_snap))
        self.assertNotIn("T1.VER.json", dispatch.get("snapshot_in") or "")
        self.assertFalse(any("T1.VER.json" in str(p) for p in dispatch.get("inputs") or []))

    def test_verify_green_loop_memory_failure_does_not_leave_stage_done(self) -> None:
        """verify_green cognition/archive failure must not permanently mark ledger done."""
        self._setup_task()
        for stage, extra in [
            ("test_write", []),
            ("verify_red", ["--red-reason", "r", "--red-passed", "0", "--red-failed", "1"]),
            ("implement", []),
        ]:
            report = self._report(f"T1.{stage}.md")
            run_cli(
                "accept-stage",
                "--id", "T1", "--stage", stage, "--report", str(report), *extra,
                worktree=self.wt,
            )
        loop = self.run_dir / "loop-memory" / "default" / "T1.json"
        self.assertTrue(loop.exists())
        loop.unlink()

        green_report = self._report("T1.verify_green.md")
        bad = run_cli(
            "accept-stage",
            "--id", "T1", "--stage", "verify_green", "--report", str(green_report),
            "--verdict", "GREEN", "--passed", "1", "--failed", "0",
            check=False,
            worktree=self.wt,
        )
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn("error:", bad.stderr)

        state = json.loads(run_cli("show", "--json", worktree=self.wt).stdout)
        self.assertNotEqual(state["todos"][0]["stages"]["verify_green"], "done")

        data = json.loads(run_cli("next", "--json", worktree=self.wt).stdout)
        self.assertFalse(data["done"])
        self.assertEqual(data["stage"], "verify_green")


class TestCloseout(WorkflowBase):
    def test_fails_with_pending_todos(self) -> None:
        self._start()
        run_cli("confirm-direction", "--file", str(self._direction()), worktree=self.wt)
        run_cli("set-plan", "--plan", str(self._plan()), worktree=self.wt)
        brief = self._brief()
        run_cli("add-task", "--id", "T1", "--title", "write tests", "--brief", str(brief), worktree=self.wt)
        bad = run_cli("closeout", check=False, worktree=self.wt)
        self.assertNotEqual(bad.returncode, 0)

    def test_succeeds_after_all_done_and_compacts(self) -> None:
        self._start()
        run_cli("confirm-direction", "--file", str(self._direction()), worktree=self.wt)
        run_cli("set-plan", "--plan", str(self._plan()), worktree=self.wt)
        brief = self._brief()
        run_cli("add-task", "--id", "T1", "--title", "write tests", "--brief", str(brief), worktree=self.wt)
        progress = Path(__file__).resolve().parent / "progress.py"
        env = os.environ.copy()
        env["LOOP_MEMORY_HOME"] = str(self.run_dir / "loop-memory")
        env["LOOP_MEMORY_SESSION"] = "default"
        for stage in ("test_write", "verify_red", "implement", "verify_green"):
            subprocess.run(
                [sys.executable, str(progress), "mark", "--worktree", str(self.wt), "--id", "T1", "--stage", stage],
                check=True,
                env=env,
            )
        # archive the loop to satisfy closeout gate
        loop_archive = self.run_dir / "loop-memory-archive"
        loop_archive.mkdir(parents=True, exist_ok=True)
        (loop_archive / "T1.json").write_text("{}", encoding="utf-8")
        loop_file = self.run_dir / "loop-memory" / "default" / "T1.json"
        if loop_file.exists():
            loop_file.unlink()
        out = run_cli("closeout", worktree=self.wt)
        self.assertTrue(json.loads(out.stdout)["ok"])
        state = json.loads(run_cli("show", "--json", worktree=self.wt).stdout)
        self.assertEqual(state["run"]["closeout"], "done")
        # compact leaves single snapshot line
        lines = (self.run_dir / "progress.jsonl").read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0])["op"], "snapshot")


class TestFast(WorkflowBase):
    def test_code_model_and_stateless(self) -> None:
        out = run_cli("fast", "--kind", "code", "--goal", "fix typo", "--files", "a.py", "--verify", "python3 -m unittest", worktree=self.wt)
        data = json.loads(out.stdout)
        dispatch = data["dispatch"]
        self.assertEqual(dispatch["role"], "fast_coder")
        self.assertEqual(dispatch["model"], "kimi-k3-max")
        self.assertIn("fallback_models", dispatch)
        self.assertEqual(dispatch["fallback_models"], ["cursor-grok-4.5-high"])
        self.assertFalse((self.run_dir / "progress.jsonl").exists())

    def test_prose_model(self) -> None:
        out = run_cli("fast", "--kind", "prose", "--goal", "fix docs", "--files", "README.md", "--verify", "make docs", worktree=self.wt)
        data = json.loads(out.stdout)
        dispatch = data["dispatch"]
        self.assertEqual(dispatch["role"], "fast_coder")
        self.assertEqual(dispatch["model"], "kimi-k3-max")
        self.assertIn("fallback_models", dispatch)
        self.assertEqual(dispatch["fallback_models"], [])


if __name__ == "__main__":
    unittest.main()
