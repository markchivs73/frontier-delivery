# Status — Frontier Delivery (engineering delivery process)

**Updated:** 2026-10-20
**State:** active
**One-liner:** The process is fully defined in markdown and runnable through the Claude Code and Copilot adapters. It is moving to iterative looping: real deliveries, then Retro PRs to harden the instructions.

## Where it is
- One initial commit (2026-08-20) holds the whole process: `process/workflow.md` (state machine), `process/handoffs.md` (envelopes and routing table), nine roles in `agents/`, and templates in `templates/`.
- Thin harness wrappers are live: `.claude/agents/` (8 subagents), `.claude/commands/deliver.md`, and `.github/agents/*.agent.md` (9 custom agents).
- `adapters/README.md` maps tracker capabilities to the ADO and GitHub MCP tools. `docs/azure-target-architecture.md` gives a six-step migration to MAF and Foundry, and the repo is at step 1 ("Now").
- No real delivery has run yet: there are no `work/<id>/` artefacts and no Retro PRs.

## Decisions made
- 2026-08-20: Shape: one orchestrator, spec artefacts as the contract between stages, a single writer (Implementer), and four fresh-context `check-` agents. Evidence is in `docs/industry-assessment.md`.
- 2026-08-20: Safety invariants: two human gates (plan approval and PR review), verify-fix limited to 3 loops, re-plan limited to 2, draft PR only, never merge.
- 2026-08-20: Role content lives only in `agents/`. Wrappers stay thin, and any change to a role's inputs or outputs updates `process/handoffs.md` in the same change.
- 2026-08-20: The process improves through PRs: Retro proposes small instruction edits for human review and never weakens the safety rules.

## Blockers
- None. Retro has little to learn from until a handful of real deliveries have run (a known risk in `docs/industry-assessment.md`).

## Next actions
- [15m] Contract-sync audit: for each role in `agents/`, check that its Inputs and Outputs match its section in `process/handoffs.md` and the routing table there (~lines 91–106). List any mismatches without fixing them.
- [15m] Wrapper parity check: confirm that each role in `agents/` has a `.claude/agents/` wrapper (or that the orchestrator is covered by `.claude/commands/deliver.md`) and a `.github/agents/*.agent.md` wrapper, and that each wrapper only points at `<process-root>/agents/<role>.md`.
- [15m] Write a dogfood work item for the first iterative loop: a small GitHub issue on this repo (for example "add a STATUS-aware note to `adapters/claude-code.md`") that `/deliver` can run end to end.
- [1h] Run `/deliver` on that issue end to end, keep `work/<id>/`, then run Retro and raise its instruction-edit PR.
- [deep] Define what "iterative looping" means here: how many deliveries before promoting to migration step 2 (CI-hosted, headless), and which friction metrics in `agents/retro.md` decide it.

## Parked ideas
- Migration steps 3–6 (Foundry read-side, then verify-side, then implement-side, then the full MAF graph) in `docs/azure-target-architecture.md`.
- Benchmark the GitHub Copilot coding agent as a managed implement step before building step 5.
