# Contracts

The handoff envelopes in [process/handoffs.md](../process/handoffs.md), as data. They follow the **E27 contracts-as-data model** (the Kubernetes CRD analogue) so they can move into the Frontier registry as they are:

| Kubernetes | Here |
|---|---|
| Structural (closed) OpenAPI schema | Closed JSON Schema 2020-12: `additionalProperties: false` on every object, no remote `$ref` |
| `x-kubernetes-validations` CEL rules scoped to `self` | `x-frontier-validations`: `[{rule, message}]`, CEL scoped to `self`, no I/O, no cross-contract lookups |
| Rules type-checked at CRD write | Rules compiled when the runner loads the contract set; a rule that doesn't compile fails loading |
| Generic validator in the API server | One validator in the runner, applied to every envelope whichever agent produced it |
| Immutable versions | `contracts.lock.json` pins each contract by id, major and sha256 of its canonical bytes; the runner refuses bytes that don't match |
| ValidatingAdmissionPolicy | The gate policy ([policy/](../policy/)) is bound separately; it is configuration, not a contract |

## Layout

```
contracts/
  contracts.lock.json                 # id → major, file, sha256 digest
  delivery/
    <name>.v1.schema.json             # one closed schema per contract, rules inside
    conformance/<name>.yaml           # valid and invalid payloads with expected verdicts
```

Contract ids are `frontier.delivery.<name>` with a major version; `process/workflow.yaml` names the contract on each stage's output edge as `<id>@<major>`.

## Working with contracts

```bash
export PYTHONPATH=runner
python -m frontier contracts verify                  # pins match bytes, every rule compiles
python -m frontier contracts check --contract frontier.delivery.planner-envelope --file work/x/envelopes/planner.yaml
python -m frontier contracts lock                    # re-pin after an intentional change (unpublished majors only)
python -m pytest tests/test_contracts.py             # conformance cases
```

The rules for changing a contract:
- A published major is immutable. A breaking change (a new required field, a narrowed enum, a stricter rule) means a new `.v2.schema.json` and a new id@major on the edge, never an edit to v1.
- Every change carries conformance cases: at least one valid payload and one invalid payload per rule, each tagged with the rule message it should trip (`violates`), or `structural: true` for a schema-level rejection.

## Conformance cases are implementation-neutral

The `conformance/` files are written to be run by any implementation of the contract model, not just this runner. The engine's .NET validator (closed JSON Schema plus a CEL library) should give exactly the same verdicts. That makes these cases a ready-made cross-implementation check for the CEL-on-.NET feasibility risk. The cases use YAML anchors and merge keys (`<<:`); expand them to JSON first if your loader doesn't support merge keys.

## Assumptions to revisit when the registry lands

- **Rule placement.** Rules are embedded in the schema (`x-frontier-validations`), the way CRDs embed theirs. If E27 stores rules alongside the schema, split them out and keep the digest over both.
- **Canonicalisation.** Digests use sorted-key, compact, UTF-8 JSON, which equals RFC 8785 (JCS) for these documents because they contain no floats. Align with the registry's canonical hashing and re-lock.
- **Publishing.** This repo stands in for the registry. At publish, a definition would pin each contract by digest and carry its bytes inline, matching ADR-2: no fetch mid-run.
- **Cost budgets.** CEL cost estimation at registration and runtime budgets are not implemented here. The rules are small, fixed and loop over arrays of bounded size.
