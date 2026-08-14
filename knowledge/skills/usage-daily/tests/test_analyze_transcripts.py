#!/usr/bin/env python3
"""RED tests for usage-daily analyze_transcripts discovery + fixtures.

Locks resolve_transcripts_root contract and existing categorize/scan/json APIs.
Run: python3 knowledge/skills/usage-daily/tests/test_analyze_transcripts.py
"""

from __future__ import annotations

import importlib.util
import io
import os
import shutil
import tempfile
import time
import unittest
from contextlib import redirect_stderr
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "analyze_transcripts.py"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "transcripts"

EXPECTED_JSON_TOP_KEYS = {
    "generated_at",
    "window_hours",
    "totals",
    "sessions",
    "top_sessions",
    "top_subagents",
}


def load_module():
    spec = importlib.util.spec_from_file_location("usage_daily_analyze", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class ResolveTranscriptsRootTests(unittest.TestCase):
    """Discovery matrix for resolve_transcripts_root(explicit, env, home, cwd)."""

    def setUp(self) -> None:
        self.mod = load_module()
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / "home"
        self.home.mkdir()
        self.projects = self.home / ".cursor" / "projects"
        self.projects.mkdir(parents=True)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _make_transcripts(self, project_slug: str) -> Path:
        root = self.projects / project_slug / "agent-transcripts"
        root.mkdir(parents=True)
        return root

    def test_explicit_wins_over_env_and_glob(self) -> None:
        glob_root = self._make_transcripts("Users-acme-repo")
        env_root = self.home / "env-root"
        env_root.mkdir()
        explicit = self.home / "explicit-root"
        explicit.mkdir()
        cwd = Path("/Users/acme/repo")
        got = self.mod.resolve_transcripts_root(
            explicit,
            {"CURSOR_TRANSCRIPTS_ROOT": str(env_root)},
            self.home,
            cwd,
        )
        self.assertEqual(Path(got), explicit)
        self.assertNotEqual(Path(got), env_root)
        self.assertNotEqual(Path(got), glob_root)

    def test_env_wins_over_glob(self) -> None:
        self._make_transcripts("Users-acme-repo")
        env_root = self.home / "from-env"
        env_root.mkdir()
        cwd = Path("/Users/acme/repo")
        got = self.mod.resolve_transcripts_root(
            None,
            {"CURSOR_TRANSCRIPTS_ROOT": str(env_root)},
            self.home,
            cwd,
        )
        self.assertEqual(Path(got), env_root)

    def test_zero_glob_matches_exits_1(self) -> None:
        # no agent-transcripts dirs under home/.cursor/projects
        stderr = io.StringIO()
        with redirect_stderr(stderr), self.assertRaises(SystemExit) as cm:
            self.mod.resolve_transcripts_root(
                None, {}, self.home, Path("/Users/acme/repo")
            )
        self.assertEqual(cm.exception.code, 1)
        self.assertTrue(stderr.getvalue().strip())

    def test_one_glob_match_used(self) -> None:
        only = self._make_transcripts("Only-Project")
        got = self.mod.resolve_transcripts_root(
            None, {}, self.home, Path("/somewhere/else")
        )
        self.assertEqual(Path(got), only)

    def test_many_glob_slug_match(self) -> None:
        match = self._make_transcripts("Users-acme-Documents-my-repo")
        self._make_transcripts("Users-other-Documents-other-repo")
        cwd = Path("/Users/acme/Documents/my-repo")
        got = self.mod.resolve_transcripts_root(None, {}, self.home, cwd)
        self.assertEqual(Path(got), match)

    def test_many_glob_no_slug_match_exits_1_lists_candidates(self) -> None:
        a = self._make_transcripts("Project-A")
        b = self._make_transcripts("Project-B")
        stderr = io.StringIO()
        with redirect_stderr(stderr), self.assertRaises(SystemExit) as cm:
            self.mod.resolve_transcripts_root(
                None, {}, self.home, Path("/Users/acme/Documents/unrelated")
            )
        self.assertEqual(cm.exception.code, 1)
        err = stderr.getvalue()
        self.assertIn(str(a), err)
        self.assertIn(str(b), err)


class CategorizeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = load_module()

    def test_medeo_dev_boundary(self) -> None:
        self.assertEqual(self.mod.categorize("please use medeo-dev skill"), "medeo-dev")
        self.assertEqual(self.mod.categorize("open Medeo Dev dashboard"), "medeo-dev")

    def test_mcap_lane_boundary(self) -> None:
        self.assertEqual(
            self.mod.categorize("run mcap-lane-model-test on stg"),
            "mcap-lane-model-test",
        )
        self.assertEqual(
            self.mod.categorize("mcap_lane_model_test probe"),
            "mcap-lane-model-test",
        )
        self.assertEqual(
            self.mod.categorize("grpc-execute against swim lane"),
            "mcap-lane-model-test",
        )

    def test_code_workflow_boundary(self) -> None:
        self.assertEqual(self.mod.categorize("start code-workflow"), "code-workflow")
        self.assertEqual(self.mod.categorize("implement green next"), "code-workflow")
        self.assertEqual(self.mod.categorize("test write stage"), "code-workflow")
        self.assertEqual(self.mod.categorize("verify red then verify green"), "code-workflow")
        self.assertEqual(self.mod.categorize("plan 阶段 kickoff"), "code-workflow")
        self.assertEqual(self.mod.categorize("fast lane change"), "code-workflow")

    def test_other_fallback(self) -> None:
        self.assertEqual(self.mod.categorize("write a haiku about rain"), "other")


class ScanFixtureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = load_module()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "transcripts"
        shutil.copytree(FIXTURES, self.root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_scan_time_window_filters_old_session(self) -> None:
        now = time.time()
        new_main = self.root / "sess-new" / "sess-new.jsonl"
        old_main = self.root / "sess-old" / "sess-old.jsonl"
        os.utime(new_main, (now, now))
        os.utime(old_main, (now - 10 * 3600, now - 10 * 3600))

        sessions = self.mod.scan(self.root, hours=2.0)
        ids = {s["session"] for s in sessions}
        self.assertIn("sess-new", ids)
        self.assertNotIn("sess-old", ids)

    def test_scan_includes_categorized_subagents_from_fixtures(self) -> None:
        now = time.time()
        os.utime(self.root / "sess-new" / "sess-new.jsonl", (now, now))
        sessions = self.mod.scan(self.root, hours=1.0)
        by_id = {s["session"]: s for s in sessions}
        self.assertIn("sess-new", by_id)
        cats = {sub["category"] for sub in by_id["sess-new"]["subagents"]}
        self.assertEqual(
            cats,
            {"medeo-dev", "mcap-lane-model-test", "code-workflow", "other"},
        )


class BuildJsonPayloadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = load_module()
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "transcripts"
        shutil.copytree(FIXTURES, self.root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_payload_key_stability_on_fixture_scan(self) -> None:
        now = time.time()
        os.utime(self.root / "sess-new" / "sess-new.jsonl", (now, now))
        sessions = self.mod.scan(self.root, hours=24.0)
        self.assertTrue(any(s["session"] == "sess-new" for s in sessions))
        totals = self.mod.build_totals(sessions)
        tops = self.mod.top_sessions(sessions)
        top_subs = self.mod.top_subagents(sessions)
        payload = self.mod.build_json_payload(
            "2026-08-14T00:00:00+08:00",
            24.0,
            sessions,
            totals,
            tops,
            top_subs,
        )
        self.assertEqual(set(payload.keys()), EXPECTED_JSON_TOP_KEYS)
        self.assertIn("session_count", payload["totals"])
        self.assertIn("category_counts", payload["totals"])
        self.assertIn("category_bytes", payload["totals"])
        sample = next(s for s in payload["sessions"] if s["session"] == "sess-new")
        for key in (
            "session",
            "mtime",
            "mtime_iso",
            "main_bytes",
            "user_turns",
            "sub_count",
            "sub_bytes",
            "total_bytes",
            "category_bytes",
            "category_counts",
            "subagents",
        ):
            self.assertIn(key, sample)


if __name__ == "__main__":
    unittest.main()
