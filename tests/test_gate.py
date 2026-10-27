import copy

from frontier import gate
from frontier.config import Context

POLICY = Context.load().policy


def planner(**kw):
    env = {"technology": {"detected": "python", "source": "repo"}, "task_count": 3, "acceptance_test_count": 2,
           "planned_paths": ["src/reports/**"], "risks": []}
    env.update(kw)
    return env


def test_small_plan_is_low_risk_and_approved():
    ev = gate.evaluate_plan(POLICY, planner())
    assert (ev.recommendation, ev.risk_tier) == ("approve", "low")


def test_protected_paths_make_a_plan_high_risk():
    for path in [".github/workflows/ci.yml", "infra/main.bicep", "src/auth/login.py", "db/migrations/001.sql"]:
        assert gate.evaluate_plan(POLICY, planner(planned_paths=[path])).risk_tier == "high", path


def test_new_stack_and_risk_flags_are_high():
    assert gate.evaluate_plan(POLICY, planner(technology={"detected": "go", "source": "user"})).risk_tier == "high"
    assert gate.evaluate_plan(POLICY, planner(), {"risk_flags": ["auth"]}).risk_tier == "high"


def test_reported_risks_and_size_raise_the_tier():
    assert gate.evaluate_plan(POLICY, planner(risks=["perf"])).risk_tier == "medium"
    assert gate.evaluate_plan(POLICY, planner(task_count=20)).risk_tier == "high"


def test_merge_recommendation():
    impl = {"test_run": {"failed": 0}, "ac_self_check": [{"ac": "AC-1", "met": True}]}
    clean = [{"findings": []}]
    ok = gate.evaluate_merge(POLICY, gate.DiffStats(["src/a.py"], 40), clean, impl, 0)
    assert (ok.recommendation, ok.risk_tier) == ("approve", "low")
    blocked = gate.evaluate_merge(POLICY, gate.DiffStats(["src/a.py"], 40), [{"findings": [{"severity": "blocking"}]}], impl, 0)
    assert blocked.recommendation == "changes"
    big = gate.evaluate_merge(POLICY, gate.DiffStats(["src/a.py"], 500), clean, impl, 0)
    assert big.risk_tier == "medium"
    loops = gate.evaluate_merge(POLICY, gate.DiffStats(["src/a.py"], 40), clean, impl, 2)
    assert loops.risk_tier == "medium"


def records(n, agree=True, false_approvals=0):
    out = []
    for i in range(n):
        out.append({"gate": "plan", "recommendation": "approve", "decision": "approve" if agree else "changes", "agreed": agree})
    for r in out[-false_approvals:] if false_approvals else []:
        r.update(decision="changes", agreed=False)
    return out


def auto_policy():
    p = copy.deepcopy(POLICY)
    p["gates"]["plan"]["mode"] = "auto"
    return p


def test_auto_needs_evidence():
    mode, notes = gate.effective_mode(auto_policy(), "plan", records(5))
    assert mode == "shadow" and "samples" in notes[0]
    assert gate.effective_mode(auto_policy(), "plan", records(25)) == ("auto", [])


def test_auto_closes_itself_on_regression():
    mode, notes = gate.effective_mode(auto_policy(), "plan", records(30, false_approvals=2))
    assert mode == "shadow" and "regression" in notes[0]


def test_shadow_and_human_are_never_promoted():
    assert gate.effective_mode(POLICY, "plan", records(100))[0] == "shadow"
    assert gate.effective_mode(POLICY, "backlog", records(100))[0] == "human"


def test_auto_only_within_tiers():
    p = auto_policy()
    assert gate.auto_allows(p, gate.Evaluation("plan", "approve", "low"))
    assert not gate.auto_allows(p, gate.Evaluation("plan", "approve", "medium"))
    assert not gate.auto_allows(p, gate.Evaluation("plan", "changes", "low"))


def test_backlog_checks():
    good = {"stories": [{"id": "S-1", "title": "t", "acceptance_criteria": [{"id": "AC-1", "ears": "WHEN x THE SYSTEM SHALL y"}]}]}
    assert gate.evaluate_backlog(POLICY, {}, good).recommendation == "approve"
    bad = {"stories": [{"id": "S-1", "title": "t", "depends_on": ["S-9"], "acceptance_criteria": [{"id": "AC-1", "ears": "it works"}]}]}
    ev = gate.evaluate_backlog(POLICY, {}, bad)
    assert ev.recommendation == "changes" and len(ev.reasons) == 2
    flagged = {"stories": [dict(good["stories"][0], risk_flags=["data-migration"])]}
    assert gate.evaluate_backlog(POLICY, {}, flagged).risk_tier == "high"
