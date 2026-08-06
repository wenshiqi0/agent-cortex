---
name: usage-daily
description: "Use when the user asks for daily/recent agent-cortex model consumption analysis, token usage review, cost breakdown by session/subagent/skill, or to run the scheduled usage report. Emits a markdown report grouping last 24h (configurable) Cursor agent-transcripts by session, categorizes subagents by skill (medeo-dev / code-workflow / mcap-lane-model-test / other), and flags the top consumers."
---

# usage-daily

Read-only scan of Cursor `agent-transcripts` for the last N hours. Groups
sessions, categorizes subagents by skill, and emits a markdown (or JSON) cost
report. Deterministic; no network; does not touch `state.vscdb`.

Script:

```text
knowledge/skills/usage-daily/analyze_transcripts.py
```

## How to run

```sh
python3 knowledge/skills/usage-daily/analyze_transcripts.py --hours 24
python3 knowledge/skills/usage-daily/analyze_transcripts.py --hours 48 --json
python3 knowledge/skills/usage-daily/analyze_transcripts.py --hours 24 --out /tmp/usage.md
```

Defaults: `--hours 24`, transcripts root
`~/.cursor/projects/Users-wenshiqi-Documents-agent-cortex/agent-transcripts`,
markdown to stdout.

## Output shape

- Summary: session count, subagent counts/MB by category (medeo-dev /
  mcap-lane-model-test / code-workflow / other), total transcript MB
- Top sessions table (by main+sub bytes)
- Top subagents table (size, session, category, snippet)
- Static cost-center notes (orchestrator + code-workflow models)
