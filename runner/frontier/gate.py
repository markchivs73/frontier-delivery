"""Gate evaluation: risk tiers, recommendations, policy modes and calibration.

Everything here is deterministic. An LLM never decides whether a gate opens;
it only produces the artifacts these functions judge.
"""
from __future__ import annotations

import fnmatch
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

TIERS = ["low", "medium", "high"]


@dataclass
class Evaluation:
    gate: str
    recommendation: str              # approve | changes | escalate
    risk_tier: str                   # low | medium | high
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _max_tier(*tiers: str) -> str:
    return max(tiers, key=TIERS.index)


def path_is_protected(path: str, protected: list[str]) -> str | None:
    path = path.strip().removeprefix("./")
    for pattern in protected:
        if fnmatch.fnmatch(path, pattern) or fnmatch.fnmatch(path, pattern.removeprefix("**/")):
            return pattern
        # A planned glob such as "infra/**" overlaps a protected "infra/**".
        if fnmatch.fnmatch(pattern, path) or path.rstrip("/*") == pattern.rstrip("/*"):
            return pattern
    return None


def _size_tier(policy: dict, *, lines: int | None = None, files: int | None = None, tasks: int | None = None) -> tuple[str, list[str]]:
    reasons: list[str] = []
    risk = policy["risk"]
    tier = "low"
    for name, value, key in (("changed lines", lines, "max_changed_lines"),
                             ("changed files", files, "max_changed_files"),
                             ("tasks", tasks, "max_tasks")):
        if value is None:
            continue
        low, medium = risk["low"].get(key), risk["medium"].get(key)
        if medium is not None and value > medium:
            tier = _max_tier(tier, "high")
            reasons.append(f"{value} {name} exceeds the medium limit ({medium})")
        elif low is not None and value > low:
            tier = _max_tier(tier, "medium")
            reasons.append(f"{value} {name} exceeds the low limit ({low})")
    return tier, reasons


# ---- backlog ---------------------------------------------------------------
def evaluate_backlog(policy: dict, envelope: dict, backlog: dict | None) -> Evaluation:
    reasons: list[str] = []
    tier = "low"
    high_flags = set(policy["risk"].get("high_risk_flags", []))
    stories = (backlog or {}).get("stories") or []
    flagged = sorted({f for s in stories for f in s.get("risk_flags", []) if f in high_flags})
    if flagged:
        tier = "high"
        reasons.append(f"stories carry high-risk flags: {', '.join(flagged)}")
    elif len(stories) > 8:
        tier = "medium"
        reasons.append(f"{len(stories)} stories; consider splitting the epic")
    problems = backlog_problems(backlog)
    if problems:
        return Evaluation("backlog", "changes", tier, reasons + problems)
    if envelope.get("open_decisions"):
        return Evaluation("backlog", "escalate", tier, reasons + ["open decisions remain: " + "; ".join(envelope["open_decisions"])])
    return Evaluation("backlog", "approve", tier, reasons or ["stories are INVEST-shaped with EARS ACs"])


def backlog_problems(backlog: dict | None) -> list[str]:
    if not isinstance(backlog, dict) or not backlog.get("stories"):
        return ["backlog.yaml is missing or has no stories"]
    problems = []
    ids = {s.get("id") for s in backlog["stories"]}
    for story in backlog["stories"]:
        sid = story.get("id", "?")
        acs = story.get("acceptance_criteria") or []
        if not story.get("title"):
            problems.append(f"{sid} has no title")
        if not acs:
            problems.append(f"{sid} has no acceptance criteria")
        if len(acs) > 7:
            problems.append(f"{sid} has {len(acs)} ACs; too big for one delivery")
        for ac in acs:
            text = str(ac.get("ears", "")).upper()
            if "SHALL" not in text:
                problems.append(f"{sid} {ac.get('id', '?')} is not in EARS form")
        for dep in story.get("depends_on") or []:
            if dep not in ids:
                problems.append(f"{sid} depends on unknown story {dep}")
    return problems


# ---- plan ------------------------------------------------------------------
def evaluate_plan(policy: dict, planner: dict, analyst: dict | None = None) -> Evaluation:
    reasons: list[str] = []
    protected = policy["risk"]["protected_paths"]
    tier, size_reasons = _size_tier(policy, tasks=planner.get("task_count"))
    reasons += size_reasons
    hits = sorted({p for path in planner.get("planned_paths", []) if (p := path_is_protected(path, protected))})
    if hits:
        tier = "high"
        reasons.append(f"plan touches protected paths: {', '.join(hits)}")
    if (planner.get("technology") or {}).get("source") == "user":
        tier = "high"
        reasons.append("technology was chosen by the human for this plan (new stack decision)")
    high_flags = set(policy["risk"].get("high_risk_flags", []))
    flags = sorted(set((analyst or {}).get("risk_flags", [])) & high_flags)
    if flags:
        tier = "high"
        reasons.append(f"story risk flags: {', '.join(flags)}")
    if planner.get("risks"):
        tier = _max_tier(tier, "medium")
        reasons.append(f"planner reported {len(planner['risks'])} risk(s)")
    if not planner.get("planned_paths"):
        return Evaluation("plan", "changes", "high", reasons + ["planner did not report planned_paths"])
    if not planner.get("acceptance_test_count"):
        return Evaluation("plan", "changes", tier, reasons + ["no acceptance tests planned"])
    return Evaluation("plan", "approve", tier, reasons or ["small plan, no protected paths, no reported risks"])


