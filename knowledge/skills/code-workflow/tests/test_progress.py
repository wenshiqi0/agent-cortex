#!/usr/bin/env python3
"""Tests for code-workflow progress.py — stdlib unittest only."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "progress.py"


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, str(SCRIPT), *args]
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def load_progress():
    spec = importlib.util.spec_from_file_location("cw_progress", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class ProgressTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.ledger = self.root / ".cortex" / "code-workflow" / "progress.jsonl"
        self.history = self.root / ".cortex" / "code-workflow" / "history.jsonl"
        self.wt = str(self.root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _complete_todo(self, todo_id: str) -> None:
        for stage in ("test_write", "verify_red", "implement", "verify_green"):
            run("mark", "--worktree", self.wt, "--id", todo_id, "--stage", stage)

    def test_init_add_mark_show_next(self) -> None:
        out = run(
            "init",
            "--worktree",
            self.wt,
            "--goal",
            "ship X",
            "--constraint",
            "no commit",
        )
        self.assertTrue(json.loads(out.stdout)["ok"])
        self.assertTrue(self.ledger.exists())

        run(
            "add-todo",
            "--worktree",
            self.wt,
            "--id",
            "T1",
            "--title",
            "add resolver",
            "--brief",
            "/tmp/T1.md",
        )
        run(
            "add-todo",
            "--worktree",
            self.wt,
            "--id",
            "T2",
            "--title",
            "wire tool",
        )

        run(
            "mark",
            "--worktree",
            self.wt,
            "--id",
            "T1",
            "--stage",
            "test_write",
            "--stage-status",
            "in_progress",
        )
        nxt = json.loads(run("next", "--worktree", self.wt).stdout)
        self.assertEqual(nxt["id"], "T1")
        self.assertEqual(nxt["stage"], "test_write")

        run(
            "mark",
            "--worktree",
            self.wt,
            "--id",
            "T1",
            "--stage",
            "test_write",
            "--artifact",
            "/tmp/T1-test.md",
        )
        run("mark", "--worktree", self.wt, "--id", "T1", "--stage", "verify_red")
        run("mark", "--worktree", self.wt, "--id", "T1", "--stage", "implement")
        run("mark", "--worktree", self.wt, "--id", "T1", "--stage", "verify_green")

        view = json.loads(run("show", "--worktree", self.wt, "--json").stdout)
        self.assertEqual(view["goal"], "ship X")
        self.assertEqual(view["constraints"], ["no commit"])
        t1 = view["todos"][0]
        self.assertEqual(t1["id"], "T1")
        self.assertEqual(t1["status"], "done")
        self.assertEqual(t1["stages"]["test_write"], "done")
        self.assertEqual(t1["artifacts"]["test_writer_report"], "/tmp/T1-test.md")

        nxt = json.loads(run("next", "--worktree", self.wt).stdout)
        self.assertEqual(nxt["id"], "T2")
        self.assertEqual(nxt["stage"], "test_write")

    def test_mark_blocked_surfaces_in_next(self) -> None:
        run("init", "--worktree", self.wt, "--goal", "g")
        run("add-todo", "--worktree", self.wt, "--id", "T1", "--title", "a")
        run(
            "mark",
            "--worktree",
            self.wt,
            "--id",
            "T1",
            "--stage",
            "test_write",
            "--stage-status",
            "blocked",
            "--note",
            "model missing",
        )
        nxt = json.loads(run("next", "--worktree", self.wt).stdout)
        self.assertEqual(nxt["status"], "blocked")
        self.assertEqual(nxt["id"], "T1")

    def test_set_plan_and_mark_run(self) -> None:
        run("init", "--worktree", self.wt, "--goal", "g")
        run(
            "set-plan",
            "--worktree",
            self.wt,
            "--plan",
            "/tmp/plan.md",
            "--mark-done",
        )
        view = json.loads(run("show", "--worktree", self.wt, "--json").stdout)
        self.assertEqual(view["plan"], "/tmp/plan.md")
        self.assertEqual(view["run"]["plan"], "done")
        self.assertEqual(view["run"]["preflight"], "done")

    def test_duplicate_todo_fails_without_force(self) -> None:
        run("init", "--worktree", self.wt, "--goal", "g")
        run("add-todo", "--worktree", self.wt, "--id", "T1", "--title", "a")
        bad = run(
            "add-todo",
            "--worktree",
            self.wt,
            "--id",
            "T1",
            "--title",
            "b",
            check=False,
        )
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn("already exists", bad.stderr)

    def test_ledger_is_jsonl(self) -> None:
        run("init", "--worktree", self.wt, "--goal", "g")
        run("add-todo", "--worktree", self.wt, "--id", "T1", "--title", "a")
        run(
            "mark",
            "--worktree",
            self.wt,
            "--id",
            "T1",
            "--status",
            "in_progress",
        )
        lines = self.ledger.read_text(encoding="utf-8").strip().splitlines()
        self.assertGreaterEqual(len(lines), 3)
        ops = [json.loads(line)["op"] for line in lines]
        self.assertEqual(ops[0], "init")
        self.assertIn("add-todo", ops)
        self.assertIn("mark", ops)

    def test_self_gitignore_created(self) -> None:
        run("init", "--worktree", self.wt, "--goal", "g")
        gi = self.root / ".cortex" / ".gitignore"
        self.assertTrue(gi.exists())
        text = gi.read_text(encoding="utf-8")
        self.assertIn("*", text)
        self.assertIn("!.gitignore", text)

    def test_compact_archives_done_keeps_active(self) -> None:
        run("init", "--worktree", self.wt, "--goal", "ship X")
        run(
            "set-plan",
            "--worktree",
            self.wt,
            "--plan",
            "/tmp/plan.md",
            "--mark-done",
        )
        run("add-todo", "--worktree", self.wt, "--id", "T1", "--title", "done one")
        run("add-todo", "--worktree", self.wt, "--id", "T2", "--title", "pending one")
        self._complete_todo("T1")

        out = json.loads(run("compact", "--worktree", self.wt).stdout)
        self.assertTrue(out["ok"])
        self.assertEqual(out["archived_todos"], 1)
        self.assertEqual(out["active_todos"], 1)
        self.assertEqual(out["events_after"], 1)
        self.assertEqual(Path(out["progress"]), self.ledger)
        self.assertEqual(Path(out["history"]), self.history)

        view = json.loads(run("show", "--worktree", self.wt, "--json").stdout)
        self.assertEqual([t["id"] for t in view["todos"]], ["T2"])
        self.assertEqual(view["todos"][0]["status"], "pending")
        self.assertEqual(view["goal"], "ship X")
        self.assertEqual(view["plan"], "/tmp/plan.md")

        self.assertTrue(self.history.exists())
        archive = json.loads(self.history.read_text(encoding="utf-8").strip())
        self.assertEqual(archive["op"], "archive")
        self.assertEqual(archive["reason"], "compact")
        self.assertEqual([t["id"] for t in archive["todos"]], ["T1"])
        self.assertEqual(archive["todos"][0]["status"], "done")

        nxt = json.loads(run("next", "--worktree", self.wt).stdout)
        self.assertEqual(nxt["id"], "T2")
        self.assertEqual(nxt["stage"], "test_write")

        lines = self.ledger.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0])["op"], "snapshot")

    def test_fold_snapshot_equals_pre_compact_active_state(self) -> None:
        progress = load_progress()
        run("init", "--worktree", self.wt, "--goal", "g")
        run("add-todo", "--worktree", self.wt, "--id", "T1", "--title", "a")
        run("add-todo", "--worktree", self.wt, "--id", "T2", "--title", "b")
        self._complete_todo("T1")

        before = progress.fold(progress.read_events(self.ledger))
        active_ids = [
            tid
            for tid in before["todo_order"]
            if before["todos"][tid]["status"] not in ("done", "skipped")
        ]
        expected = {
            "goal": before["goal"],
            "worktree": before["worktree"],
            "plan": before["plan"],
            "constraints": before["constraints"],
            "run": before["run"],
            "todo_order": active_ids,
            "todos": {tid: before["todos"][tid] for tid in active_ids},
        }

        run("compact", "--worktree", self.wt)
        after = progress.fold(progress.read_events(self.ledger))
        self.assertEqual(after["goal"], expected["goal"])
        self.assertEqual(after["worktree"], expected["worktree"])
        self.assertEqual(after["plan"], expected["plan"])
        self.assertEqual(after["constraints"], expected["constraints"])
        self.assertEqual(after["run"], expected["run"])
        self.assertEqual(after["todo_order"], expected["todo_order"])
        self.assertEqual(after["todos"], expected["todos"])

    def test_force_init_after_snapshot_resets_run_state(self) -> None:
        """Forced init after compact must start a genuinely fresh run.

        Fold sees snapshot then init; init must clear prior direction/plan/
        todos and apply the new init's run statuses (preflight done).
        """
        direction = self.root / "direction.md"
        direction.write_text("# direction\n", encoding="utf-8")

        run("init", "--worktree", self.wt, "--goal", "old goal")
        run(
            "set-direction",
            "--worktree",
            self.wt,
            "--file",
            str(direction),
        )
        run(
            "set-plan",
            "--worktree",
            self.wt,
            "--plan",
            "/tmp/old-plan.md",
            "--mark-done",
        )
        run("add-todo", "--worktree", self.wt, "--id", "T1", "--title", "old todo")
        self._complete_todo("T1")
        run("compact", "--worktree", self.wt)

        before_lines = [
            ln for ln in self.ledger.read_text(encoding="utf-8").splitlines() if ln.strip()
        ]
        self.assertEqual(len(before_lines), 1)
        self.assertEqual(json.loads(before_lines[0])["op"], "snapshot")

        out = json.loads(
            run(
                "init",
                "--worktree",
                self.wt,
                "--goal",
                "new goal",
                "--force",
            ).stdout
        )
        self.assertTrue(out["ok"])

        # Append-only: snapshot remains; new init is appended.
        after_lines = [
            ln for ln in self.ledger.read_text(encoding="utf-8").splitlines() if ln.strip()
        ]
        self.assertEqual(len(after_lines), 2)
        self.assertEqual(json.loads(after_lines[0])["op"], "snapshot")
        self.assertEqual(json.loads(after_lines[1])["op"], "init")

        view = json.loads(run("show", "--worktree", self.wt, "--json").stdout)
        self.assertEqual(view["goal"], "new goal")
        self.assertEqual(view["plan"], "")
        self.assertEqual(view["direction"], "")
        self.assertFalse(view["direction_confirmed"])
        self.assertEqual(view["todos"], [])
        self.assertEqual(
            view["run"],
            {"preflight": "done", "plan": "pending", "closeout": "pending"},
        )

    def test_compact_idempotent_skips_empty_archive(self) -> None:
        run("init", "--worktree", self.wt, "--goal", "g")
        run("add-todo", "--worktree", self.wt, "--id", "T1", "--title", "a")
        run("add-todo", "--worktree", self.wt, "--id", "T2", "--title", "b")
        self._complete_todo("T1")
        run("compact", "--worktree", self.wt)

        history_before = self.history.read_text(encoding="utf-8")
        history_lines_before = [
            ln for ln in history_before.splitlines() if ln.strip()
        ]
        progress_before = self.ledger.read_text(encoding="utf-8")

        out = json.loads(run("compact", "--worktree", self.wt).stdout)
        self.assertTrue(out["ok"])
        self.assertEqual(out["archived_todos"], 0)
        self.assertEqual(out["active_todos"], 1)
        self.assertEqual(out["events_before"], 1)
        self.assertEqual(out["events_after"], 1)

        history_after_lines = [
            ln
            for ln in self.history.read_text(encoding="utf-8").splitlines()
            if ln.strip()
        ]
        self.assertEqual(history_after_lines, history_lines_before)

        progress_after = self.ledger.read_text(encoding="utf-8")
        snap = json.loads(progress_after.strip())
        self.assertEqual(snap["op"], "snapshot")
        self.assertEqual([t["id"] for t in snap["todos"]], ["T2"])
        # Content equivalent (ts may change); still a single-line snapshot.
        self.assertEqual(len(progress_after.strip().splitlines()), 1)
        self.assertEqual(
            len(progress_before.strip().splitlines()),
            len(progress_after.strip().splitlines()),
        )


if __name__ == "__main__":
    unittest.main()
