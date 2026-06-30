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

  # tracked rules entrypoints (thin pointers, not symlinks):
  CLAUDE.md   -> first line `@knowledge/AGENTS.md` (Claude Code import)
  AGENTS.md   -> note telling other tools to read knowledge/AGENTS.md
```

## Loading model

Tools discover context by walking **up from cwd to the repo root**, so content
here is visible only when a tool session starts **at the agent-cortex root**.
Sessions started inside an independent git repo (e.g. under `repositories/`) stop
at that repo's boundary — by design.

## Requirements

| Tool | Why |
|------|-----|
| [**bun**](https://bun.sh) | runs the CLI (`scripts/cli.js`) and installs npm-sourced resources (`bun add`) |
| **git** | clones `github` / `git` sources (and manages this repo) |
| **mrain** | external memory CLI used by the builtin `mrain` skill and turn-level recall/memorize rules |
| [**Qdrant**](https://qdrant.tech) | external vector store used by `mrain` for semantic memory search; run as a local binary/service reachable from this machine, no Docker required |

No npm/node required — the CLI is pure bun + git, with zero npm dependencies.
`mrain` assumes a local Qdrant endpoint is available when semantic memory is
enabled, typically `http://127.0.0.1:6333`.

## The manager

Run from the agent-cortex root:

```sh
bun run <command>
```

| Command | Purpose |
|---------|---------|
| `bun run install` | bootstrap: relink builtin + restore externals from lock |
| `bun run install skill <github\|git\|npm> <source> [name]` | install one external skill |
| `bun run install agent <github\|git\|npm> <source> [name]` | install one external agent |
| `bun run uninstall <name>` | delete an external resource + links + lock entry |
| `bun run relink` | rebuild all tool symlinks (builtin + external) |
| `bun run verify [name]` | recompute hashes vs lock, report drift |
| `bun run list` | list builtin + external, both kinds |

`--ref <branch/tag>` and `--path <dir>` refine a source.

> Agents and tooling invoke the same CLI through `scripts/cortex <command>`; the
> `bun run` aliases above are the short form for humans. Logic lives in `scripts/`
> (`cli.js` + `config.js` / `resource.js` / `fetch.js` / `commands.js`).

## Setup after clone

External content is gitignored, so a fresh clone has only builtin resources.
One command bootstraps everything — relink builtin links and restore any external
recorded in the lock:

```sh
bun run install
```

## Usage

- **Builtin skill/agent**: create it under `knowledge/skills/<name>/SKILL.md` or
  `knowledge/agents/<name>.md`, then run `bun run relink`.
- **External skill/agent**: `bun run install skill|agent <type> <source>` —
  never hand-clone.
- **Rules**: edit `knowledge/AGENTS.md`; root `AGENTS.md`/`CLAUDE.md` follow.

## Not handled

Codex `config.toml`-based agents (different mechanism). Agent defs are markdown
only — every model reads the same semantic content.
