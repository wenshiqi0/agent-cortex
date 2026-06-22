# agent-cortex — shared agent knowledge base

Source of truth for **skills**, **agents**, and **rules** shared across AI coding
tools (Claude Code, Codex, Cursor, opencode).

Resources have two origins:

- **builtin** — ship with the template, live in `knowledge/{skills,agents}/`,
  tracked by git. This is the template's own product.
- **external** — installed from a source (github/git/npm), live in
  `./{skills,agents}/`, **gitignored** so the template stays clean.

Tools scan one flat directory per resource. Builtin + external are merged into
that directory by **per-resource symlinks** managed by `scripts/cortex`.

## Layout

```
knowledge/
  AGENTS.md              <- this file. Shared rules. All tools read it.
  skills/<name>/SKILL.md   builtin skills
  agents/<name>.md         builtin agents
skills/<name>/           external skills (gitignored) + skills/skills-lock.json
agents/<name>.md         external agents (gitignored) + agents/agents-lock.json

# generated symlink dirs (gitignored; rebuilt by `relink`):
.claude/skills/<name>    -> knowledge/skills/<name>  OR  skills/<name>
.agents/skills/<name>    -> (same)
.claude/agents/<name>.md -> knowledge/agents/<name>.md  OR  agents/<name>.md
.cursor/agents/<name>.md -> (same)
.opencode/agent/<name>.md-> (same)

# rules file links (tracked; point at knowledge/AGENTS.md):
AGENTS.md -> knowledge/AGENTS.md     CLAUDE.md -> knowledge/AGENTS.md
```

## How tools load this (cwd walks up to repo root)

| Resource | Claude Code | Codex | Cursor | opencode |
|----------|-------------|-------|--------|----------|
| skills   | `.claude/skills` | `.agents/skills` | `.claude/skills` | `.claude/skills` / `.agents/skills` |
| agents   | `.claude/agents` | (n/a) | `.cursor/agents` | `.opencode/agent` |
| rules    | `CLAUDE.md` | `AGENTS.md` | `AGENTS.md` | `AGENTS.md` |

Codex pure-`config.toml` agents are intentionally NOT handled — agent defs are
markdown only.

## The manager script

`scripts/cortex <cmd>` handles all link/lock work (a `bun` CLI; logic split across
`scripts/cli.js` + `config.js` / `resource.js` / `fetch.js` / `commands.js`):

```
install                                              bootstrap: relink + restore externals from lock
install skill <github|git|npm> <source> [name] [--ref r] [--path p]
install agent <github|git|npm> <source> [name] [--ref r] [--path p]
uninstall <name>  delete an external resource + links + lock entry
relink            rebuild every tool symlink (builtin + external)
verify [name]     recompute hashes vs lock, report drift
list              list builtin + external, both kinds
```

After a fresh clone, run `scripts/cortex install` once — it relinks builtin and
restores any external recorded in the lock.

## Rule: add or change a BUILTIN skill/agent

1. Edit under `knowledge/skills/<name>/SKILL.md` or `knowledge/agents/<name>.md`.
   Agents use the richest frontmatter (`name`, `description`, `tools`, `model`,
   ...); unknown fields are ignored per tool.
2. Run `scripts/cortex relink` (only needed when adding/removing a resource, not
   for in-place edits).

## Rule: install an EXTERNAL skill/agent

Never hand-clone or copy. Run `scripts/cortex install skill|agent <type> <source>`.
It fetches, places the resource under `./skills/` or `./agents/`, hashes it into
the per-kind lockfile, and links it into every tool dir.

## Rule: change shared rules

Edit THIS file (`knowledge/AGENTS.md`). Root `AGENTS.md` and `CLAUDE.md` are
symlinks to it — every tool picks up the change.

## Rule: load a subproject's own context before working in it

Before touching any subproject (read/edit/run/commit/PR), FIRST read that
subproject's `CLAUDE.md` / `AGENTS.md` if present, and its skills under
`<subproject>/.claude/skills/`. A subproject's own rules win over anything here.
The root session starts above the subproject, so its context is NOT auto-injected
— go look.
