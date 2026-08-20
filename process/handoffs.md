# Handoff Contracts

Every agent finishes by returning a **handoff envelope**: a fenced YAML block, plus any artifact files it wrote under `work/<id>/`. The orchestrator routes on `status` and never edits an envelope's content.

These contracts are the source of truth. Each agent definition in [agents/](../agents/) names its inputs and outputs by reference to this file. When this pipeline is promoted to Azure (Microsoft Agent Framework), each envelope becomes the typed message schema on the corresponding workflow edge — see [docs/azure-target-architecture.md](../docs/azure-target-architecture.md).

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

### requirements-analyst → orchestrator
```yaml
artifacts: [work/<id>/requirements.md]
source: ado | github | inline
acceptance_criteria_count: <n>       # must be ≥ 1 for status: ok
gaps: [<missing info>]               # populated when status: needs_input
```

### planner → orchestrator
```yaml
artifacts: [work/<id>/design.md, work/<id>/tasks.md]
technology:
  detected: <stack summary or "none">
  source: repo | user | undefined     # undefined ⇒ status must be needs_input
task_count: <n>
risks: [<risk>, ...]
```

### implementer → orchestrator
```yaml
branch: delivery/<id>
tasks_completed: <n>/<n>
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
stage: intake | plan | gate-plan | implement | verify | deliver
attempted: <what was done>
blocking: <what is blocking>
question: <smallest question that unblocks>
options: [<option>, ...]
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
| requirements-analyst | ok | invoke planner |
| requirements-analyst | needs_input | escalate: missing ACs/gaps |
| planner | ok | present plan → human gate #1 |
| planner | needs_input | escalate: technology choice / ambiguity |
| human gate #1 | approved | invoke implementer |
| human gate #1 | changes | re-invoke planner with comments verbatim (≤ 2 cycles) |
| implementer | ok | invoke all four check agents in parallel |
| check agents | all pass | deliver: draft PR + verification report |
| check agents | any fail | re-invoke implementer with blocking findings verbatim (≤ 3 loops) |
| check agents | loop budget hit | escalate with outstanding findings |
| PR merged/closed | — | invoke retro |
| any | failed | escalate with error detail |
