"""Assembling work/<id>/verification-report.md from the check envelopes (deterministic)."""
from __future__ import annotations

from .envelopes import CHECK_AGENTS

LABELS = {
    "check-requirements": "Requirements compliance",
    "check-architecture": "Architecture & patterns",
    "check-security": "Security",
    "check-test-adequacy": "Test adequacy",
}


def blocking_findings(checks: dict[str, dict]) -> list[dict]:
    return [dict(f, check=c["check"]) for c in checks.values() for f in c.get("findings", []) if f["severity"] == "blocking"]


def advisory_findings(checks: dict[str, dict]) -> list[dict]:
    return [dict(f, check=c["check"]) for c in checks.values() for f in c.get("findings", []) if f["severity"] == "advisory"]


def summary_table(checks: dict[str, dict], fix_iterations: int, outcome: str) -> str:
    rows = []
    for agent in CHECK_AGENTS:
        env = checks.get(agent)
        if not env:
            rows.append(f"| {LABELS[agent]} | not run | - | - |")
            continue
        b = sum(1 for f in env["findings"] if f["severity"] == "blocking")
        a = sum(1 for f in env["findings"] if f["severity"] == "advisory")
        rows.append(f"| {LABELS[agent]} | {env['verdict']} | {b} | {a} |")
    return "\n".join([
        "| Check | Verdict | Blocking | Advisory |",
        "|---|---|---|---|",
        *rows,
        "",
        f"- **Fix iterations used**: {fix_iterations}",
        f"- **Outcome**: {outcome}",
    ])


def _cell(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def render(title: str, checks: dict[str, dict], implementer: dict, fix_iterations: int, outcome: str, history: list[dict]) -> str:
    blocking = blocking_findings(checks)
    advisory = advisory_findings(checks)
    lines = [f"# Verification Report: {title}", "", "> Assembled by the frontier-delivery runner from the four check envelopes.", "", "## Summary", summary_table(checks, fix_iterations, outcome), ""]
    lines += ["## Blocking findings", ""]
    if blocking:
        lines += ["| ID | Check | Location | Finding | Required action |", "|---|---|---|---|---|"]
        lines += [f"| {f['id']} | {f['check']} | `{_cell(f['location'])}` | {_cell(f['finding'])} | {_cell(f.get('required_action', ''))} |" for f in blocking]
    else:
        lines.append("None open.")
    lines += ["", "## Advisory findings", ""]
    if advisory:
        lines += ["| ID | Check | Location | Finding |", "|---|---|---|---|"]
        lines += [f"| {f['id']} | {f['check']} | `{_cell(f['location'])}` | {_cell(f['finding'])} |" for f in advisory]
    else:
        lines.append("None.")
    lines += ["", "## AC verification", "", "| AC | Implementer evidence | Met |", "|---|---|---|"]
    lines += [f"| {a['ac']} | {_cell(a.get('evidence', ''))} | {'yes' if a.get('met') else 'no'} |" for a in implementer.get("ac_self_check", [])]
    lines += ["", "## History", ""]
    for h in history:
        ids = ", ".join(h.get("blocking", [])) or "none"
        lines.append(f"- Iteration {h['iteration']}: blocking findings: {ids}")
    return "\n".join(lines) + "\n"
