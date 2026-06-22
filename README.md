# agent-cortex

Shared, multi-tool agent knowledge base: one source of truth for **skills**,
**agents**, and **rules**, consumed natively by Claude Code, Codex, Cursor, and
opencode.

## Why

Each tool loads skills/agents/rules from a different directory and (for agents)
won't read another tool's folder. Maintaining N copies rots. agent-cortex keeps
everything in `knowledge/` and **directory-level symlinks** project it into each
tool's expected path — single source, zero duplication, no build step.

## Layout

```
agent-cortex/
  knowledge/            <- SSOT. Edit ONLY here.
    AGENTS.md           shared rules
    skills/<name>/SKILL.md
    agents/<name>.md
  README.md

  # one-time symlinks into knowledge/ — do not hand-edit:
  AGENTS.md       -> knowledge/AGENTS.md
  CLAUDE.md       -> knowledge/AGENTS.md
  .claude/skills  -> knowledge/skills
  .agents/skills  -> knowledge/skills
  .claude/agents  -> knowledge/agents
  .cursor/agents  -> knowledge/agents
  .opencode/agent -> knowledge/agents
```

Because the links point at directories, adding a skill/agent under `knowledge/`
is picked up by every tool instantly — nothing to run.

## Loading model

Tools discover context by walking **up from cwd to the repo root**. So content
here is visible only when a tool session starts **at the agent-cortex root**
(or a non-git dir above it). Sessions started inside an independent git repo
stop at that repo's boundary — by design.

## Usage

Just edit `knowledge/`. No command to run.

- **Add a skill**: create `knowledge/skills/<name>/SKILL.md` (frontmatter
  `name` + `description`).
- **Add an agent**: create `knowledge/agents/<name>.md` with the richest
  frontmatter (`name`, `description`, `tools`, `model`, ...). Unknown fields are
  ignored per tool.
- **Change rules**: edit `knowledge/AGENTS.md`. Root `AGENTS.md` / `CLAUDE.md`
  pick it up automatically.

(One-time link setup, if ever rebuilding from scratch:)

```sh
mkdir -p .claude .cursor .opencode .agents
ln -sf ../knowledge/skills .claude/skills
ln -sf ../knowledge/agents .claude/agents
ln -sf ../knowledge/skills .agents/skills
ln -sf ../knowledge/agents .cursor/agents
ln -sf ../knowledge/agents .opencode/agent
ln -sf knowledge/AGENTS.md AGENTS.md
ln -sf knowledge/AGENTS.md CLAUDE.md
```

## Not handled

Codex `config.toml`-based agents (different mechanism). Agent defs are markdown
only — every model understands the semantic content regardless.
