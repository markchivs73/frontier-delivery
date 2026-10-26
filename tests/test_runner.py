"""End-to-end runner behaviour against a fake `claude` binary, in a scratch git repo."""
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from frontier.config import Context
from frontier.orchestrate import Orchestrator

FAKE = Path(__file__).parent / "fakes" / "fake_claude.py"
BLOCKING = {"verdict": "fail", "findings": [{"id": "SEC-1", "severity": "blocking", "location": "src/x.py:1",
                                             "finding": "Injection.", "evidence": "id flows to query", "required_action": "Parameterise."}]}


@pytest.fixture
def repo(tmp_path, monkeypatch):
    r = tmp_path / "product"
    r.mkdir()
    run = lambda *a: subprocess.run(["git", *a], cwd=r, check=True, capture_output=True)
    run("init", "-q", "-b", "main")
    run("config", "user.email", "t@example.com")
    run("config", "user.name", "t")
    (r / "README.md").write_text("product\n")
    run("add", ".")
    run("commit", "-qm", "init")
    monkeypatch.chdir(r)
    monkeypatch.setenv("FRONTIER_CLAUDE_BIN", str(FAKE))
    monkeypatch.setenv("FRONTIER_FAKE_LOG", str(tmp_path / "calls.json"))
    monkeypatch.setenv("FRONTIER_BASE", "main")
    monkeypatch.setenv("FRONTIER_RECORDS", str(tmp_path / "calibration.jsonl"))
    return r


def scenario(tmp_path, monkeypatch, **agents):
    path = tmp_path / "scenario.json"
    path.write_text(json.dumps(agents))
    monkeypatch.setenv("FRONTIER_FAKE_SCENARIO", str(path))


def calls(tmp_path):
    return [json.loads(l) for l in (tmp_path / "calls.json").read_text().splitlines()]


def records(tmp_path):
    p = tmp_path / "calibration.jsonl"
    return [json.loads(l) for l in p.read_text().splitlines()] if p.exists() else []


def orch(repo, policy=None):
    if policy:
        (repo / ".frontier").mkdir(exist_ok=True)
        (repo / ".frontier" / "policy.yaml").write_text(yaml.safe_dump(policy))
    return Orchestrator(Context.load(repo))


def test_full_delivery_with_one_fix_loop(repo, tmp_path, monkeypatch):
    scenario(tmp_path, monkeypatch, **{"check-security": [BLOCKING, {}]})
    o = orch(repo)
    out = o.plan("local:csv-export", source="Users need CSV export.")
    assert (out.status, out.stage, out.gate) == ("waiting", "gate-plan", "plan")
    assert "sealed" in out.message and "approve" not in out.message.split("sealed")[0].lower().split("mode")[-1]
    assert subprocess.run(["git", "branch", "--show-current"], cwd=repo, capture_output=True, text=True).stdout.strip() == "delivery/local-csv-export"

    decided = o.decide("local-csv-export", "plan", "approve", "mark")
    assert "agreed with" in decided.message
    assert records(tmp_path)[-1]["agreed"] is True

    built = o.build("local-csv-export")
    assert (built.status, built.stage, built.gate) == ("waiting", "gate-merge", "merge")
    assert built.actions == ["open_pr"]
    log = calls(tmp_path)
    assert [c["agent"] for c in log].count("implementer") == 2
    assert [c["agent"] for c in log].count("check-security") == 2
    assert all(c["strict"] == "1" for c in log)
    assert all("--agent" in c["args"] and c["args"][c["args"].index("--agent") + 1].startswith("frontier-delivery:") for c in log)
    second_impl = [c for c in log if c["agent"] == "implementer"][1]
    assert "SEC-1" in second_impl["prompt"] and "Parameterise." in second_impl["prompt"]  # verbatim routing
    report = (repo / "work/local-csv-export/verification-report.md").read_text()
    assert "Iteration 1: blocking findings: SEC-1" in report and "Iteration 2: blocking findings: none" in report

    learned = o.learn("local-csv-export", merged=True, review="LGTM")
    assert learned.status == "done"
    merge_rec = [r for r in records(tmp_path) if r["gate"] == "merge"]
    assert merge_rec and merge_rec[-1]["decision"] == "approve"


def test_fix_budget_exhausted_escalates(repo, tmp_path, monkeypatch):
    scenario(tmp_path, monkeypatch, **{"check-security": [BLOCKING]})
    o = orch(repo)
    o.plan("local:x", source="x")
    o.decide("local-x", "plan", "approve")
    out = o.build("local-x")
    assert out.status == "escalated"
    assert [c["agent"] for c in calls(tmp_path)].count("implementer") == 3
    state = yaml.safe_load((repo / "work/local-x/state.yaml").read_text())
    assert state["stage"] == "escalate" and state["resume_stage"] == "verify"


