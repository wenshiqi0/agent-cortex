---
name: install-skill
description: Use when the user asks to install, add, fetch, or update a skill from an external source (a GitHub repo, a git URL, or an npm package). Run the bundled install.js script — do NOT hand-clone or hand-copy skill files.
---

# Install Skill

Installs a skill from an external source into agent-cortex's single source of
truth at `knowledge/skills/<name>/`. The runtime symlinks (`.claude/skills`,
`.agents/skills`) then expose it to every tool automatically — no extra step.

**Always run the script.** Do not git-clone, npm-install, or copy files by hand;
the script handles fetching, locating the skill, copying into `knowledge/skills/`,
hashing, and updating the lockfile (`knowledge/skills-lock.json`) consistently.

## Script

Path: `knowledge/skills/install-skill/install.js` (Node ≥ 18, uses git + npm).

```sh
node knowledge/skills/install-skill/install.js <command> ...
```

### Install

```sh
# from a GitHub repo (owner/repo). name optional; inferred from SKILL.md frontmatter.
node knowledge/skills/install-skill/install.js install github larksuite/cli lark-base
node knowledge/skills/install-skill/install.js install github owner/repo my-skill --ref v2

# from any git URL
node knowledge/skills/install-skill/install.js install git https://example.com/x.git my-skill

# from an npm package
node knowledge/skills/install-skill/install.js install npm @scope/some-skill my-skill
```

Skill lookup inside the source (auto): `skills/<name>/SKILL.md`, then
`<name>/SKILL.md`, then `./SKILL.md`, then the first `skills/*/SKILL.md`.
Override with `--path <dir>`.

### Maintain

```sh
node .../install.js list             # show installed skills + their sources
node .../install.js verify [name]    # recompute folder hash, report drift vs lock
node .../install.js restore [name]   # reinstall from lock (npm-ci equivalent)
node .../install.js remove <name>    # delete skill folder + lock entry
```

## Lockfile

`knowledge/skills-lock.json` records per skill: `source`, `sourceType`
(`github`/`git`/`npm`), optional `ref`, `skillPath`, and `computedHash`
(SHA-256 over all files in the skill folder, excluding `.git`/`node_modules`).
Commit it — it lets others `restore` the exact set.

## Rules

- Never install into `.claude/skills` / `.cursor/skills` directly — those are
  symlinks; always target `knowledge/skills/` via the script.
- After installing, the skill is live immediately (directory symlinks). No sync.
- If `verify` reports DRIFT, the on-disk skill was edited locally; decide whether
  to keep the local change (re-`install` to update the hash) or `restore`.
