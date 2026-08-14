---
name: skill-creator
description: Use when you need to capture a repeatable capability as a reusable skill or revise an existing one — whether the user asks ("turn this into a skill", "save this as a skill", "沉淀一个 skill", "revise this skill", "slim", "mechanize", "skill 瘦身") or you notice you just did something a future agent will redo (a multi-step query, a deploy sequence, a build incantation, an investigation that should have been one command). Guides decomposing the task into mechanizable steps backed by scripts, then wrapping them in a thin skill that grants minimal autonomy.
---

# skill-creator — distill a capability into a skill

A skill is not documentation. A skill is **mechanization plus a small amount of
judgement**. The next agent who faces this task should run a command, not an
investigation. Most of the value lives in the scripts; SKILL.md is a thin
wrapper naming which script to run and the few decisions a script cannot make.

## The core principle

When you finish a task worth keeping, you have implicit knowledge: which queue,
which command, which flag, which order. Left as prose, the next agent re-derives
it. The job of a skill is to **erase that re-derivation** — bias toward removing
autonomy. Hand the model only the decisions a script genuinely cannot make.

## Procedure

### 1. List every step, then sort into mechanical vs judgement

Write the task as a flat list of concrete steps. For each, ask: *could a script
do this with no model reasoning?*

- **Mechanical** — queries, CLI calls, builds, file scaffolding, name/URL/ARN
  derivation, parsing, polling, formatting. Anything deterministic. → goes in a
  **script**.
- **Judgement** — "is this output acceptable", "which of these is the right
  target", "should we proceed given prod risk". Anything needing context or a
  human's intent. → stays in the **skill body** as a short instruction, or a
  `--yes`-style gate in the script.

If a step *feels* like judgement but is really a lookup (e.g. "find the queue
name"), it is mechanical — bake the answer in. The billing-dlq skill hardcodes
account/region/queue-scheme precisely because hunting them was the wasted work.

### 2. Mechanize aggressively — push the mechanical/judgement line toward mechanical

Default to a script for anything deterministic. A script is faster, cheaper, and
cannot hallucinate. Prefer:

- **stdlib / no deps** when reasonable (python3 + `subprocess` over a CLI already
  on PATH beats a dependency tree; avoids type/install friction — see why
  billing-dlq moved off `import "bun"`).
- **explicit subcommands** (`count`, `peek`, `redrive`) over one do-everything
  entrypoint. Keep granularity small — single-purpose scripts compose and are
  individually testable; if a task does two things, split it.
- **simple, reliable I/O**: small fixed args in, JSON or one stable line out. No
  interactive prompts in the read path. Print the resolved target (URL/ARN)
  before acting so the operation is auditable.
- **safety gates on writes**: irreversible / prod-mutating ops refuse unless an
  explicit flag (`--yes`) is passed. Pin region/env so a stray default can't
  silently hit the wrong target.

### 3. Write a thin SKILL.md

The body exists to route, not to re-explain the script. Include:

- **frontmatter** `name` + `description`. The description is a trigger: name the
  user phrasings AND situations where the model should reach for it.
- **the gotcha up front** — the one fact that caused the original re-hunt (e.g.
  "medeo-dev has no sqs command — don't go spelunking").
- **coordinates** — the deterministic facts (names, accounts, source-of-truth
  paths) the script encodes, so a human can audit them.
- **commands** — copy-paste invocations for each subcommand, real arguments.
- **semantics + safety** — what each command means, what's destructive, what's
  gated.

Keep it scannable — cut anything the script's `--help` already says.

### 4. Decide builtin vs business, then place it

- **builtin** (template's own product, reusable across any project) →
  `knowledge/skills/<name>/`, tracked by git.
- **business / org-specific** (talks to specific queues, services, infra) →
  cortex-root `skills/<name>/`, gitignored. This is where most distilled task
  skills land.

Then register the symlinks and run the repo skill audit:

```sh
scripts/cortex relink
python3 scripts/skill-audit.py
```

Confirm `ls -l .claude/skills/<name>` points at the right source dir. For
business skills also run `git check-ignore skills/<name>/*` so the template
stays clean.

The audit contract every skill must satisfy: **SKILL.md ≤ 120 lines**, and
deterministic command docs need co-located scripts (or repo-tooling references).
The audit checks contracts (frontmatter, paths, cortex commands, CLI `--help`,
co-located tests) — not whether the skill is the right abstraction.

### 5. Test before declaring done

Run every script subcommand against a real (read-only) target. Confirm write
gates refuse without their flag. A skill whose script wasn't run is a guess.
Re-run `python3 scripts/skill-audit.py` (or `--json`) after edits so placement
and docs stay consistent with the tree.

## Revising an existing skill

Same loop, shorter: re-sort the skill's steps mechanical vs judgement → move
freshly-mechanical prose into scripts → thin SKILL.md back to a routing card →
`scripts/cortex relink` (only when resources were added/removed) +
`python3 scripts/skill-audit.py`.

## Checklist

- [ ] Steps listed and sorted; mechanical steps live in scripts, lookups hardcoded
- [ ] Scripts: stdlib/minimal deps, small subcommands, simple I/O, write gates
- [ ] SKILL.md thin: triggering description, gotcha, coordinates, commands, safety
- [ ] Placed correctly (builtin `knowledge/skills/` vs business `skills/`)
- [ ] `scripts/cortex relink` + `python3 scripts/skill-audit.py` (and
      `git check-ignore` for business skills)
- [ ] Every subcommand tested; write gates confirmed
