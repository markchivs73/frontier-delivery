# Runner

The deterministic orchestrator: [roles/orchestrator.md](../roles/orchestrator.md) as code. It runs each role as a fresh headless Claude Code session (`claude -p --agent frontier-delivery:<role>`, with the plugin and guard hooks loaded). It validates every envelope against its pinned contract, applies the gate policy and loop budgets, and stops whenever a human is needed.

No LLM decides routing, budgets or whether a gate opens. Agents produce artifacts; this code judges them.

## Install

```bash
pip install -r runner/requirements.txt      # PyYAML, jsonschema, cel-python
export PYTHONPATH=/path/to/frontier-delivery/runner
```

It needs the `claude` CLI on `PATH`, authenticated. Run it from the product repo root, or pass `--repo`.

## Commands

| Command | What it does |
|---|---|
| `shape <ref> --idea <text|file>` | Shaper, options phase; stops at the backlog gate for your choice |
| `shape <ref> --choice "<option>"` | Shaper, backlog phase; stops at the backlog gate |
| `stories <shape-id>` | The approved backlog as issue-ready stories (JSON) |
| `plan <ref> [--source …]` | Intake and plan on `delivery/<id>`; stops at the plan gate (unless `auto` applies) |
| `decide <id> <gate> approve|changes|reject` | Records your decision; in shadow mode it reveals the sealed recommendation |
| `build <id> [--comments …]` | Implement → four parallel checks → fix loop (≤ budget) → report; stops at the merge gate |
| `deliver <ref>` | `plan`, then `build` straight away if the plan gate auto-approves |
| `answer <id> "<text>"` | Answers an escalation and resumes the stage that raised it |
| `learn <id> [--merged]` | Records the merge-gate decision and runs Retro |
| `status` | Everything in `work/` and what is waiting on you |
| `calibration [--gate …]` | Agreement and regression stats per gate, against the policy thresholds |
| `contracts lock|verify|check` | Pins, verifies and checks contracts (see [contracts/README.md](../contracts/README.md)) |
| `github --event-name … --event-path …` | GitHub-native mode, used by [the reusable workflow](../.github/workflows/frontier.yml) |

Every command prints its outcome as JSON on stdout and the human-facing message as markdown on stderr. Exit codes: `0` advanced or waiting, `3` escalated, `2` error.

## Environment

| Variable | Default | Purpose |
|---|---|---|
| `FRONTIER_CLAUDE_BIN` | `claude` | The CLI to run (tests use a fake) |
| `FRONTIER_PLUGIN_DIR` | the process root | `--plugin-dir` for each session; `installed` uses the installed plugin instead |
| `FRONTIER_RECORDS` | `calibration.records` in the policy | Calibration log path (GitHub mode points it at the `frontier/metrics` branch copy) |
| `FRONTIER_BASE` | origin's default branch | Base branch for diffs |
| `FRONTIER_AGENT_TIMEOUT` | `3600` | Seconds per agent session |
| `FRONTIER_STRICT` | set to `1` for every session the runner starts | Makes the guard apply its rules to the main session too |

Headless sessions run with `runner.permission_mode` from the policy (default `bypassPermissions`). Run the runner only in a disposable checkout or container; the guard hooks still apply.

## GitHub-native mode

[`frontier/github.py`](frontier/github.py) maps events to commands:

| Event | Action |
|---|---|
| issue labelled `frontier:shape` | `shape`; posts the options; labels `frontier:gate-backlog` and `frontier:needs-decision` |
| issue labelled `frontier:deliver`, or `workflow_dispatch` | `plan` on `delivery/<id>`; opens a draft PR containing the plan; labels `frontier:gate-plan` |
| `/option n` on the idea issue | Writes the backlog for option *n* |
| `/approve` | Approves the pending gate and continues: publishes the stories, builds, or (merge gate) marks the PR ready for review |
| `/changes <text>` | Sends the stage back with your words verbatim |
| `/answer <text>` | Resumes from an escalation |
| `/reject` | Stops |
| PR with head `delivery/*` closed | `learn`: records merge vs close, posts the retro |

Only `OWNER`, `MEMBER` and `COLLABORATOR` comments are acted on. Calibration records go to `calibration.jsonl` on an orphan `frontier/metrics` branch, so they never touch `main`'s history.

## Frontier Workflow (deferred)

Running the process as a published workflow definition on Frontier Workflow (DAG on DTF + MAF, Azure Container Apps) waits on the contracts register (E27). It needs:

- **Contract publishing:** the schemas in `contracts/delivery/` registered as immutable, hash-addressed snapshots, and the definition carrying them inline by digest (ADR-2).
- **The engine validator:** one validator at every node boundary (closed JSON Schema plus CEL); the conformance cases here are its acceptance tests.
- **Node schema refs:** compilation currently rejects a schema ref declared on a node; only edges are exempt.

When those exist, the mapping is direct:

| Here | Frontier Workflow |
|---|---|
| `process/workflow.yaml` stages, `on:` transitions | DAG nodes and conditional edges |
| `contract: <id>@<major>` | Edge contract pinned by digest |
| Plan, backlog and merge gates | HITL coordination nodes; the gate policy bound as node-level governance policy (not part of the contract) |
| Budgets | Graph-enforced loop counters |
| Each `claude -p --agent` call | An agent node (MAF), or an adapter calling Claude Code headless |
| `orchestrate.py` | Retired; the engine is the orchestrator |

The interactive and GitHub modes stay useful after the move: the same roles, contracts and policy apply.
