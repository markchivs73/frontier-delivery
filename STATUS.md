# Status — Frontier Delivery (engineering delivery process)

**Updated:** 2026-10-27
**State:** active
**One-liner:** PR #2 restructures the process into a Claude Code plugin with a shape stage, policy-driven gates, contracts as data (E27 shape) and a deterministic runner for headless and GitHub-native runs. It is awaiting review, and no live run has happened yet.

## Where it is
- PR #2 (`feature/frontier-delivery-template`) is green: 119 tests, and `claude plugin validate` passes. The roles now live in `roles/` and the plugin wrappers in `agents/` · `commands/` · `hooks/`. The runner is in `runner/`, the contracts in `contracts/delivery/`, and the gate policy in `policy/`.
- Three run modes share the roles, contracts and policy: interactive (`/frontier-delivery:shape|deliver|inbox`), headless (`python -m frontier …`) and GitHub-native (labels and `/approve`-style comments, through `.github/workflows/frontier.yml`).
- Neither a live `claude -p --agent frontier-delivery:<role>` run nor a live Actions run has happened yet. Both need credentials.
- The Frontier Workflow binding is deferred until the E27 contracts register lands (`runner/README.md#frontier-workflow-deferred`).

## Decisions made
- 2026-10-26 — Contracts follow E27: closed JSON Schema 2020-12 plus CEL rules (`x-frontier-validations`), pinned by sha256 in `contracts/contracts.lock.json`, with implementation-neutral conformance cases.
- 2026-10-26 — Gates are human, shadow or auto per `policy/policy.yaml`. Auto must be earned through calibration and closes itself on regression. The shipped default is backlog human, plan and merge shadow, and never auto-merge.
- 2026-10-26 — Sealed recommendations and calibration records live in a runner-owned ledger (`frontier/metrics` branch), never in committed `state.yaml`. In CI, agents get no git or GitHub credentials.
- 2026-10-26 — Verify budget = maximum verify passes (default 3: the first pass plus two fix loops).
- 2026-10-26 — Local delivery and GitHub-native mode come first; the Frontier Workflow binding is deferred.
- 2026-08-20 — Shape: one orchestrator, spec artefacts as the contract between stages, a single writer, and fresh-context `check-` agents (`docs/industry-assessment.md`).

## Blockers
- None for review. A first live run needs `ANTHROPIC_API_KEY` (or `CLAUDE_CODE_OAUTH_TOKEN`) in a scratch repo.

## Next actions
- [15m] Review PR #2, starting with `policy/policy.yaml`, `roles/shaper.md` and `contracts/README.md`. Done when it's merged or has review comments.
- [15m] Make a scratch repo, run `bash ~/repos/frontier-delivery/init/frontier-init.sh --github --labels` in it, and add the API key secret. Done when `.github/workflows/frontier.yml` is committed there.
- [1h] First live delivery: label a small story `frontier:deliver` in the scratch repo, drive it to the merge gate with `/approve`, and note any agent/plugin naming or permission issues (risk: `--agent frontier-delivery:<role>` naming).
- [1h] Run `contracts/delivery/conformance/*.yaml` against the candidate .NET validator and CEL library (Corvus + a community CEL implementation) to test the CEL-on-.NET feasibility risk.
- [deep] Bind to Frontier Workflow once E27 is in place: publish the contracts, add an engine boundary validator, and generate the DAG from `process/workflow.yaml`.

## Parked ideas
- Gate conditions as CEL (policy, not contract); revert/incident outcome tracking; a `golden/` eval set of fixed deliveries.
- Benchmark the GitHub Copilot coding agent as a managed implement step.
