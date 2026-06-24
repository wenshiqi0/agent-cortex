---
name: cortex-mem
description: Use when searching, loading, writing, or curating cross-session agent memory for agent-cortex, including prior decisions, repo conventions, debugging history, or reusable workflow facts.
---

# cortex-mem

`cortex-mem` is the controlled memory layer for agent-cortex. The CLI owns its
local service lifecycle; callers should use memory commands, not manage the
backend directly.

## Service Contract

The script shields callers from the local memory backend. Before every read or
write it ensures the service is running, waits for readiness, and initializes
the collection if needed.

```sh
scripts/cortex-mem status
```

If the script returns an error, report the script error. Do not tell the user to
start Qdrant manually unless the error says the `qdrant` binary is missing or the
configured endpoint is non-local.

## When To Search

Search memory before answering when the user asks about:

- prior decisions: "how did we decide X", "what did we do last time"
- repo conventions, repeated workflows, setup steps, debugging history
- a named project, branch, PR, incident, queue, skill, agent, or script that may
  have been discussed in an earlier session

Always scope the search. Prefer the narrowest known filters: `repo`, `project`,
`kind`, `tags`, `files`, and time range. Treat retrieved memories as historical
evidence, not unquestionable truth; verify against current files when behavior
or code may have changed.

## When To Write

Write memory only for durable facts:

- decisions and the reason they were made
- repo-specific conventions or gotchas
- commands, paths, service names, API quirks, and debugging outcomes likely to recur
- user preferences that are stable and useful across sessions
- completed investigation summaries with evidence and scope

Do not write ordinary chat, transient plans, raw logs, secrets, tokens,
credentials, private personal data, or unverified guesses.

## Curator Agent

For any non-trivial write, read `knowledge/agents/cortex-memory-curator.md` and
launch a subagent with that role text plus the candidate context. The curator
returns a memory candidate; the main agent decides whether to persist it.

Curated memory must include:

- `summary`: stable Chinese summary
- `scope`: repo/project/runtime boundary
- `kind`: decision, convention, debugging, workflow, preference, or reference
- `evidence`: source pointers such as files, commands, PRs, transcript snippets
- `tags`: short searchable labels
- `confidence`: 0.0 to 1.0
- `expires_at`: optional, for time-sensitive facts

## Storage Contract

Qdrant stores semantic index records: vector, summary, tags, scope, file refs,
timestamps, and confidence. Raw source material belongs in an auditable local
store, not only in Qdrant payloads.

The intended CLI contract is:

```sh
scripts/cortex-mem status
scripts/cortex-mem search --query "..." --repo agent-cortex --limit 8
scripts/cortex-mem remember --json /path/to/memory.json
```

If the CLI is missing or incomplete, do not invent database writes by hand.
Report the missing command and continue with an explicit, user-approved manual
summary instead.

## Safety Rules

- Never persist secrets, credentials, API keys, private keys, cookies, or `.env`
  contents.
- Never write "probably" as fact. Lower `confidence` or omit the memory.
- Prefer fewer, higher-quality memories over exhaustive capture.
- Cross-project recall must name the source project so context does not pollute
  the current repo.
- Before using a memory to justify code changes, re-check the current codebase.
