"""Thin contract tests for code-workflow SKILL.md and README.md.

No markdown-section slicing; only existence, line cap, required keywords,
and absence of model/fallback/slug tokens.
"""

from __future__ import annotations

import unittest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
SKILL = SKILL_DIR / "SKILL.md"
README = SKILL_DIR / "README.md"

REQUIRED = (
    "workflow.py",
    "Fast Lane",
    "Full Loop",
    "confirm-direction",
    "protocol-blind",
    "code-workflow-planner",
    "code-workflow-planner-backup",
    "code-workflow-test-writer",
    "code-workflow-implementer",
    "code-workflow-verifier",
    "code-workflow-prose-editor",
    "doctor",
    "test",
    "--verify-cmd",
)

README_REQUIRED = (
    "workflow.py",
    "Fast Lane",
    ".cortex",
    "next --json",
    "ARTIFACT_POLICY",
    "code-workflow-planner",
    "code-workflow-planner-backup",
    "code-workflow-test-writer",
    "code-workflow-implementer",
    "code-workflow-verifier",
    "code-workflow-prose-editor",
)

FORBIDDEN = (
    "model",
    "fallback",
    "kimi-k3-max",
    "cursor-grok-4.5-high",
    "composer-2.5-fast",
    "gpt-5.6-sol-medium",
)


class TestSkillContract(unittest.TestCase):
    def test_skill_exists_and_under_line_cap(self) -> None:
        self.assertTrue(SKILL.exists(), f"missing {SKILL}")
        text = SKILL.read_text(encoding="utf-8")
        lines = text.splitlines()
        self.assertLessEqual(len(lines), 120, f"SKILL.md is {len(lines)} lines; cap is 120")

    def test_required_keywords(self) -> None:
        text = SKILL.read_text(encoding="utf-8")
        for needle in REQUIRED:
            with self.subTest(needle=needle):
                self.assertIn(needle, text)

    def test_protocol_blind_boundary_statement(self) -> None:
        text = SKILL.read_text(encoding="utf-8").lower()
        self.assertIn("protocol-blind", text)

    def test_no_model_fallback_or_known_slugs(self) -> None:
        text = SKILL.read_text(encoding="utf-8")
        lower = text.lower()
        for needle in FORBIDDEN:
            with self.subTest(needle=needle):
                self.assertNotIn(needle.lower(), lower)

    def test_readme_exists_with_required_needles(self) -> None:
        self.assertTrue(README.is_file(), f"missing {README}")
        text = README.read_text(encoding="utf-8")
        for needle in README_REQUIRED:
            with self.subTest(needle=needle):
                self.assertIn(needle, text)

    def test_readme_no_model_slugs(self) -> None:
        text = README.read_text(encoding="utf-8")
        lower = text.lower()
        for needle in FORBIDDEN:
            with self.subTest(needle=needle):
                self.assertNotIn(needle.lower(), lower)


if __name__ == "__main__":
    unittest.main()
