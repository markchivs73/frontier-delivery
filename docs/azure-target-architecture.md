# Azure Target Architecture

> **Status, October 2026.** Superseded in part. The cloud target is now **Frontier Workflow** (DAG on DTF + MAF, Azure Container Apps), with contracts published to the Frontier registry under the E27 model (closed JSON Schema 2020-12 + CEL, pinned by hash). That binding is deferred until the register lands; see [runner/README.md](../runner/README.md#frontier-workflow-deferred). Migration steps 1 and 2 below are now built: the plugin plus the headless runner, and GitHub-native mode. The Foundry-specific choices below remain options, not commitments.

How the markdown-defined process in this repo promotes to an automated pipeline on Azure. Written against the mid-2026 platform state; **re-verify GA/preview status before building** (flagged per item).

## Platform choices

| Concern | Choice | Status (mid-2026) |
|---|---|---|
| Orchestration | **Microsoft Agent Framework (MAF)** typed workflow — sequential + handoff patterns; determinism in the graph, LLM judgment in the nodes | 1.0 GA (Apr 2026) |
| Agent runtime | **Foundry Agent Service** — prompt agents (`agent.yaml` / AgentSchema) for prompt-only roles; **hosted agents** (container, per-session VM sandbox, Entra agent identity) for roles that need shell | Runtime GA (Mar 2026); hosted agents GA (~Jul 2026) |
| Long-running state | **Durable Task extension for MAF** — resumable deliveries, human-gate pauses that survive restarts | GA |
| Tracker integration | **ADO remote MCP server** + **GitHub MCP server**, attached as Foundry MCP tools (Entra/OAuth auth) | ADO remote MCP preview (Mar 2026, in Foundry tool catalog); GitHub MCP GA |
| Code execution | Implementer's own hosted-agent sandbox (MAF **Agent Harness** shell tool) for the inner loop; **ACA dynamic sessions** (Hyper-V-isolated custom containers) if a separate sandbox is preferred; **existing CI** (ADO pipeline / GitHub Actions, triggered via MCP) as the authoritative test gate | Agent Harness new at Build 2026; ACA sessions GA; CI GA |
| Models | Mixed providers in Foundry: strong model (e.g. Claude Opus/Sonnet-class, GA in Foundry since Nov 2025, or GPT-5-era) for Planner/Implementer/Check agents; cheaper model for Analyst/Retro | GA |
| Observability & eval | Foundry tracing (OpenTelemetry) + evaluations; App Insights auto-injected for hosted agents | GA (Jun 2026) |

## Component mapping

Each markdown file here becomes a deployable artifact. The handoff envelopes in [process/handoffs.md](../process/handoffs.md) become the **typed message schemas on workflow edges** — this is the key property that makes the markdown phase a true prototype of the Azure phase.

| This repo | Azure artifact | Notes |
|---|---|---|
| `process/workflow.md` | MAF workflow graph (code-first, Python/.NET) + Durable Task | Routing table → edges/conditions; loop budgets → graph-enforced counters; gates → workflow request/response pauses |
| `process/handoffs.md` + `contracts/delivery/` | Registry contracts pinned on edges | Already closed JSON Schema 2020-12 + CEL; validation by the engine's single validator at every node boundary |
| `roles/orchestrator.md` | The workflow itself (not an LLM agent) | Most orchestrator rules become deterministic code — the biggest reliability win of promotion |
| `roles/requirements-analyst.md` | Foundry **prompt agent** (`agent.yaml`) + ADO/GitHub MCP tools (read-only) | Cheap model tier |
| `roles/planner.md` | Prompt agent + repo read access (MCP repo tools or a read-only sandbox checkout) | Strong model |
| `roles/implementer.md` | Foundry **hosted agent**: container with repo toolchain, MAF Agent Harness (shell, file, todo providers), git credentials via Entra agent identity | Works on `delivery/<id>` branch; optionally executes builds/tests in an ACA dynamic session pool instead of in-sandbox |
| `roles/check-*.md` (×4) | Prompt agents (architecture) / hosted agents (those that run tests), fanned out with MAF **concurrent** pattern | Fresh context is structural here: each gets only the diff + artifacts as input messages |
| `roles/retro.md` | Prompt agent + MCP (read PR threads) + repo write on a proposal branch | Triggered by PR-merged event (Foundry Routines or webhook → workflow) |
| `templates/*.md` | Unchanged — carried in the repo, written into `work/<id>/` | Artifacts stay git-versioned; git remains the shared memory |
| `adapters/README.md` tracker table | MCP tool allowlists per agent in Foundry tool config | Per-tool approval controls in Foundry |

## Flow on Azure

1. **Trigger**: ADO service hook / GitHub webhook (work item tagged e.g. `agent-deliver`) → starts a workflow instance; or manual start with inline requirements.
2. Workflow runs Analyst → Planner as prompt-agent nodes, writing artifacts to the delivery branch under `work/<id>/`.
3. **Gate 1**: workflow pauses (Durable request/response); approval surfaced via Teams (Foundry agents publish to Teams/M365) or an ADO/GitHub comment command; timeout → reminder → expiry policy.
4. Implementer hosted agent runs the task loop in its sandbox; pushes the branch.
5. Check fan-out (concurrent pattern) → findings merged by deterministic code → fix loop ≤ 3 enforced by the graph.
6. CI pipeline triggered via MCP as the authoritative test gate; draft PR opened and linked to the work item.
7. **Gate 2**: normal human PR review. Merge event triggers the Retro node; instruction-edit proposals arrive as PRs to this repo.

## Security posture

- Each agent gets a dedicated **Entra agent identity**; secretless access to ADO/GitHub/models; least privilege per the role contracts (check agents read-only, analyst read-only, implementer branch-scoped write, nobody can merge).
- Hosted-agent sandboxes are per-session isolated; network egress restricted (private networking is GA on the Foundry runtime).
- Branch policies in ADO/GitHub enforce the never-merge rule independently of agent behaviour — defense in depth for the human gate.

## Migration order (each step ships value alone)

1. **Now** — run the process via harness adapters (Claude Code / Copilot) locally. Iterate on role instructions; let Retro PRs harden them.
2. **CI-hosted** — run the same harness headless in GitHub Actions / ADO pipelines (e.g. `claude-code-action` triggered by issue label), still markdown-defined. Zero Foundry footprint; proves unattended operation.
3. **Foundry read-side** — promote Analyst + Planner to Foundry prompt agents (`agent.yaml` from the markdown role files); human still drives implement locally. Low risk, exercises MCP + identity setup.
4. **Foundry verify-side** — promote the check fan-out; run it against human- or locally-produced PRs (immediately useful as an AI review gate on all PRs, not just agent-authored ones).
5. **Foundry implement-side** — Implementer as a hosted agent with sandbox + CI gate.
6. **Full workflow** — MAF graph with Durable gates replaces the interactive orchestrator; Retro node closes the loop.

## Cost notes

- Foundry prompt roles/workflows: pay per model tokens + tool calls; hosted agents: container compute per hour (scale-to-zero) — keep the Implementer the only always-warm-capable component.
- The check fan-out is the token multiplier (4 fresh-context reads of the diff per iteration); budget ≈ tokens(diff+artifacts) × 4 × iterations. Loop budgets cap the worst case; model-tier routing keeps Analyst/Retro cheap.
- Alternative worth benchmarking before building step 5: the **GitHub Copilot coding agent** (triggerable from Azure Boards, custom agents via `.github/agents/*.agent.md`) as a managed implement-step, with this pipeline supplying requirements/plan/verification around it. Constraint: GitHub-hosted repos only.
