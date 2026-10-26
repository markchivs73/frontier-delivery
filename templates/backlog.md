# Backlog: <epic title>

> Written by the Shaper in the backlog phase and approved by the human at the **backlog gate**. Each story becomes one tracker issue and one delivery. The machine-readable twin, `backlog.yaml`, is what gets published, so the two must agree.

## Epic
- **Title**: <epic title>
- **Outcome**: <the user-visible result when every story is done>
- **Chosen option**: <option title>; see `decision-log.md` D-<n>
- **Source idea**: <`gh:<owner>/<repo>#<n>` | `ado:…` | `local:<slug>`>

## Stories (delivery order)

### S-1: <imperative title> (walking skeleton)
- **Value**: <why this is worth shipping on its own>
- **Depends on**: none
- **Size**: S | M
- **Risk flags**: none | auth | data-migration | infra | public-api | <other>
- **Acceptance criteria**
  - AC-1: WHEN <trigger> THE SYSTEM SHALL <response>
  - AC-2: …

### S-2: …

## Open decisions
> Questions that did not block the backlog but must be answered before the named story is planned. Empty is fine.

- <question>: blocks S-<n>

---

## `backlog.yaml` schema

```yaml
epic:
  title: <string>
  outcome: <string>
  chosen_option: <string>
  source: <work-item ref>
stories:
  - id: S-1
    title: <imperative title>
    value: <string>
    depends_on: []              # story ids
    size: S | M
    risk_flags: []              # e.g. [auth, data-migration]
    acceptance_criteria:
      - id: AC-1
        ears: "WHEN … THE SYSTEM SHALL …"
open_decisions:
  - question: <string>
    blocks: [S-2]
```

The publisher creates each story as an issue whose body carries the value, dependencies, risk flags and EARS ACs in [requirements.md](requirements.md) shape, so the Requirements Analyst accepts them unchanged at intake.
