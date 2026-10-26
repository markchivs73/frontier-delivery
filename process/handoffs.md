# Handoff Contracts

Every agent finishes by returning a **handoff envelope** in two places:
1. Written to `work/<id>/envelopes/<agent>.yaml` (overwriting any earlier one). The runner reads this file. It is the only path under `work/` that the read-only check agents may write.
2. Repeated as the final fenced YAML block of the agent's reply, for interactive sessions.

The orchestrator routes on `status` and never edits an envelope's content.

This file is the readable form of the contracts. The machine form is [contracts/delivery/](../contracts/delivery/): one closed JSON Schema 2020-12 contract per envelope, with CEL rules for the cross-field invariants noted below, pinned by hash in `contracts/contracts.lock.json` and validated by the runner on every handoff (see [contracts/README.md](../contracts/README.md)). A change here must be mirrored there, with conformance cases, in the same commit. Each agent definition in [roles/](../roles/) names its inputs and outputs by reference to this file. When the process runs on Frontier Workflow, these contracts are published to the registry and pinned on the corresponding workflow edges.

## Common envelope

```yaml
agent: <agent name>            # e.g. requirements-analyst
work_item: <id>                # ado:<org>/<project>/<id> | gh:<owner>/<repo>#<n> | local:<slug>
status: ok | needs_input | failed
artifacts: [<paths written>]   # files under work/<id>/
needs_input:                   # required when status: needs_input
  question: <smallest question that unblocks>
  options: [<option>, ...]     # optional, when a choice can be offered
summary: <2-3 sentences, human-readable>
```

Statuses: `ok` — stage complete, artifacts valid; `needs_input` — blocked on a human decision (orchestrator escalates); `failed` — stage could not complete after its own retries (orchestrator escalates with the error).

## Per-agent extensions

### shaper → orchestrator
`<id>` is the shape id (for example `gh-owner-repo-12` for the idea issue).
```yaml
phase: options | backlog
options:                             # phase: options
  - title: <option title>
    summary: <2-3 sentences>
    recommended: true | false
    size_stories: <n>
chosen_option: <title>               # phase: backlog, required for status: ok
story_count: <n>                     # phase: backlog, ≥ 1 for status: ok
open_decisions: [<question>, ...]
```
In the options phase `status` is `needs_input`, and `needs_input.options` lists the option titles.

### requirements-analyst → orchestrator
```yaml
artifacts: [work/<id>/requirements.md]
source: ado | github | inline
acceptance_criteria_count: <n>       # must be ≥ 1 for status: ok
gaps: [<missing info>]               # populated when status: needs_input
risk_flags: [<flag>, ...]            # carried from the story (e.g. auth, data-migration)
```

### planner → orchestrator
```yaml
artifacts: [work/<id>/design.md, work/<id>/tasks.md]
technology:
  detected: <stack summary or "none">
  source: repo | user | undefined     # undefined ⇒ status must be needs_input
task_count: <n>
acceptance_test_count: <n>           # tests in design.md's Acceptance test plan; ≥ 1 for status: ok
planned_paths: [<path or glob>, ...] # every path the plan expects to touch; used for the risk tier
risks: [<risk>, ...]
```

### implementer → orchestrator
```yaml
branch: delivery/<id>
tasks_completed: { done: <n>, total: <n> }   # done == total for status: ok
test_run:
  command: <how tests were run>
  passed: <n>
  failed: <n>                        # must be 0 for status: ok
ac_self_check:                       # one entry per acceptance criterion in requirements.md
  - ac: AC-1
    met: true | false
    evidence: <file/test that demonstrates it>
fix_iteration: <0-3>                 # 0 on first pass; incremented per verify loop
```

### check-* → orchestrator
All four check agents (`check-requirements`, `check-architecture`, `check-security`, `check-test-adequacy`) share one findings schema:
```yaml
check: requirements | architecture | security | test-adequacy
verdict: pass | fail                 # fail iff any blocking finding
findings:
  - id: <CHECK>-<n>               # e.g. SEC-1, REQ-2, ARC-1, TST-3
    severity: blocking | advisory
    location: <file:line or artifact section>
    finding: <one-sentence defect statement>
    evidence: <why this is real — concrete input/state/scenario>
    required_action: <what the implementer must change>   # blocking only
```
Check ground rules: findings must cite evidence (no vibes); an unverifiable suspicion is `advisory`, never `blocking`; check agents propose actions but never write code.

### orchestrator → human (escalation)
```yaml
stage: shape | intake | plan | gate-backlog | gate-plan | implement | verify | deliver | gate-merge | learn
attempted: <what was done>
blocking: <what is blocking>
question: <smallest question that unblocks>
options: [<option>, ...]
```

### gate → calibration log
Written by the orchestrator/runner, one JSON line per gate decision, to the policy's `calibration.records` (GitHub mode: `calibration.jsonl` on the `frontier/metrics` branch).
```yaml
gate: backlog | plan | merge
work_item: <ref>
mode: human | shadow | auto
recommendation: approve | changes | escalate   # sealed until the human decides
risk_tier: low | medium | high
reasons: [<why>, ...]
decision: approve | changes | reject | auto-approved
decided_by: <login | policy>
agreed: true | false
outcome: unknown | kept | reverted | incident   # updated later; feeds the regression rule
decided_at: <ISO-8601>
policy_version: <n>
```

### retro → repo
```yaml
artifacts: [learnings.md]
lessons:
  - observation: <plan-vs-outcome or check-vs-human-review gap>
    agent: <which agent definition it implicates>
    proposed_change: <instruction edit, or "none — process worked">
instruction_prs: [<branch/PR ref>, ...]   # empty if no changes proposed
```

## Routing table

| From | status | Orchestrator action |
|---|---|---|
| shaper | needs_input (phase: options) | backlog gate: human picks an option |
| shaper | ok (phase: backlog) | backlog gate per policy |
| backlog gate | option chosen / changes | re-invoke shaper with the choice/comments verbatim (≤ `budgets.reshape`) |
| backlog gate | approved | publish `backlog.yaml` as tracker issues; auto-start per policy |
| requirements-analyst | ok | invoke planner |
| requirements-analyst | needs_input | escalate: missing ACs/gaps |
| planner | ok | plan gate per policy (human / shadow / auto) |
| planner | needs_input | escalate: technology choice / ambiguity |
| plan gate | approved (human or auto) | invoke implementer |
| plan gate | changes | re-invoke planner with comments verbatim (≤ `budgets.replan`) |
| implementer | ok | invoke all four check agents in parallel |
| check agents | all pass | deliver: PR + verification report → merge gate per policy |
| check agents | any fail | re-invoke implementer with blocking findings verbatim (at most `budgets.verify_fix` verify passes in total) |
| check agents | loop budget hit | escalate with outstanding findings; `/answer accept` delivers with them recorded, `/answer <guidance>` starts a fresh loop |
| merge gate | changes | re-invoke implementer with the human's comments verbatim |
| merge gate | auto | runner enables auto-merge (branch protection still applies) |
| PR merged/closed | — | record merge-gate calibration, invoke retro |
| any | failed | escalate with error detail |
