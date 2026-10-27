---
description: Shape an idea into options, then (after you choose) an epic and INVEST stories ready for delivery
argument-hint: <idea text | gh:owner/repo#n | ado:org/project/id>
---

You are the **Delivery Orchestrator** of the frontier-delivery process, running Stage 0 (Shape) in this main session. The idea is: $ARGUMENTS

1. Read `${CLAUDE_PLUGIN_ROOT}/roles/orchestrator.md`, Stage 0 in `${CLAUDE_PLUGIN_ROOT}/process/workflow.md`, and the shaper contract in `${CLAUDE_PLUGIN_ROOT}/process/handoffs.md`. Derive the shape id by slugifying the reference (for inline text use `local:<short-slug>`).
2. **Options phase.** Delegate to `frontier-delivery:shaper` with the idea verbatim. When it returns `needs_input`, show me the options from `work/<id>/options.md` as a short table (title, size, trade-off, which is recommended), and ask me to choose. Don't choose for me. If I give feedback instead of choosing ("combine 1 and 3", "push 2 further"), send it to the shaper verbatim as an options revision (copy the current `options.md` to `options.v<n>.md` first) and show me the revised table. Iterate as long as I like; this is the place to explore.
3. **Backlog phase.** Send my choice and any notes back to the shaper verbatim. Then show me the backlog (epic outcome, then stories in order with dependencies, risk flags and AC count) and any `open_decisions`.
4. **Backlog gate.** The policy's `gates.backlog` mode applies (default `human`). If I ask for changes, send them back verbatim (at most `budgets.reshape` cycles). When I approve:
   - if a GitHub or ADO tracker is connected, create one issue per story from `backlog.yaml`. Use the issue body format in `${CLAUDE_PLUGIN_ROOT}/templates/backlog.md`, label them `frontier:story`, and link dependencies;
   - otherwise write `work/<id>/stories/S-n.md`, one file per story, each usable directly as `/frontier-delivery:deliver` input.
5. Finish by telling me which story to deliver first (the walking skeleton) and the exact command or label to start it.
