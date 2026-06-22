---
name: example-agent
description: Template subagent showing the richest-frontmatter source format. Delete or replace.
tools: Read, Grep, Glob, Bash
model: inherit
---

You are a template subagent. Replace this body with the agent's system prompt.

Authoring notes:
- This single file is symlinked into `.claude/agents/`, `.cursor/agents/`, and
  `.opencode/agent/` by `sync.sh`. One physical file, read by all tools.
- Use the superset of frontmatter fields. Fields a given tool does not recognize
  (e.g. opencode `mode`, Claude `tools`) are ignored harmlessly.
- Keep the body semantic — every model reads the same markdown.
