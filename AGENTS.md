# AGENTS.md

This repository defines the **frontier-delivery process**: markdown agent roles, envelope contracts, gate policy, templates, the Claude Code plugin, and the deterministic runner that executes it headless. The "product" is the process definition itself.

## For any agent working in this repo

- **Source of truth:** role definitions in `roles/`; the state machine in `process/workflow.md` and `process/workflow.yaml`; inter-agent contracts in `process/handoffs.md` (prose) and `contracts/delivery/` (machine form); gate policy in `policy/policy.yaml`. The harness wrappers in `agents/`, `commands/` and `.github/agents/` must stay thin. Role content belongs in `roles/` only.
- **Contract-sync rule:** any change to a role's inputs or outputs is made in the same change to `process/handoffs.md`, the matching `contracts/delivery/*.v1.schema.json`, its conformance cases in `contracts/delivery/conformance/`, and the lock (`PYTHONPATH=runner python -m frontier contracts lock`). Contracts are closed JSON Schema 2020-12 plus CEL rules (`x-frontier-validations`, scoped to `self`, no I/O). A breaking change is a new major, never an edit to a pinned one.
- Verification and review agents use the `check-` prefix (never `verifier-`).
- **Never weaken the safety invariants:** the gate policy model (human / shadow / auto, with auto earned through calibration and closing on regression); agents never merge; the single-writer rule; bounded loops (budgets in the policy); the guard hooks (`runner/frontier/guard.py`). The shipped default policy must never auto-merge.
- Keep the adapter tracker table (`adapters/README.md`) capability-first; concrete MCP tool names live only in that table.
- Run `python -m pytest tests` before proposing a change. `tests/test_repo_consistency.py` enforces most of the rules above.

## For agents running the process (in a product repo with the plugin enabled)

- Enter through the orchestrator: `/frontier-delivery:shape`, `/frontier-delivery:deliver`, the Copilot `orchestrator` agent, or the headless runner. Do not run role agents ad hoc mid-delivery except through the orchestrator's routing.
- Follow your role file exactly, including its Non-goals section. Finish every stage by writing your envelope to `work/<id>/envelopes/<agent>.yaml` and repeating it as a fenced YAML block.
- All delivery working files go under `work/<id>/` in the target repo, committed on the `delivery/<id>` (or `shape/<id>`) branch.
- If a guard hook denies an action, that action is outside your role. Return `needs_input` rather than working around it.
