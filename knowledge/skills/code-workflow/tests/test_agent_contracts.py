"""Contract tests for code-workflow role agents under knowledge/agents/.

Stdlib unittest only. Frontmatter parsed with regex (no YAML dependency).
Protocol-blind body checks apply only to content after the closing ---.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
AGENTS_DIR = REPO_ROOT / "knowledge" / "agents"
CURSOR_AGENTS = REPO_ROOT / ".cursor" / "agents"
AGENTS_MD = REPO_ROOT / "knowledge" / "AGENTS.md"
WORKFLOW_PY = REPO_ROOT / "knowledge" / "skills" / "code-workflow" / "scripts" / "workflow.py"

KNOWN_SLUGS = (
    "kimi-k3-max",
    "cursor-grok-4.5-high",
    "composer-2.5-fast",
    "gpt-5.6-sol-medium",
)

AGENT_MODELS = {
    "code-workflow-planner": "kimi-k3-max",
    "code-workflow-planner-backup": "gpt-5.6-sol-medium",
    "code-workflow-test-writer": "cursor-grok-4.5-high",
    "code-workflow-implementer": "cursor-grok-4.5-high",
    "code-workflow-verifier": "composer-2.5-fast",
    "code-workflow-prose-editor": "kimi-k3-max",
}

BODY_FORBIDDEN = (
    "workflow.py",
    "progress.jsonl",
    "loop-memory",
    "code-workflow",
    "test_write",
    "verify_red",
    "verify_green",
    *KNOWN_SLUGS,
)

# Stable keyword needles for per-role edit restrictions (exact wording free).
EDIT_NEEDLES = {
    "code-workflow-planner": ("plan", "brief"),
    "code-workflow-planner-backup": ("plan", "brief"),
    "code-workflow-test-writer": ("test", "production"),
    "code-workflow-implementer": ("scope", "weaken"),
    "code-workflow-verifier": ("read-only", "never"),
    "code-workflow-prose-editor": ("list", "behavior"),
}

ARTIFACT_POLICY_STRINGS = (
    "write required outputs only to caller-given paths",
    "put transient evidence only in artifact_dir",
    "never create repo-root artifacts/",
    "never persist secrets",
)

AGENT_LINE_CAP = 40

FRONTMATTER_RE = re.compile(
    r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z",
    re.DOTALL,
)


def split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    match = FRONTMATTER_RE.match(text)
    if not match:
        raise AssertionError("missing or malformed YAML frontmatter --- block")
    raw, body = match.group(1), match.group(2)
    fields: dict[str, str] = {}
    for line in raw.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields, body


class TestAgentContracts(unittest.TestCase):
    def test_role_agent_files_exist(self) -> None:
        for name in AGENT_MODELS:
            path = AGENTS_DIR / f"{name}.md"
            with self.subTest(name=name):
                self.assertTrue(path.is_file(), f"missing {path}")

    def test_frontmatter_mapping(self) -> None:
        for name, expected_model in AGENT_MODELS.items():
            path = AGENTS_DIR / f"{name}.md"
            with self.subTest(name=name):
                self.assertTrue(path.is_file(), f"missing {path}")
                text = path.read_text(encoding="utf-8")
                fields, _body = split_frontmatter(text)
                self.assertEqual(fields.get("name"), name)
                self.assertTrue(fields.get("description"), "description must be non-empty")
                self.assertTrue(fields.get("tools"), "tools must be non-empty")
                self.assertEqual(fields.get("model"), expected_model)

    def test_bodies_protocol_blind(self) -> None:
        for name in AGENT_MODELS:
            path = AGENTS_DIR / f"{name}.md"
            with self.subTest(name=name):
                self.assertTrue(path.is_file(), f"missing {path}")
                _fields, body = split_frontmatter(path.read_text(encoding="utf-8"))
                for needle in BODY_FORBIDDEN:
                    self.assertNotIn(needle, body, f"{name} body contains {needle!r}")

    def test_bodies_state_edit_restrictions(self) -> None:
        for name, needles in EDIT_NEEDLES.items():
            path = AGENTS_DIR / f"{name}.md"
            with self.subTest(name=name):
                self.assertTrue(path.is_file(), f"missing {path}")
                _fields, body = split_frontmatter(path.read_text(encoding="utf-8"))
                lower = body.lower()
                for needle in needles:
                    self.assertIn(needle.lower(), lower, f"{name} body missing {needle!r}")

    def test_agents_md_and_workflow_slug_free(self) -> None:
        agents_text = AGENTS_MD.read_text(encoding="utf-8")
        workflow_text = WORKFLOW_PY.read_text(encoding="utf-8")
        for slug in KNOWN_SLUGS:
            with self.subTest(slug=slug, file="AGENTS.md"):
                self.assertNotIn(slug, agents_text)
            with self.subTest(slug=slug, file="workflow.py"):
                self.assertNotIn(slug, workflow_text)
        self.assertNotIn("fallback_models", workflow_text)

    def test_cursor_agent_links_match_source(self) -> None:
        for name in AGENT_MODELS:
            source = AGENTS_DIR / f"{name}.md"
            linked = CURSOR_AGENTS / f"{name}.md"
            with self.subTest(name=name):
                self.assertTrue(linked.is_file() or linked.is_symlink(), f"missing {linked}")
                self.assertTrue(linked.exists(), f"unreadable/broken link {linked}")
                self.assertEqual(
                    linked.read_text(encoding="utf-8"),
                    source.read_text(encoding="utf-8"),
                    f"{linked} content != {source}",
                )

    def test_agent_bodies_under_line_cap_without_artifacts_section(self) -> None:
        for name in AGENT_MODELS:
            path = AGENTS_DIR / f"{name}.md"
            with self.subTest(name=name):
                text = path.read_text(encoding="utf-8")
                self.assertLessEqual(
                    len(text.splitlines()),
                    AGENT_LINE_CAP,
                    f"{name} is {len(text.splitlines())} lines; cap is {AGENT_LINE_CAP}",
                )
                _fields, body = split_frontmatter(text)
                self.assertNotIn("## Artifacts", body)

    def test_workflow_defines_artifact_policy(self) -> None:
        text = WORKFLOW_PY.read_text(encoding="utf-8")
        self.assertIn("ARTIFACT_POLICY", text)
        for needle in ARTIFACT_POLICY_STRINGS:
            with self.subTest(needle=needle):
                self.assertIn(needle, text)


if __name__ == "__main__":
    unittest.main()
