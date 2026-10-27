"""Markdown the runner hands to humans: gate requests, reveals, escalations, PR bodies.
Used verbatim as issue/PR comments in GitHub mode and printed in local mode."""
from __future__ import annotations

from pathlib import Path

COMMANDS = {
    "backlog-options": "Reply `/option <number or title>` (add notes on the following lines), `/changes <feedback>` for a revised set of options, or `/reject`.",
    "backlog": "Reply `/approve`, `/changes <what to change>`, or `/reject`.",
    "plan": "Reply `/approve`, `/changes <what to change>`, or `/reject`.",
    "merge": "Review and merge the PR yourself, or reply `/changes <what to change>`. `/approve` marks the PR ready for review.",
    "escalation": "Reply `/answer <your answer>` to resume, or `/reject` to stop.",
}

MARKER = "<!-- frontier-delivery -->"


def _mode_line(gate_state: dict) -> str:
    mode = gate_state.get("mode", "human")
    if mode == "shadow":
        return "**Mode: shadow.** A recommendation has been sealed and will be revealed after your decision, so your call stays independent."
    if mode == "auto":
        return f"**Mode: auto.** Approved automatically (risk tier `{gate_state.get('risk_tier')}`)."
    return "**Mode: human.**"


def _notes(gate_state: dict) -> str:
    notes = gate_state.get("notes") or []
    return "".join(f"\n> {n}" for n in notes)


def backlog_options(work_id: str, envelope: dict, gate_state: dict, revision: int = 0) -> str:
    rows = "\n".join(
        f"| {i} | {o['title']}{' (recommended)' if o.get('recommended') else ''} | {o.get('size_stories', '?')} | {o['summary']} |"
        for i, o in enumerate(envelope.get("options", []), 1)
    )
    question = (envelope.get("needs_input") or {}).get("question", "Which option should be taken forward?")
    heading = f"Shaping: revised options (round {revision})" if revision else "Shaping: choose an option"
    files = [h["file"] for h in gate_state.get("history", []) if h.get("file")]
    previous = f"\nEarlier versions: {', '.join(f'`work/{work_id}/{f}`' for f in files)}." if files else ""
    return f"""{MARKER}
### {heading}

{question}

| # | Option | Stories | Summary |
|---|---|---|---|
{rows}

Full write-up: `work/{work_id}/options.md`. Decisions already settled: `work/{work_id}/decision-log.md`.{previous}

{COMMANDS['backlog-options']}"""


def backlog(work_id: str, envelope: dict, backlog_data: dict, gate_state: dict) -> str:
    stories = "\n".join(
        f"- **{s['id']}: {s['title']}** ({s.get('size', '?')}"
        f"{', depends on ' + ', '.join(s['depends_on']) if s.get('depends_on') else ''}"
        f"{', risk: ' + ', '.join(s['risk_flags']) if s.get('risk_flags') else ''}), {len(s.get('acceptance_criteria', []))} ACs"
        for s in backlog_data.get("stories", [])
    )
    epic = backlog_data.get("epic", {})
    return f"""{MARKER}
### Backlog ready for approval: {epic.get('title', work_id)}

**Outcome:** {epic.get('outcome', '')}
**Chosen option:** {envelope.get('chosen_option', '')}

{stories}

Full backlog: `work/{work_id}/backlog.md`.

{_mode_line(gate_state)}{_notes(gate_state)}

{COMMANDS['backlog']}"""


def plan(work_id: str, planner: dict, gate_state: dict) -> str:
    tech = planner.get("technology", {})
    risks = "".join(f"\n  - {r}" for r in planner.get("risks", [])) or " none reported"
    return f"""{MARKER}
### Plan ready for approval

- **Stack:** {tech.get('detected')} (source: {tech.get('source')})
- **Tasks:** {planner.get('task_count')}, of which T1 writes **{planner.get('acceptance_test_count')} acceptance tests**
- **Planned paths:** {', '.join(f'`{p}`' for p in planner.get('planned_paths', []))}
- **Risks:**{risks}

Review `work/{work_id}/design.md`, starting with its **Acceptance test plan** (the executable definition of done), then `tasks.md` and `requirements.md`.

{_mode_line(gate_state)}{_notes(gate_state)}

{COMMANDS['plan']}"""


def merge(work_id: str, gate_state: dict, report_summary: str) -> str:
    return f"""{MARKER}
### Ready for your review

{report_summary}

Full report: `work/{work_id}/verification-report.md`.

{_mode_line(gate_state)}{_notes(gate_state)}

{COMMANDS['merge']}"""


def reveal(gate: str, rec: dict) -> str:
    verdict = "agreed with" if rec["agreed"] else "**disagreed** with"
    reasons = "".join(f"\n- {r}" for r in rec.get("reasons", []))
    return f"""{MARKER}
Recorded `{rec['decision']}` at the {gate} gate. The sealed recommendation was `{rec['recommendation']}` (risk `{rec['risk_tier']}`), so you {verdict} it.{reasons}"""


def escalation(esc: dict) -> str:
    options = "".join(f"\n- {o}" for o in esc.get("options", []))
    return f"""{MARKER}
### Needs your decision ({esc['stage']})

**Blocking:** {esc['blocking']}
**Attempted:** {esc['attempted']}

**Question:** {esc['question']}{options}

{COMMANDS['escalation']}"""


def pr_body(work_item: str, work_id: str, report_summary: str, implementer: dict, closes: str | None) -> str:
    acs = "\n".join(
        f"| {a['ac']} | {'yes' if a.get('met') else 'no'} | {a.get('evidence', '')} |" for a in implementer.get("ac_self_check", [])
    )
    test = implementer.get("test_run", {})
    closing = f"\n\nCloses {closes}" if closes else ""
    return f"""Delivery for `{work_item}` via frontier-delivery.

{report_summary}

**Tests:** `{test.get('command', '')}`: {test.get('passed', 0)} passed, {test.get('failed', 0)} failed.

| AC | Met | Evidence |
|---|---|---|
{acs}

Artifacts: `work/{work_id}/` (requirements, design, tasks, verification report, state).{closing}"""


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""
