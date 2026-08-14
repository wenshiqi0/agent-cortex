#!/usr/bin/env python3
"""Tests for loop-memory.py — stdlib unittest only.

Every test runs the CLI via subprocess with sys.executable, isolated in a
tempfile.TemporaryDirectory with LOOP_MEMORY_HOME / LOOP_MEMORY_SESSION set
in the child environment.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "loop-memory.py"


class LoopMemoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / "home"
        self.session = "test-session"
        self.session_dir = self.home / self.session

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_cli(
        self, *args: str, check: bool = True, session: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["LOOP_MEMORY_HOME"] = str(self.home)
        env["LOOP_MEMORY_SESSION"] = session if session is not None else self.session
        cmd = [sys.executable, str(SCRIPT), *args]
        return subprocess.run(
            cmd, capture_output=True, text=True, check=check, env=env
        )

    def init_loop(self, loop_id: str = "T1", session: str | None = None) -> dict:
        out = self.run_cli(
            "init",
            loop_id,
            "--repo",
            "medeo-price",
            "--worktree",
            "/tmp/wt",
            "--task",
            "add pricing",
            session=session,
        )
        return json.loads(out.stdout)

    def get_loop(self, loop_id: str = "T1") -> dict:
        return json.loads(self.run_cli("get", loop_id).stdout)

    def loop_file(self, loop_id: str = "T1") -> Path:
        return self.session_dir / f"{loop_id}.json"

    def test_init_creates_loop_file_and_rejects_duplicate(self) -> None:
        ack = self.init_loop("T1")
        self.assertTrue(ack["ok"])
        self.assertEqual(ack["loop_id"], "T1")

        path = self.loop_file("T1")
        self.assertTrue(path.exists())
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["loop_id"], "T1")
        self.assertEqual(data["repo"], "medeo-price")
        self.assertEqual(data["worktree"], "/tmp/wt")
        self.assertEqual(data["task"], "add pricing")
        self.assertTrue(data["created_at"])
        self.assertEqual(data["stages"], {})

        self.assertTrue((self.session_dir / "index.json").exists())

        dup = self.run_cli(
            "init",
            "T1",
            "--repo",
            "medeo-price",
            "--worktree",
            "/tmp/wt",
            "--task",
            "add pricing",
            check=False,
        )
        self.assertNotEqual(dup.returncode, 0)
        self.assertTrue(dup.stderr.strip())

    def test_get_roundtrip_and_missing(self) -> None:
        self.init_loop("T1")
        data = self.get_loop("T1")
        self.assertEqual(data["loop_id"], "T1")
        self.assertEqual(data["repo"], "medeo-price")
        self.assertEqual(data["worktree"], "/tmp/wt")
        self.assertEqual(data["task"], "add pricing")
        self.assertTrue(data["created_at"])
        self.assertEqual(data["stages"], {})

        missing = self.run_cli("get", "NOPE", check=False)
        self.assertEqual(missing.returncode, 1)
        self.assertTrue(missing.stderr.strip())

    def test_put_merge_patch_semantics(self) -> None:
        self.init_loop("T1")
        self.run_cli(
            "put", "T1", "--stage", "WT",
            "--patch", '{"explored": true, "notes": {"a": 1}, "list": [1, 2]}',
        )
        # Nested objects merge recursively.
        self.run_cli(
            "put", "T1", "--stage", "WT", "--patch", '{"notes": {"b": 2}}'
        )
        stage = self.get_loop("T1")["stages"]["WT"]
        self.assertEqual(stage["notes"], {"a": 1, "b": 2})
        self.assertTrue(stage["explored"])

        # null deletes a key.
        self.run_cli(
            "put", "T1", "--stage", "WT", "--patch", '{"notes": {"a": null}}'
        )
        self.assertEqual(self.get_loop("T1")["stages"]["WT"]["notes"], {"b": 2})

        # Arrays/scalars replace wholesale.
        self.run_cli("put", "T1", "--stage", "WT", "--patch", '{"list": [3]}')
        self.assertEqual(self.get_loop("T1")["stages"]["WT"]["list"], [3])

        bad_stage = self.run_cli(
            "put", "T1", "--stage", "BAD", "--patch", "{}", check=False
        )
        self.assertNotEqual(bad_stage.returncode, 0)

        bad_patch = self.run_cli(
            "put", "T1", "--stage", "WT", "--patch", "{not json", check=False
        )
        self.assertNotEqual(bad_patch.returncode, 0)
        self.assertTrue(bad_patch.stderr.strip())

    def test_add_file_keys_dedup_and_validation(self) -> None:
        self.init_loop("T1")
        self.run_cli(
            "add-file", "T1", "--stage", "WT",
            "--path", "src/price.py", "--role", "impl",
            "--symbols", '["PriceCalc"]',
        )
        wt = self.get_loop("T1")["stages"]["WT"]
        self.assertEqual(
            wt["files"],
            [{"path": "src/price.py", "role": "impl", "symbols": ["PriceCalc"]}],
        )

        self.run_cli(
            "add-file", "T1", "--stage", "IMPL",
            "--path", "src/other.py", "--role", "fix",
            "--symbols", '["Other"]',
        )
        impl = self.get_loop("T1")["stages"]["IMPL"]
        self.assertEqual(
            impl["files_touched"],
            [{"path": "src/other.py", "role": "fix", "symbols": ["Other"]}],
        )
        self.assertNotIn("files", impl)

        # Dedup by path: re-adding updates role/symbols in place.
        self.run_cli(
            "add-file", "T1", "--stage", "WT",
            "--path", "src/price.py", "--role", "test",
            "--symbols", '["PriceCalc", "PriceTest"]',
        )
        wt = self.get_loop("T1")["stages"]["WT"]
        self.assertEqual(len(wt["files"]), 1)
        self.assertEqual(wt["files"][0]["role"], "test")
        self.assertEqual(wt["files"][0]["symbols"], ["PriceCalc", "PriceTest"])

        bad_symbols = self.run_cli(
            "add-file", "T1", "--stage", "WT",
            "--path", "src/x.py", "--role", "impl",
            "--symbols", "not-json",
            check=False,
        )
        self.assertNotEqual(bad_symbols.returncode, 0)
        self.assertTrue(bad_symbols.stderr.strip())

        non_array = self.run_cli(
            "add-file", "T1", "--stage", "WT",
            "--path", "src/x.py", "--role", "impl",
            "--symbols", '{"a": 1}',
            check=False,
        )
        self.assertNotEqual(non_array.returncode, 0)

    def test_add_decision_appends_in_order(self) -> None:
        self.init_loop("T1")
        self.run_cli(
            "add-decision", "T1", "--stage", "WT", "--text", "use existing resolver"
        )
        self.run_cli(
            "add-decision", "T1", "--stage", "WT", "--text", "keep schema flat"
        )
        decisions = self.get_loop("T1")["stages"]["WT"]["decisions"]
        self.assertEqual(len(decisions), 2)
        self.assertEqual(decisions[0]["text"], "use existing resolver")
        self.assertEqual(decisions[1]["text"], "keep schema flat")
        for entry in decisions:
            self.assertTrue(entry["ts"])

    def test_set_test_red(self) -> None:
        self.init_loop("T1")
        self.run_cli(
            "set-test", "T1", "--stage", "WT", "--red",
            "--passed", "0", "--failed", "12", "--reason", "no PriceCalc",
        )
        test_red = self.get_loop("T1")["stages"]["WT"]["test_red"]
        self.assertEqual(test_red["passed"], 0)
        self.assertEqual(test_red["failed"], 12)
        self.assertEqual(test_red["reason"], "no PriceCalc")
        self.assertTrue(test_red["ts"])

        no_red = self.run_cli(
            "set-test", "T1", "--stage", "WT",
            "--passed", "0", "--failed", "12", "--reason", "x",
            check=False,
        )
        self.assertNotEqual(no_red.returncode, 0)

    def test_set_verdict(self) -> None:
        self.init_loop("T1")
        self.run_cli(
            "set-verdict", "T1", "--stage", "VER", "--verdict", "GREEN",
            "--test-passed", "12", "--test-failed", "0",
        )
        ver = self.get_loop("T1")["stages"]["VER"]
        self.assertEqual(ver["verdict"], "GREEN")
        self.assertEqual(ver["test_green"]["passed"], 12)
        self.assertEqual(ver["test_green"]["failed"], 0)
        self.assertTrue(ver["test_green"]["ts"])

        bad = self.run_cli(
            "set-verdict", "T1", "--stage", "VER", "--verdict", "YELLOW",
            "--test-passed", "12", "--test-failed", "0",
            check=False,
        )
        self.assertNotEqual(bad.returncode, 0)

    def test_stage_mutation_sets_ended_at(self) -> None:
        self.init_loop("T1")
        mutations = [
            ("put", "T1", "--stage", "WT", "--patch", '{"explored": true}'),
            (
                "add-file", "T1", "--stage", "WT",
                "--path", "src/a.py", "--role", "impl", "--symbols", "[]",
            ),
            ("add-decision", "T1", "--stage", "IMPL", "--text", "d"),
            (
                "set-test", "T1", "--stage", "WT", "--red",
                "--passed", "0", "--failed", "1", "--reason", "r",
            ),
            (
                "set-verdict", "T1", "--stage", "VER", "--verdict", "RED",
                "--test-passed", "0", "--test-failed", "1",
            ),
        ]
        for cmd in mutations:
            self.run_cli(*cmd)
            stage = cmd[3]
            ended = self.get_loop("T1")["stages"][stage].get("ended_at")
            self.assertTrue(ended, f"{cmd[0]} must set stages.{stage}.ended_at")

    def test_snapshot_through_stage_and_out(self) -> None:
        self.init_loop("T1")
        self.run_cli("put", "T1", "--stage", "WT", "--patch", '{"explored": true}')
        self.run_cli(
            "add-decision", "T1", "--stage", "IMPL", "--text", "impl done"
        )
        self.run_cli(
            "set-verdict", "T1", "--stage", "VER", "--verdict", "GREEN",
            "--test-passed", "12", "--test-failed", "0",
        )

        snap = json.loads(
            self.run_cli("snapshot", "T1", "--through-stage", "IMPL").stdout
        )
        self.assertEqual(snap["loop_id"], "T1")
        self.assertEqual(snap["repo"], "medeo-price")
        self.assertEqual(snap["worktree"], "/tmp/wt")
        self.assertEqual(snap["task"], "add pricing")
        self.assertTrue(snap["created_at"])
        self.assertIn("WT", snap["stages"])
        self.assertIn("IMPL", snap["stages"])
        self.assertNotIn("VER", snap["stages"])

        out_path = Path(self.tmp.name) / "snap.json"
        self.run_cli(
            "snapshot", "T1", "--through-stage", "IMPL", "--out", str(out_path)
        )
        self.assertTrue(out_path.exists())
        from_file = json.loads(out_path.read_text(encoding="utf-8"))
        self.assertEqual(from_file, snap)

    def test_list_and_index_rebuild(self) -> None:
        self.init_loop("T1")
        self.init_loop("T2")
        # Write VER before WT so ordering must follow WT -> IMPL -> VER,
        # not insertion order.
        self.run_cli(
            "set-verdict", "T1", "--stage", "VER", "--verdict", "GREEN",
            "--test-passed", "1", "--test-failed", "0",
        )
        self.run_cli("put", "T1", "--stage", "WT", "--patch", '{"explored": true}')

        def listed() -> list:
            return json.loads(self.run_cli("list").stdout)

        loops = {entry["loop_id"]: entry for entry in listed()}
        self.assertEqual(set(loops), {"T1", "T2"})
        t1 = loops["T1"]
        self.assertEqual(t1["repo"], "medeo-price")
        self.assertEqual(t1["task"], "add pricing")
        self.assertTrue(t1["created_at"])
        self.assertTrue(t1["updated_at"])
        self.assertEqual(t1["stages"], ["WT", "VER"])
        self.assertEqual(loops["T2"]["stages"], [])

        # Rebuild path: deleting index.json must not break list.
        (self.session_dir / "index.json").unlink()
        loops = {entry["loop_id"]: entry for entry in listed()}
        self.assertEqual(set(loops), {"T1", "T2"})
        self.assertEqual(loops["T1"]["stages"], ["WT", "VER"])

    def test_session_isolation(self) -> None:
        self.init_loop("T1", session="session-a")

        other = json.loads(self.run_cli("list", session="session-b").stdout)
        self.assertEqual(other, [])
        missing = self.run_cli("get", "T1", check=False, session="session-b")
        self.assertEqual(missing.returncode, 1)

        # Same loop_id in another session is an independent loop.
        ack = self.init_loop("T1", session="session-b")
        self.assertTrue(ack["ok"])
        a = json.loads(self.run_cli("list", session="session-a").stdout)
        b = json.loads(self.run_cli("list", session="session-b").stdout)
        self.assertEqual([e["loop_id"] for e in a], ["T1"])
        self.assertEqual([e["loop_id"] for e in b], ["T1"])

    def test_archive(self) -> None:
        self.init_loop("T1")
        self.run_cli("put", "T1", "--stage", "WT", "--patch", '{"explored": true}')
        before = self.get_loop("T1")

        dest = Path(self.tmp.name) / "archived"
        ack = json.loads(self.run_cli("archive", "T1", "--to", str(dest)).stdout)
        self.assertTrue(ack["ok"])

        copied = dest / "T1.json"
        self.assertTrue(copied.exists())
        self.assertEqual(json.loads(copied.read_text(encoding="utf-8")), before)
        self.assertFalse(self.loop_file("T1").exists())

        loops = json.loads(self.run_cli("list").stdout)
        self.assertNotIn("T1", [e["loop_id"] for e in loops])

        gone = self.run_cli("get", "T1", check=False)
        self.assertEqual(gone.returncode, 1)

        missing = self.run_cli("archive", "NOPE", "--to", str(dest), check=False)
        self.assertEqual(missing.returncode, 1)


class DoctorTests(unittest.TestCase):
    """Read-only `doctor` CLI — validates index/file consistency."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / "home"
        self.session = "test-session"
        self.session_dir = self.home / self.session

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_cli(
        self, *args: str, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["LOOP_MEMORY_HOME"] = str(self.home)
        env["LOOP_MEMORY_SESSION"] = self.session
        cmd = [sys.executable, str(SCRIPT), *args]
        return subprocess.run(
            cmd, capture_output=True, text=True, check=check, env=env
        )

    def init_loop(self, loop_id: str = "T1") -> dict:
        out = self.run_cli(
            "init",
            loop_id,
            "--repo",
            "medeo-price",
            "--worktree",
            "/tmp/wt",
            "--task",
            "add pricing",
        )
        return json.loads(out.stdout)

    def loop_file(self, loop_id: str = "T1") -> Path:
        return self.session_dir / f"{loop_id}.json"

    def index_file(self) -> Path:
        return self.session_dir / "index.json"

    def _snapshot_home(self) -> dict[str, str]:
        """Path -> content for every file under the session home."""
        out: dict[str, str] = {}
        if not self.session_dir.exists():
            return out
        for path in sorted(self.session_dir.rglob("*")):
            if path.is_file():
                out[str(path.relative_to(self.session_dir))] = path.read_text(
                    encoding="utf-8"
                )
        return out

    def _assert_text_status_lines(self, stdout: str) -> list[str]:
        lines = [ln for ln in stdout.splitlines() if ln.strip()]
        self.assertTrue(lines, f"doctor text output empty:\n{stdout!r}")
        for line in lines:
            self.assertRegex(
                line,
                r"^(OK|WARN|FAIL) \S+ .+",
                msg=f"bad doctor line: {line!r}",
            )
        return lines

    def _assert_json_payload(
        self, stdout: str, *, expect_ok: bool
    ) -> dict:
        payload = json.loads(stdout)
        self.assertIsInstance(payload, dict)
        self.assertEqual(set(payload.keys()) & {"checks", "ok"}, {"checks", "ok"})
        self.assertIsInstance(payload["checks"], list)
        self.assertIsInstance(payload["ok"], bool)
        self.assertEqual(payload["ok"], expect_ok)
        return payload

    def test_doctor_corrupt_index_exits_1(self) -> None:
        self.session_dir.mkdir(parents=True)
        self.index_file().write_text("{not-json", encoding="utf-8")
        before = self._snapshot_home()

        proc = self.run_cli("doctor", check=False)
        self.assertEqual(proc.returncode, 1, msg=proc.stdout + proc.stderr)
        lines = self._assert_text_status_lines(proc.stdout)
        self.assertTrue(
            any(ln.startswith("FAIL ") for ln in lines),
            f"expected FAIL line: {proc.stdout}",
        )

        json_proc = self.run_cli("doctor", "--json", check=False)
        self.assertEqual(json_proc.returncode, 1, msg=json_proc.stdout + json_proc.stderr)
        self._assert_json_payload(json_proc.stdout, expect_ok=False)

        self.assertEqual(self._snapshot_home(), before, "doctor must be read-only")

    def test_doctor_missing_indexed_loop_file_exits_1(self) -> None:
        self.init_loop("T1")
        self.loop_file("T1").unlink()
        before = self._snapshot_home()

        proc = self.run_cli("doctor", check=False)
        self.assertEqual(proc.returncode, 1, msg=proc.stdout + proc.stderr)
        lines = self._assert_text_status_lines(proc.stdout)
        self.assertTrue(
            any(ln.startswith("FAIL ") for ln in lines),
            f"expected FAIL line: {proc.stdout}",
        )

        json_proc = self.run_cli("doctor", "--json", check=False)
        self.assertEqual(json_proc.returncode, 1)
        self._assert_json_payload(json_proc.stdout, expect_ok=False)

        self.assertEqual(self._snapshot_home(), before, "doctor must be read-only")

    def test_doctor_bad_stage_key_exits_1(self) -> None:
        self.init_loop("T1")
        path = self.loop_file("T1")
        data = json.loads(path.read_text(encoding="utf-8"))
        data.setdefault("stages", {})["BAD"] = {"notes": "invalid stage"}
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        before = self._snapshot_home()

        proc = self.run_cli("doctor", check=False)
        self.assertEqual(proc.returncode, 1, msg=proc.stdout + proc.stderr)
        lines = self._assert_text_status_lines(proc.stdout)
        self.assertTrue(
            any(ln.startswith("FAIL ") for ln in lines),
            f"expected FAIL line: {proc.stdout}",
        )

        self.assertEqual(self._snapshot_home(), before, "doctor must be read-only")

    def test_doctor_orphan_loop_file_warns_exit_0(self) -> None:
        self.init_loop("T1")
        orphan = self.session_dir / "ORPHAN.json"
        orphan.write_text(
            json.dumps(
                {
                    "loop_id": "ORPHAN",
                    "repo": "medeo-price",
                    "worktree": "/tmp/wt",
                    "task": "orphan task",
                    "created_at": "2026-01-01T00:00:00Z",
                    "stages": {},
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        before = self._snapshot_home()

        proc = self.run_cli("doctor", check=False)
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
        lines = self._assert_text_status_lines(proc.stdout)
        self.assertTrue(
            any(ln.startswith("WARN ") for ln in lines),
            f"expected WARN line for orphan: {proc.stdout}",
        )
        self.assertFalse(
            any(ln.startswith("FAIL ") for ln in lines),
            f"orphan must not FAIL: {proc.stdout}",
        )

        json_proc = self.run_cli("doctor", "--json", check=False)
        self.assertEqual(json_proc.returncode, 0)
        payload = self._assert_json_payload(json_proc.stdout, expect_ok=True)
        self.assertTrue(payload["checks"], "json checks should be non-empty")

        self.assertEqual(self._snapshot_home(), before, "doctor must be read-only")

    def test_doctor_healthy_home_exits_0(self) -> None:
        self.init_loop("T1")
        self.run_cli(
            "put", "T1", "--stage", "WT", "--patch", '{"explored": true}'
        )
        before = self._snapshot_home()

        proc = self.run_cli("doctor", check=False)
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + proc.stderr)
        lines = self._assert_text_status_lines(proc.stdout)
        self.assertTrue(
            any(ln.startswith("OK ") for ln in lines),
            f"expected OK line: {proc.stdout}",
        )
        self.assertFalse(
            any(ln.startswith("FAIL ") for ln in lines),
            f"healthy home must not FAIL: {proc.stdout}",
        )

        json_proc = self.run_cli("doctor", "--json", check=False)
        self.assertEqual(json_proc.returncode, 0, msg=json_proc.stdout + json_proc.stderr)
        self._assert_json_payload(json_proc.stdout, expect_ok=True)

        self.assertEqual(self._snapshot_home(), before, "doctor must be read-only")


if __name__ == "__main__":
    unittest.main()
