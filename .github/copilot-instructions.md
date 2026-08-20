# Copilot instructions

Read and follow [AGENTS.md](../AGENTS.md) — it holds the repo instructions for all agents (source-of-truth layout, contract-sync rule, safety invariants, `check-` naming convention).

Copilot specifics for this repo:
- The delivery workflow is entered by selecting the `orchestrator` custom agent ([.github/agents/orchestrator.agent.md](agents/orchestrator.agent.md)); the role agents live in [.github/agents/](agents/).
- Wrappers there must stay thin — role content is edited only in [agents/](../agents/) at the repo root (the harness-neutral definitions), not in the `.agent.md` files.
