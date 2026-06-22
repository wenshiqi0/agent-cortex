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

## Loop

This is the core loop for developing a subproject under `repositories/`. It is a
rule for the **top-level orchestrator** (the session whose cwd is the
agent-cortex root, with full visibility of every skill and every repo). This
section lives in `AGENTS.md` on purpose: a spawned subagent's cwd is its own
project directory, so it never sees this file — the orchestrator alone runs the
loop and decides what to hand down.

### Why a loop is needed

A subproject is an isolated git repo. When work happens with cwd inside
`repositories/<repo>/`, the agent there is blind to the agent-cortex root: it
cannot see the shared skills, the rules, or sibling projects. That isolation is
intentional. The orchestrator's job is to hand the subagent the **coordinates**
of the capabilities it may need — not the contents.

### The loop (orchestrator steps)

1. **Pick the repo and scope the task.** The repo lives at
   `repositories/<repo>/`.

2. **Isolate the work in a worktree** per the `feature-workflow` skill:
   `repositories/<repo>.worktrees/<branch>/`. Never work on the repo's main tree.

3. **Build a path map (paths only — never paste contents).** Resolve absolute
   paths so the subagent can use them from its own cwd:
   - shared skills: `<cortex-root>/knowledge/skills/` and `<cortex-root>/skills/`
   - shared agents: `<cortex-root>/knowledge/agents/` and `<cortex-root>/agents/`
   - shared rules: `<cortex-root>/knowledge/AGENTS.md`
   - any **related sibling projects**: `<cortex-root>/repositories/<other>/`

   Skills **and agents** are both shared and discoverable this way — same
   mechanism, paths only. A subagent can itself spawn further subagents, so it
   needs the agents directories in its map to find and assign roles to its own
   children. The orchestrator hands down the agents path; the subagent reads and
   uses agent definitions on demand, exactly as it does with skills.

4. **Optionally assign a role.** The orchestrator MAY designate one
   `knowledge/agents/<name>.md` (or external `agents/<name>.md`) as the
   subagent's persona — its contents become part of the subagent's main system
   prompt, so the subagent embodies that agent's characteristics. Only the
   explicitly assigned agent file is included; no other cortex content is.

5. **Spawn the subagent.** Its cwd is the worktree (its own project directory).
   The spawn prompt contains: the task, the path map, and the instruction —
   *"When searching, grepping, or recalling context, include these directories
   in your search scope; read from them on demand. Do not assume they are
   indexed — go look."* Plus: *"This project's own `CLAUDE.md`/`AGENTS.md` and
   skills take precedence over anything from the path map."*

6. **Iterate.** The subagent develops inside its isolated cwd, pulling from the
   mapped paths only as needed. The orchestrator reviews results and re-spawns or
   refines as the loop requires.

7. **Close out** per `feature-workflow`: PR, check status with `gh`, confirm with
   the user before releasing the worktree.

### Invariants

- The subagent gets **paths, not pasted bodies**, for both skills and agents
  (it discovers and reads them on demand, and can assign agent roles to its own
  children). The single exception is the role agent in step 4, whose body is
  pasted into the subagent's own system prompt.
- The orchestrator never does subproject edits on the main working tree itself —
  it delegates into a worktree.
- Subproject-local rules always win over the handed-down path map.