# ---- merge -----------------------------------------------------------------
@dataclass
class DiffStats:
    files: list[str]
    lines: int


def evaluate_merge(policy: dict, diff: DiffStats, checks: list[dict], implementer: dict, fix_iterations: int) -> Evaluation:
    reasons: list[str] = []
    protected = policy["risk"]["protected_paths"]
    tier, size_reasons = _size_tier(policy, lines=diff.lines, files=len(diff.files))
    reasons += size_reasons
    hits = sorted({p for f in diff.files if (p := path_is_protected(f, protected))})
    if hits:
        tier = "high"
        reasons.append(f"change touches protected paths: {', '.join(hits)}")
    blocking = [f for c in checks for f in c.get("findings", []) if f.get("severity") == "blocking"]
    advisory = [f for c in checks for f in c.get("findings", []) if f.get("severity") == "advisory"]
    auto_when = policy["gates"]["merge"].get("auto_when") or {}
    max_adv = auto_when.get("max_advisory_findings")
    if max_adv is not None and len(advisory) > max_adv:
        tier = _max_tier(tier, "medium")
        reasons.append(f"{len(advisory)} advisory findings (limit {max_adv})")
    max_fix = auto_when.get("max_fix_iterations")
    if max_fix is not None and fix_iterations > max_fix:
        tier = _max_tier(tier, "medium")
        reasons.append(f"needed {fix_iterations} fix iterations (limit {max_fix})")
    if blocking:
        return Evaluation("merge", "changes", tier, reasons + [f"{len(blocking)} blocking finding(s) open"])
    failed = (implementer.get("test_run") or {}).get("failed", 1)
    if failed:
        return Evaluation("merge", "changes", tier, reasons + [f"{failed} failing test(s)"])
    unmet = [a["ac"] for a in implementer.get("ac_self_check", []) if not a.get("met")]
    if unmet:
        return Evaluation("merge", "changes", tier, reasons + [f"ACs not met: {', '.join(unmet)}"])
    return Evaluation("merge", "approve", tier, reasons or ["checks clean, tests green, small change"])


# ---- calibration -----------------------------------------------------------
def load_records(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def agrees(recommendation: str, decision: str) -> bool:
    if decision == "auto-approved":
        return True
    if recommendation == "approve":
        return decision == "approve"
    return decision in ("changes", "reject")


def is_false_approval(record: dict) -> bool:
    if record.get("recommendation") != "approve":
        return False
    if record.get("outcome") in ("reverted", "incident"):
        return True
    return record.get("decision") in ("changes", "reject")


@dataclass
class Calibration:
    gate: str
    samples: int
    agreement: float | None
    recent_false_approvals: int
    eligible: bool
    reasons: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def calibration(policy: dict, gate: str, records: list[dict]) -> Calibration:
    cal = policy["calibration"]
    gate_records = [r for r in records if r.get("gate") == gate]
    judged = [r for r in gate_records if r.get("decision") != "auto-approved"]
    agreement = (sum(1 for r in judged if r.get("agreed")) / len(judged)) if judged else None
    window = gate_records[-cal["regression"]["window"]:]
    false_approvals = sum(1 for r in window if is_false_approval(r))
    reasons = []
    if len(judged) < cal["min_samples"]:
        reasons.append(f"{len(judged)}/{cal['min_samples']} human-decided samples")
    if agreement is not None and agreement < cal["min_agreement"]:
        reasons.append(f"agreement {agreement:.0%} below {cal['min_agreement']:.0%}")
    if false_approvals > cal["regression"]["max_false_approvals"]:
        reasons.append(f"regression: {false_approvals} false approvals in the last {len(window)} decisions")
    eligible = not reasons and agreement is not None
    return Calibration(gate, len(judged), agreement, false_approvals, eligible, reasons)


def effective_mode(policy: dict, gate: str, records: list[dict]) -> tuple[str, list[str]]:
    """The mode the runner actually applies: `auto` closes itself on missing or regressed evidence."""
    configured = policy["gates"][gate]["mode"]
    if configured != "auto":
        return configured, []
    cal = calibration(policy, gate, records)
    if cal.eligible:
        return "auto", []
    return "shadow", ["auto mode suspended: " + "; ".join(cal.reasons)]


def auto_allows(policy: dict, evaluation: Evaluation) -> bool:
    allowed = (policy["gates"][evaluation.gate].get("auto_when") or {}).get("risk_tiers", [])
    return evaluation.recommendation == "approve" and evaluation.risk_tier in allowed


def record(gate_state: dict, *, gate: str, work_item: str, decision: str, decided_by: str, policy_version: int) -> dict:
    return {
        "gate": gate,
        "work_item": work_item,
        "mode": gate_state["mode"],
        "recommendation": gate_state["recommendation"],
        "risk_tier": gate_state["risk_tier"],
        "reasons": gate_state.get("reasons", []),
        "decision": decision,
        "decided_by": decided_by,
        "agreed": agrees(gate_state["recommendation"], decision),
        "outcome": "unknown",
        "decided_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "policy_version": policy_version,
    }


def append_record(path: Path, rec: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, sort_keys=True) + "\n")
