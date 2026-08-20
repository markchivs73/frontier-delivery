# CLAUDE.md

Read and follow [AGENTS.md](AGENTS.md) — it holds the repo instructions for all agents (source-of-truth layout, contract-sync rule, safety invariants, `check-` naming convention).

Claude Code specifics for this repo:
- The delivery workflow is entered via the `/deliver` command ([.claude/commands/deliver.md](.claude/commands/deliver.md)); the 8 role subagents live in [.claude/agents/](.claude/agents/).
- Wrappers there must stay thin — role content is edited only in [agents/](agents/).
