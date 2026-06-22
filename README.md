# agent-cortex

A monorepo template for agent harnesses: one place to manage the **skills**,
**agents**, and **rules** shared across Claude Code, Codex, Cursor, and opencode.

## Why

Each tool loads skills/agents/rules from a different directory and (for agents)
won't read another tool's folder. agent-cortex keeps resources in one place and
projects them into every tool's expected path via per-resource symlinks — single
source, no duplication.

Resources have two origins, kept apart so the template stays clean:

- **builtin** — ship with the template (`knowledge/skills/`, `knowledge/agents/`),
  tracked by git.
- **external** — installed from github/git/npm (`./skills/`, `./agents/`),
  **gitignored** along with their lockfiles.

Both are merged into each tool's scan directory by symlinks, so a tool sees one
flat list and can't tell builtin from external.

## Layout

```
agent-cortex/
  knowledge/                 tracked — the template's own product
    AGENTS.md                shared rules (SSOT)
    skills/<name>/SKILL.md   builtin skills
    agents/<name>.md         builtin agents
  skills/                    gitignored — installed skills + skills-lock.json
  agents/                    gitignored — installed agents + agents-lock.json
  repositories/              gitignored — business git repos live here
  README.md

  # gitignored, rebuilt by `relink`:
  .claude/skills/  .agents/skills/
  .claude/agents/  .cursor/agents/  .opencode/agent/

  # tracked links to rules:
  AGENTS.md -> knowledge/AGENTS.md
  CLAUDE.md -> knowledge/AGENTS.md
```

## Loading model

Tools discover context by walking **up from cwd to the repo root**, so content
here is visible only when a tool session starts **at the agent-cortex root**.
Sessions started inside an independent git repo (e.g. under `repositories/`) stop
at that repo's boundary — by design.

## The manager

```sh
scripts/cortex <command>
```

Entrypoint is `scripts/cortex` (a `bun` CLI; install bun from https://bun.sh).
Logic is split across `scripts/` (`cli.js` + `config.js` / `resource.js` /
`fetch.js` / `commands.js`).

| Command | Purpose |
|---------|---------|
| `install` | bootstrap: relink builtin + restore externals from lock |
| `install skill <github\|git\|npm> <source> [name]` | install one external skill |
| `install agent <github\|git\|npm> <source> [name]` | install one external agent |
| `uninstall <name>` | delete an external resource + links + lock entry |
| `relink` | rebuild all tool symlinks (builtin + external) |
| `verify [name]` | recompute hashes vs lock, report drift |
| `list` | list builtin + external, both kinds |

`--ref <branch/tag>` and `--path <dir>` refine a source.

## Setup after clone

External content is gitignored, so a fresh clone has only builtin resources.
One command bootstraps everything — relink builtin links and restore any external
recorded in the lock:

```sh
scripts/cortex install
```

## Usage

- **Builtin skill/agent**: create it under `knowledge/skills/<name>/SKILL.md` or
  `knowledge/agents/<name>.md`, then run `scripts/cortex relink`.
- **External skill/agent**: `scripts/cortex install skill|agent <type> <source>` —
  never hand-clone.
- **Rules**: edit `knowledge/AGENTS.md`; root `AGENTS.md`/`CLAUDE.md` follow.

## Not handled

Codex `config.toml`-based agents (different mechanism). Agent defs are markdown
only — every model reads the same semantic content.
