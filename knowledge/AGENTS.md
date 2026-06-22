# agent-cortex — shared agent knowledge base

Single source of truth for **skills**, **agents**, and **rules** shared across
AI coding tools (Claude Code, Codex, Cursor, opencode).

All content lives in `knowledge/`. Every runtime-specific path
(`.claude/`, `.cursor/`, `.agents/`, `.opencode/`, `AGENTS.md`, `CLAUDE.md`) is a
**directory- or file-level symlink into `knowledge/`** — set up once, never
hand-edited. No build/sync step: because the links are directory-level, adding a
skill or agent under `knowledge/` is visible to every tool immediately.

## Layout

```
knowledge/
  AGENTS.md            <- this file. Shared rules (SSOT). All tools read it.
  skills/<name>/SKILL.md
  agents/<name>.md
```

## How tools load this (cwd walks up to repo root)

| Source            | Claude Code | Codex | Cursor | opencode |
|-------------------|-------------|-------|--------|----------|
| skills            | `.claude/skills` | `.agents/skills` | `.claude/skills` | `.claude/skills` / `.agents/skills` |
| agents            | `.claude/agents` | (n/a) | `.cursor/agents` | `.opencode/agent` |
| rules             | `CLAUDE.md` | `AGENTS.md` | `AGENTS.md` | `AGENTS.md` |

Symlinks bridge each tool's expected path to `knowledge/`. Codex pure-`config.toml`
agents are intentionally NOT handled — agent defs are markdown only.

Directory-level links in place (set up once):

```
.claude/skills  -> knowledge/skills      .claude/agents -> knowledge/agents
.agents/skills  -> knowledge/skills      .cursor/agents -> knowledge/agents
                                         .opencode/agent -> knowledge/agents
AGENTS.md -> knowledge/AGENTS.md         CLAUDE.md -> knowledge/AGENTS.md
```

## Rule: add or change a skill

1. Create/edit `knowledge/skills/<name>/SKILL.md`. Frontmatter requires `name` + `description`.
2. Done. Directory link makes it visible to every tool immediately — no build step.

## Rule: add or change an agent

1. Create/edit `knowledge/agents/<name>.md`. Use the **richest** frontmatter
   (Claude superset: `name`, `description`, `tools`, `model`, ...). Tools that
   don't recognize a field ignore it — content stays semantic and portable.
2. Done. Visible to `.claude/agents`, `.cursor/agents`, `.opencode/agent` at once.

## Rule: change shared rules

Edit THIS file (`knowledge/AGENTS.md`). Root `AGENTS.md` and `CLAUDE.md` are
symlinks to it — every tool picks up the change.

## Rule: load a subproject's own context before working in it

Before touching any subproject (read/edit/run/commit/PR), FIRST read that
subproject's `CLAUDE.md` / `AGENTS.md` if present, and its skills under
`<subproject>/.claude/skills/`. A subproject's own rules win over anything here.
The root session starts above the subproject, so its context is NOT auto-injected
— go look.
