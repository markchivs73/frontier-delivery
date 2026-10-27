# Design — <work item title>

> Written by the Planner; approved by the human at Gate #1. The Implementer follows this; the architecture check judges conformance to it. Structural deviation after approval requires going back through the orchestrator.

## Technology
- **Detected stack**: <language, framework(s), test framework, build tooling>
- **Source**: <repo | user> — <evidence: manifests/CI files inspected, or the human's recorded choice>

## Approach
<The solution in 3–8 sentences: the shape of the change, where it lives in the codebase, and why this approach over the plausible alternative.>

## Components & interfaces
| Component | Location | Change | Notes |
|---|---|---|---|
| <name> | `path/` | new / modified | <interface or responsibility> |

## Reuse
> Existing code the implementation MUST use rather than reinventing. New abstractions require justification here.

- `path/to/util.ext` — <what it provides, where it's used in this design>

## Data & contracts
<New/changed data models, API shapes, events, migrations. "None" is fine.>

## AC coverage map
> Every AC in requirements.md must appear here. This is checked at Gate #1.

| AC | How the design satisfies it | Where |
|---|---|---|
| AC-1 | <mechanism> | <component> |

## Acceptance test plan
> The executable definition of done, reviewed at Gate #1. Task T1 writes exactly these tests (failing) before any production code. Every AC appears at least once.

| AC | Test (file :: name) | Level | Asserts |
|---|---|---|---|
| AC-1 | `tests/…::test_…` | unit / functional / integration | <the observable outcome that fails today> |

## Planned paths
> Every file or glob this plan expects to create or modify (mirrors `planned_paths` in the planner envelope). Used by the plan gate to set the risk tier.

- `src/…`

## Test strategy
<Which ACs need unit vs functional vs integration coverage, and how tests will run locally (command). Test-writing tasks live inside tasks.md alongside their code.>

## Risks & mitigations
- <risk> — <mitigation or accepted>

## Out of scope
<Restated from requirements.md plus anything this design deliberately defers.>
