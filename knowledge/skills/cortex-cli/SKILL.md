---
name: cortex-cli
description: Use when the user asks to install, add, fetch, update, or remove an external skill OR agent (from a GitHub repo, git URL, or npm package), bootstrap a fresh checkout, or rebuild/verify the tool symlinks. Drive the bundled scripts/cortex CLI — never hand-clone or hand-copy.
---

# cortex-cli — project management CLI

`scripts/cortex` manages **external** skills and agents and wires both builtin
and external resources into every tool's scan directory. Implementation lives in
`scripts/` (`cli.js` + `config.js` / `resource.js` / `fetch.js` / `commands.js`).
This skill is documentation only — the logic is the script.

**Runtime: bun.** The dispatcher `scripts/cortex` execs `bun cli.js`. Install bun
from https://bun.sh if missing.

**Always run the CLI.** Do not git-clone, npm-install, or copy files by hand.

## Commands

```sh
# bootstrap a fresh checkout: relink builtin + restore externals from lock
scripts/cortex install

# install ONE external from a source (name inferred from frontmatter if omitted)
scripts/cortex install skill github larksuite/cli lark-base
scripts/cortex install skill github owner/repo my-skill --ref v2 --path skills/my-skill
scripts/cortex install agent github owner/repo my-agent
scripts/cortex install agent npm @scope/some-agent

# remove an external resource + its links + lock entry
scripts/cortex uninstall lark-base

# maintenance
scripts/cortex relink          # rebuild ALL tool symlinks (builtin + external)
scripts/cortex verify [name]   # recompute hashes vs lock; drift -> exit 1
scripts/cortex list            # builtin [builtin] + external [github:…]
```

`kind` = `skill` | `agent`. `src` = `github` (owner/repo) | `git` (URL) | `npm` (package).
Run `relink` after adding/removing a **builtin** resource. Run `install` (no args)
once after a fresh clone — external content is gitignored, so it must be restored
from the lock.

Skill lookup in source: `skills/<name>/`, `<name>/`, `./`, first `skills/*/SKILL.md`.
Agent lookup: `agents/<name>.md`, `<name>.md`, first `agents/*.md`. Override with `--path`.

## Where things go

| | builtin (tracked) | external (gitignored) |
|---|---|---|
| skill | `knowledge/skills/<name>/` | `skills/<name>/` |
| agent | `knowledge/agents/<name>.md` | `agents/<name>.md` |

Tool dirs (gitignored, rebuilt by `relink`): skills → `.claude/skills`,
`.agents/skills`; agents → `.claude/agents`, `.cursor/agents`, `.opencode/agent`.
Each entry is a per-resource symlink pointing at builtin or external content.

## Lockfiles

`skills/skills-lock.json` and `agents/agents-lock.json` record each external
resource: `source`, `sourceType` (`github`/`git`/`npm`), optional `ref`,
`resourcePath`, and `computedHash` (SHA-256 of the resource, excluding
`.git`/`node_modules`). Gitignored — the template ships without externals.

## Rules

- Never install into `.claude/...` / `knowledge/` directly — use the CLI.
- Installing an external = stored + hashed + linked in one step (live immediately).
- `verify` DRIFT means the on-disk external was edited; re-install to update its
  hash, or `install` (bootstrap) to overwrite missing ones from source.
- A lock pins source + ref + content hash, not a commit SHA: bootstrap refetches
  the latest of that ref.
