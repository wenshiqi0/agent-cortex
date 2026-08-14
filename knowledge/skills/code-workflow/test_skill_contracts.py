"""Thin contract tests for code-workflow SKILL.md.

No markdown-section slicing; only existence, line cap, required keywords,
and primary-before-fallback model priority for code-writing roles.
"""

import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parent / "SKILL.md"
K3 = "kimi-k3-max"
GROK = "cursor-grok-4.5-high"


class TestSkillContract(unittest.TestCase):
    def test_skill_exists_and_under_line_cap(self) -> None:
        self.assertTrue(SKILL.exists(), f"missing {SKILL}")
        text = SKILL.read_text(encoding="utf-8")
        lines = text.splitlines()
        self.assertLessEqual(len(lines), 120, f"SKILL.md is {len(lines)} lines; cap is 120")

    def test_required_keywords(self) -> None:
        text = SKILL.read_text(encoding="utf-8")
        for needle in (
            "workflow.py",
            "Fast Lane",
            "Full Loop",
            "confirm-direction",
            GROK,
            K3,
            "fallback",
        ):
            with self.subTest(needle=needle):
                self.assertIn(needle, text)

    def test_protocol_blind_boundary_statement(self) -> None:
        text = SKILL.read_text(encoding="utf-8").lower()
        self.assertIn("protocol-blind", text)

    def test_code_roles_k3_primary_before_grok_fallback(self) -> None:
        """Code-writing roles: K3 appears before Grok; fallback is mentioned."""
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn("fallback", text.lower())
        k3_pos = text.find(K3)
        grok_pos = text.find(GROK)
        self.assertNotEqual(k3_pos, -1, f"missing primary slug {K3}")
        self.assertNotEqual(grok_pos, -1, f"missing fallback slug {GROK}")
        self.assertLess(
            k3_pos,
            grok_pos,
            f"expected {K3} (primary) before {GROK} (fallback) in SKILL.md",
        )


if __name__ == "__main__":
    unittest.main()
