# Evals and calibration

Two feedback loops keep the process honest. Both are evidence-driven, and neither changes anything without a human-reviewed PR.

## 1. Gate calibration (is this gate ready to open?)

Every decision at a `shadow` or `auto` gate appends one record (contract `frontier.delivery.gate-record@1`) to the calibration log: the **sealed** recommendation, the risk tier and reasons, your decision, whether you agreed, and later the downstream outcome (`kept`, `reverted`, `incident`).

- **Local:** `.frontier/calibration.jsonl` (the policy's `calibration.records`), with sealed recommendations in `.frontier/sealed.json`.
- **GitHub mode:** `calibration.jsonl` and `sealed.json` on the orphan `frontier/metrics` branch, written only by the runner.

Sealed recommendations never go into `work/<id>/state.yaml`, which is committed and visible on the PR.

```bash
PYTHONPATH=runner python -m frontier calibration
```

This reports, per gate, the number of human-decided samples, the agreement rate, recent false approvals, and whether the gate is **eligible** for `auto` under the policy thresholds (`min_samples`, `min_agreement`, `regression`).

To open a gate:
1. Run it in `shadow` until it's eligible.
2. Raise a PR changing `gates.<gate>.mode` to `auto`, with the calibration output in the description. The policy `owner` approves it.
3. The runner keeps re-checking. If the evidence drops below the thresholds, or the regression window shows too many false approvals, the gate quietly reverts to `shadow` and says so in its next request. Closing doesn't need a PR.

Why sealed: if you could see the recommendation before deciding, the agreement rate would measure how often you defer to it, not whether it's right.

**Outcome tracking (to do):** marking a merged change as `reverted` or `incident` is manual today (edit the record's `outcome`). A revert-detecting job is the natural next step, and it matters because the regression rule counts those outcomes.

## 2. Process evals (are the roles getting better?)

The Retro agent compares plan vs outcome, check findings vs what humans caught in review, and gate recommendations vs your decisions, then proposes instruction edits as PRs.

Planned next: a `golden/` set of small, fixed deliveries (a requirements text, a seed repo, and the expected ACs, plan shape and findings) re-run against role-instruction changes before they merge, so a Retro PR comes with evidence that it didn't regress something else. Until then, `tests/` covers the deterministic parts: guard, gates, runner loop, GitHub glue and contract conformance.
