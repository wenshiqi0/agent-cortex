---
name: mrain
description: Use mrain memory CLI and local memory database. Use when the user asks to remember, recall, inspect mrain memory, configure mrain model environment variables, or run mrain tests.
disable-model-invocation: true
---

# mrain

## What mrain Does

`mrain` is a Rust memory system. The CLI exposes one user-facing memory layer:

```sh
mrain memory memorize --source-kind agent --source-model "model-name" --text "..."
mrain memory recall --query "..."
mrain memory remember --id 1
mrain memory summarize-patterns
```

Do not expose short-term or long-term memory terms in CLI workflows unless discussing internals.

## Environment

Memory structuring is model-backed. `mrain` loads provider settings from environment variables through `mrain-config`. Provider priority: Anthropic-compatible first, then OpenAI-compatible.

Anthropic-compatible variables:

```sh
export MRAIN_ANTHROPIC_API_KEY="..."
export MRAIN_ANTHROPIC_MODEL="mimo-v2.5-pro"
export MRAIN_ANTHROPIC_ENDPOINT="https://token-plan-cn.xiaomimimo.com/anthropic"
export MRAIN_ANTHROPIC_MAX_TOKENS="4096"
export MRAIN_ANTHROPIC_CONTEXT_LIMIT="1000000"
export MRAIN_ANTHROPIC_THINKING="true"
export MRAIN_ANTHROPIC_THINKING_BUDGET_TOKENS="4096"
```

OpenAI-compatible variables:

```sh
export MRAIN_OPENAI_API_KEY="..."
export MRAIN_OPENAI_MODEL="gpt-4.1"
export MRAIN_OPENAI_ENDPOINT="https://api.openai.com/v1"
```

No config file is required for `memory memorize`.

## Local Storage

SQLite database: `$HOME/.mrain/memory.sqlite3`, main table `memories` (`tags` is a comma-joined string of tag values).

## Source Kind

`--source-kind` defaults to `user` for direct human CLI use. Agents using this skill MUST pass `--source-kind agent` and `--source-model`.

Allowed values:

```text
user      memory came from user-provided content
agent     memory came from agent output; requires source_model
internal  memory was synthesized by mrain itself
```

## Common Commands

If `mrain` is not found, install the binary onto `PATH` (e.g. `$HOME/.local/bin/mrain` or `/usr/local/bin/mrain`). Prefer `scripts/doctor.py` for availability checks (see Verification).

Recall memory:

```sh
mrain memory recall --query "CLI"
```

`recall` returns compact candidates as `id<TAB>summary`. Load the full record when needed:

```sh
mrain memory remember --id 1
```

Summarize recurring patterns from all memory summaries:

```sh
mrain memory summarize-patterns
```

Inspect recent memory rows:

```sh
sqlite3 "$HOME/.mrain/memory.sqlite3" \
  "SELECT created_at, content, summary, tags, source_kind, source_model FROM memories ORDER BY created_at DESC LIMIT 5;"
```

## Verification

Read-only doctor (binary, help, provider env, storage; never creates `$HOME/.mrain`):

```sh
python3 knowledge/skills/mrain/scripts/doctor.py
python3 knowledge/skills/mrain/scripts/doctor.py --json
```

Gated smoke (writes one memory row via `memorize` + `recall` when a provider API key is set; otherwise `SKIP smoke`):

```sh
python3 knowledge/skills/mrain/scripts/doctor.py --smoke
```

Exit codes: `2` missing binary, `1` any `FAIL` check, `0` otherwise (`WARN`/`SKIP` do not change the exit code).
