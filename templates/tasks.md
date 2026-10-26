# Tasks — <work item title>

> Written by the Planner; approved with the design at Gate #1. The Implementer executes in order and ticks each box on completion (the only edits it makes to this file). Every task pairs code with its tests — testing is not a separate phase.

- [ ] **T1: Acceptance tests (failing)**
  - What: write the tests in design.md's *Acceptance test plan*, exactly as approved
  - Where: <test paths>
  - Done when: every acceptance test runs and fails because the behaviour is absent (not a compile/fixture error); committed before any production code
  - Covers: <all AC-n>

- [ ] **T2 — <short imperative title>**
  - What: <the change>
  - Where: `path/to/file(s)`
  - Tests: <the test(s) written in this task>
  - Done when: <observable completion condition>
  - Covers: <AC-n, …>

- [ ] **T3 — …**
  - What: …
  - Where: …
  - Tests: …
  - Done when: …
  - Covers: …

- [ ] **T-final — Full suite & AC self-check**
  - What: run the complete test suite; record per-AC evidence in the handoff envelope (`ac_self_check`)
  - Done when: zero failing tests; every AC has evidence or is explicitly flagged
