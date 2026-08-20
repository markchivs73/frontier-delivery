# Industry Assessment & Design Rationale

Decision record for why this process is shaped the way it is. Research snapshot: **August 2026**.

## The original proposal and the verdict

The starting design was a 10-role pipeline: Orchestrator/Delivery, Technology, Requirements, Planning, Coding, Testing, Check (containing Software-Architecture + Security sub-agents), and Learn.

**Verdict: feasible and directionally correct — but the peer role-pipeline shape is the one pattern the industry has empirically retired.** Every responsibility was kept; the structure was changed to match the evidence below.

## What production systems actually converged on (2025–26)

Across GitHub Copilot coding agent, Devin, OpenAI Codex, Cursor, Google Jules, and Claude Code, the production decomposition is consistently:

> **planner phase → one strong executor loop (code + tests together, in an isolated sandbox/worktree) → separate fresh-context reviewer(s) → human gates at plan approval and PR review.**

Notable data points:

- **Cognition (Devin)** wrote the canonical ["Don't Build Multi-Agents"](https://cognition.com/blog/dont-build-multi-agents) (Jun 2025) — peer agents fail because sub-agents inherit the objective but not the implicit decisions behind it. By Feb 2026 they shipped multi-agent anyway, but only the disciplined form: one coordinator, isolated child sessions, **structured output schemas and playbooks making handoffs systematic**. That resolution is exactly this repo's shape.
- **MAST** (["Why Do Multi-Agent LLM Systems Fail?"](https://arxiv.org/abs/2503.13657), NeurIPS 2025): across 1,600+ annotated traces, failures cluster into specification issues (41.8%), **inter-agent misalignment / context loss (36.9%)**, and **weak verification (21.3%)**. Implication: fix the handoffs and the verification, don't add agents.
- **Fresh-context review agents are the part of multi-agent that clearly works**: Copilot Code Review went agentic (GA Mar 2026), CodeRabbit/Greptile/Bugbot made AI PR review a ~$420M ARR category; a second agent reviewing the diff before a human is now standard practice.
- **Spec-driven artifacts won**: AWS Kiro (requirements.md in EARS / design.md / tasks.md), GitHub Spec Kit (spec → plan → tasks → implement), AGENTS.md (Linux Foundation-stewarded, 60k+ repos). Structure lives in version-controlled markdown, not in the agent graph.
- **Cost compounds**: Anthropic's multi-agent research system used ~15× chat tokens; token spend explained ~80% of quality variance. Multi-agent only pays where the parallel work is genuinely independent (verification lenses are; coding is not).
- **DORA 2025**: AI adoption ~90%, throughput up ~20% — and incidents per PR up 23.5%. The empirical case for stronger verification gates rather than more generation.
- **Learning loops that work today are eval-driven prompt improvement**, not weight updates: GEPA-style reflective evolution of instructions from execution traces (ICLR 2026), Devin Knowledge, agents updating their own instruction files. Fully autonomous self-modification remains research.

## Role mapping (original → this repo)

| Original role | Became | Rationale |
|---|---|---|
| Orchestrator / Delivery | [orchestrator.md](../agents/orchestrator.md) | Orchestrator-worker is the endorsed pattern; rules are deterministic so most of this role becomes graph code on Azure |
| Technology | Discovery step inside [planner.md](../agents/planner.md) | One decision doesn't justify a context-loss seam; the *behaviour* (prompt the human when undefined) is preserved via `needs_input` |
| Requirements | [requirements-analyst.md](../agents/requirements-analyst.md) | Kept; hardened with the never-invent-ACs rule and EARS normalization |
| Planning | [planner.md](../agents/planner.md) | Kept; output is the Kiro/Spec-Kit artifact pair (design.md + tasks.md) — the inter-agent contract |
| Coding + Testing | [implementer.md](../agents/implementer.md) (one agent) | Coder/tester split is the classic misalignment seam (MAST bucket 2); the writer writes the tests, and independent *judgment* of tests moves to a check |
| Check (+ Architecture, Security subs) | Verification panel: [requirements](../agents/check-requirements.md) / [architecture](../agents/check-architecture.md) / [security](../agents/check-security.md) / [test-adequacy](../agents/check-test-adequacy.md) check agents, parallel, fresh-context | Evaluator-optimizer with diverse lenses — the strongest-evidence use of multiple agents; requirements-compliance and test-adequacy lenses added to the original pair |
| Learn | [retro.md](../agents/retro.md) | Scoped to what works: compare plan/outcome/check-vs-human findings, propose instruction diffs **as PRs** — never silent self-modification |

## Design rules adopted from the evidence

1. **Artifacts are the contract; envelopes are typed** ([handoffs.md](../process/handoffs.md)) — attacks MAST's 36.9% misalignment bucket; also what makes the markdown phase promotable to typed MAF workflow edges.
2. **Verbatim forwarding** — the orchestrator never summarizes another agent's output (summaries-of-summaries is the documented context-rot mechanism).
3. **Single writer** — parallel/plural writers need worktree isolation and merge machinery; a delivery has exactly one Implementer.
4. **Fresh-context check agents** — critics must not see the implementer's reasoning, or they inherit its blind spots.
5. **Bounded loops + escalation** — MAST's "premature termination" and infinite-grind failures are both cured by explicit budgets with a human fallback.
6. **Two human gates, never merge** — the universal production posture; nobody ships autonomous merge-to-main.
7. **Learning by PR** — instruction evolution with human review, matching how self-improvement actually works in production (GEPA-style), and keeping the Retro agent from weakening safety rules.

## Known risks carried forward

- **Verification token cost** (4 lenses × up to 3 loops) — mitigated by loop budgets and cheap-model routing for intake/retro; monitor per-delivery spend once automated.
- **Copilot adapter's role-switching** is weaker isolation than true subagents — documented in the adapter; prefer Claude Code locally, separate sessions for verify passes on Copilot.
- **MCP tool-name drift** — the capability table in [adapters/README.md](../adapters/README.md) is the single point to maintain.
- **Retro signal sparsity in local development** — the loop needs merged PRs with human comments to learn from; expect it to become useful only after a handful of real deliveries.
