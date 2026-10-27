# CLAUDE.md

Read and follow [AGENTS.md](AGENTS.md) — it holds the repo instructions for all agents (source-of-truth layout, contract-sync rule, safety invariants, `check-` naming convention).

Claude Code specifics for this repo:
- The delivery workflow is entered via the `/deliver` command ([.claude/commands/deliver.md](.claude/commands/deliver.md)); the 8 role subagents live in [.claude/agents/](.claude/agents/).
- Wrappers there must stay thin — role content is edited only in [agents/](agents/).

## Session handover (STATUS.md)

`STATUS.md` at the repo root is the handover note for this workstream: where it is, decisions,
blockers, and next actions tagged `[15m]` / `[1h]` / `[deep]`. A daily dashboard reads it.

- Read `STATUS.md` at the start of a session to pick up where the last one left off.
- Before ending a session in which anything changed, run `/wrap-up` (or follow
  `.claude/commands/wrap-up.md`) so `STATUS.md` reflects the state *now* and keeps at least two
  `[15m]` next actions that a fresh session could start cold.
- When a session was started from a `[15m]` item, remove or update that item as part of the wrap-up.
