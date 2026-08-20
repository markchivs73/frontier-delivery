# AGENTS.md

This repository defines the **frontier-delivery delivery process** — markdown agent roles, contracts, and templates. There is no application code here; the "product" is the process definition itself.

## For any agent working in this repo

- Source of truth: role definitions in `agents/`, contracts in `process/handoffs.md`, state machine in `process/workflow.md`. The harness wrappers in `.claude/agents/`, `.claude/commands/`, and `.github/agents/` must stay thin — role content belongs in `agents/` only.
- Verification/review agents follow the frontier naming convention: `check-` prefix (never `verifier-`).
- Any edit to a role's inputs/outputs must be reflected in `process/handoffs.md` (and vice versa) in the same change. The envelope schemas and the routing table are load-bearing.
- Never weaken the safety invariants: two human gates (plan approval, PR review), single-writer rule, bounded loops (verify→fix ≤ 3, re-plan ≤ 2), draft-PR-only, never merge.
- Keep the adapter tracker table (`adapters/README.md`) capability-first; concrete MCP tool names live only in that table.

## For agents running the delivery process (in this repo, or in a target repo with this repo vendored as `.frontier/`)

- Enter through the orchestrator (Claude Code: `/deliver`; Copilot: the `orchestrator` custom agent). Do not run role agents ad hoc mid-delivery except via the orchestrator's routing.
- Follow your role file exactly, including its Non-goals section. Finish every stage with your handoff envelope (fenced YAML) per `process/handoffs.md`.
- All delivery working files go under `work/<id>/` in the target repo.