def test_contract_violation_escalates_instead_of_proceeding(repo, tmp_path, monkeypatch):
    scenario(tmp_path, monkeypatch, planner=[{"acceptance_test_count": 0}])
    out = orch(repo).plan("local:y", source="y")
    assert out.status == "escalated"
    assert "an ok plan names at least one acceptance test" in out.data["escalation"]["blocking"]


def test_envelope_recovered_from_reply_text(repo, tmp_path, monkeypatch):
    scenario(tmp_path, monkeypatch, planner=[{"_reply_only": True}])
    out = orch(repo).plan("local:z", source="z")
    assert out.status == "waiting"


def test_missing_envelope_escalates(repo, tmp_path, monkeypatch):
    scenario(tmp_path, monkeypatch, planner=["garbage"])
    assert orch(repo).plan("local:g", source="g").status == "escalated"


def test_auto_plan_gate_continues_when_calibrated(repo, tmp_path, monkeypatch):
    scenario(tmp_path, monkeypatch)
    with open(tmp_path / "calibration.jsonl", "w") as fh:
        for i in range(20):
            fh.write(json.dumps({"gate": "plan", "recommendation": "approve", "decision": "approve", "agreed": True}) + "\n")
    o = orch(repo, {"gates": {"plan": {"mode": "auto", "auto_when": {"risk_tiers": ["low"]}}}})
    out = o.plan("local:auto", source="a")
    assert (out.status, out.actions) == ("continue", ["build"])
    assert records(tmp_path)[-1]["decision"] == "auto-approved"


def test_auto_plan_gate_falls_back_to_shadow_without_evidence(repo, tmp_path, monkeypatch):
    scenario(tmp_path, monkeypatch)
    o = orch(repo, {"gates": {"plan": {"mode": "auto", "auto_when": {"risk_tiers": ["low"]}}}})
    out = o.plan("local:noevidence", source="a")
    assert out.status == "waiting" and "auto mode suspended" in out.message


def test_build_refuses_unapproved_plan(repo, tmp_path, monkeypatch):
    scenario(tmp_path, monkeypatch)
    o = orch(repo)
    o.plan("local:p", source="p")
    with pytest.raises(ValueError):
        o.build("local-p")


def test_replan_routes_comments_verbatim_and_is_bounded(repo, tmp_path, monkeypatch):
    scenario(tmp_path, monkeypatch)
    o = orch(repo)
    o.plan("local:r", source="r")
    for i in range(2):
        o.decide("local-r", "plan", "changes", comments=f"Please split T{i}")
        out = o.plan("local:r", comments=f"Please split T{i}")
        assert out.status == "waiting"
    assert "Please split T1" in [c for c in calls(tmp_path) if c["agent"] == "planner"][-1]["prompt"]
    o.decide("local-r", "plan", "changes")
    assert o.plan("local:r", comments="again").status == "escalated"


def test_shape_options_then_backlog_then_stories(repo, tmp_path, monkeypatch):
    scenario(tmp_path, monkeypatch)
    o = orch(repo)
    out = o.shape("local:exports", idea="Users want exports.")
    assert (out.status, out.data["phase"]) == ("waiting", "options") and "Thin slice" in out.message
    out = o.shape("local:exports", choice="Thin slice")
    assert (out.status, out.data["phase"], out.gate) == ("waiting", "backlog", "backlog")
    assert "**Mode: human.**" in out.message
    o.decide("local-exports", "backlog", "approve")
    stories = o.stories("local-exports")
    assert [s["title"] for s in stories] == ["CSV export", "Filtered export"]
    assert "WHEN the user clicks Export THE SYSTEM SHALL" in stories[0]["body"] and stories[1]["depends_on"] == ["S-1"]


def test_cli_status_and_contracts(repo, tmp_path, monkeypatch):
    scenario(tmp_path, monkeypatch)
    orch(repo).plan("local:s", source="s")
    out = subprocess.run([sys.executable, "-m", "frontier", "status"], cwd=repo, capture_output=True, text=True,
                         env={**__import__("os").environ, "PYTHONPATH": str(Path(__file__).parents[1] / "runner")})
    rows = json.loads(out.stdout)
    assert rows[0]["pending_gates"] == ["plan"] and rows[0]["needs_decision"]
