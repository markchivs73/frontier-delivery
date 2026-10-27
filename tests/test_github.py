"""GitHub-native mode end to end: label → plan gate → /approve → build → merge gate → PR closed → retro,
with fake claude/gh binaries and a local bare repo as origin."""
import json
import subprocess
from pathlib import Path

import pytest

from frontier.config import Context
from frontier.github import handle_event
from frontier.orchestrate import Orchestrator

FAKES = Path(__file__).parent / "fakes"


@pytest.fixture
def gh_repo(tmp_path, monkeypatch):
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    repo = tmp_path / "product"
    subprocess.run(["git", "clone", "-q", str(origin), str(repo)], check=True, capture_output=True)
    run = lambda *a: subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True)
    run("config", "user.email", "t@example.com")
    run("config", "user.name", "t")
    run("checkout", "-q", "-b", "main")
    (repo / "README.md").write_text("x\n")
    run("add", ".")
    run("commit", "-qm", "init")
    run("push", "-q", "origin", "main")
    monkeypatch.chdir(repo)
    (tmp_path / "scenario.json").write_text("{}")
    for k, v in {
        "FRONTIER_CLAUDE_BIN": str(FAKES / "fake_claude.py"), "FRONTIER_GH_BIN": str(FAKES / "fake_gh.py"),
        "FRONTIER_FAKE_SCENARIO": str(tmp_path / "scenario.json"), "FRONTIER_FAKE_LOG": str(tmp_path / "calls.jsonl"),
        "FRONTIER_FAKE_GH_LOG": str(tmp_path / "gh.jsonl"), "FRONTIER_BASE": "main", "GITHUB_REPOSITORY": "o/r",
    }.items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("FRONTIER_RECORDS", raising=False)
    return repo


def event(tmp_path, name, payload):
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps(payload))
    return str(path)


def gh_calls(tmp_path):
    return [json.loads(l) for l in (tmp_path / "gh.jsonl").read_text().splitlines()]


def labels_added(calls, number):
    added = []
    for c in calls:
        a = c["args"]
        if a[:3] == ["issue", "edit", str(number)]:
            added += [a[i + 1] for i, x in enumerate(a) if x == "--add-label"]
    return added


def test_label_to_retro(gh_repo, tmp_path):
    issue = {"number": 42, "title": "CSV export", "body": "Users need CSV export.\nAC: WHEN … SHALL …"}
    orch = lambda: Orchestrator(Context.load(gh_repo))

    # 1. Human labels the story.
    code = handle_event(orch(), "issues", event(tmp_path, "labeled", {"action": "labeled", "label": {"name": "frontier:deliver"}, "issue": issue, "repository": {"full_name": "o/r"}}))
    assert code == 0
    calls = gh_calls(tmp_path)
    create = next(c for c in calls if c["args"][:2] == ["pr", "create"])
    assert "--draft" in create["args"] and "Closes #42" in create["body"]
    plan_comment = next(c for c in calls if c["args"][:3] == ["issue", "comment", "7"])
    assert "Plan ready for approval" in plan_comment["body"] and "sealed" in plan_comment["body"]
    assert {"frontier:gate-plan", "frontier:needs-decision"} <= set(labels_added(calls, 7))
    remote = subprocess.run(["git", "ls-remote", "--heads", "origin"], cwd=gh_repo, capture_output=True, text=True).stdout
    assert "delivery/gh-o-r-42" in remote

    # 2. An untrusted commenter is ignored.
    n = len(gh_calls(tmp_path))
    handle_event(orch(), "issue_comment", event(tmp_path, "drive-by", {"action": "created", "issue": {"number": 7, "title": "[frontier] CSV export", "pull_request": {}},
        "comment": {"body": "/approve", "author_association": "NONE", "user": {"login": "rando"}}}))
    assert len(gh_calls(tmp_path)) == n

    # 3. Owner approves the plan on the PR → build runs → merge gate.
    code = handle_event(orch(), "issue_comment", event(tmp_path, "approve", {"action": "created", "issue": {"number": 7, "title": "[frontier] CSV export", "pull_request": {}},
        "comment": {"body": "/approve", "author_association": "OWNER", "user": {"login": "mark"}}}))
    assert code == 0
    calls = gh_calls(tmp_path)
    bodies = [c["body"] for c in calls if c["args"][:3] == ["issue", "comment", "7"]]
    assert any("sealed recommendation was `approve`" in b for b in bodies)
    assert any("Ready for your review" in b for b in bodies)
    assert "frontier:gate-merge" in labels_added(calls, 7)
    assert not any(c["args"][:2] == ["pr", "merge"] for c in calls), "shadow merge gate must not merge"
    # calibration record pushed to the metrics branch
    metrics = subprocess.run(["git", "show", "origin/frontier/metrics:calibration.jsonl"], cwd=gh_repo, capture_output=True, text=True)
    subprocess.run(["git", "fetch", "-q", "origin"], cwd=gh_repo)
    metrics = subprocess.run(["git", "show", "origin/frontier/metrics:calibration.jsonl"], cwd=gh_repo, capture_output=True, text=True).stdout
    assert json.loads(metrics.splitlines()[0])["gate"] == "plan"

    # 4. Human merges the PR → merge gate recorded, retro posted.
    subprocess.run(["git", "checkout", "-q", "main"], cwd=gh_repo)
    code = handle_event(orch(), "pull_request", event(tmp_path, "closed", {"action": "closed", "repository": {"full_name": "o/r"},
        "pull_request": {"number": 7, "merged": True, "merged_by": {"login": "mark"}, "head": {"ref": "delivery/gh-o-r-42"}}}))
    assert code == 0
    subprocess.run(["git", "fetch", "-q", "origin"], cwd=gh_repo)
    lines = subprocess.run(["git", "show", "origin/frontier/metrics:calibration.jsonl"], cwd=gh_repo, capture_output=True, text=True).stdout.splitlines()
    assert [json.loads(l)["gate"] for l in lines] == ["plan", "merge"]
    assert any("### Retro" in (c["body"] or "") for c in gh_calls(tmp_path))


def test_shape_option_flow(gh_repo, tmp_path):
    orch = lambda: Orchestrator(Context.load(gh_repo))
    idea = {"number": 12, "title": "Exports", "body": "Users want exports"}
    handle_event(orch(), "issues", event(tmp_path, "shape", {"action": "labeled", "label": {"name": "frontier:shape"}, "issue": idea, "repository": {"full_name": "o/r"}}))
    assert any("choose an option" in (c["body"] or "") for c in gh_calls(tmp_path))
    subprocess.run(["git", "checkout", "-q", "main"], cwd=gh_repo)
    handle_event(orch(), "issue_comment", event(tmp_path, "early", {"action": "created", "issue": dict(idea),
        "comment": {"body": "/approve", "author_association": "OWNER", "user": {"login": "mark"}}}))
    assert "choose an option first" in gh_calls(tmp_path)[-1]["body"] and "/changes" in gh_calls(tmp_path)[-1]["body"]
    # Re-adding the label doesn't restart shaping.
    handle_event(orch(), "issues", event(tmp_path, "shape2", {"action": "labeled", "label": {"name": "frontier:shape"}, "issue": idea, "repository": {"full_name": "o/r"}}))
    assert "already in progress" in gh_calls(tmp_path)[-1]["body"]
    subprocess.run(["git", "checkout", "-q", "main"], cwd=gh_repo)
    handle_event(orch(), "issue_comment", event(tmp_path, "revise", {"action": "created", "issue": dict(idea),
        "comment": {"body": "/changes Combine both and keep it CSV only", "author_association": "OWNER", "user": {"login": "mark"}}}))
    assert any("revised options (round 1)" in (c["body"] or "") for c in gh_calls(tmp_path))
    subprocess.run(["git", "checkout", "-q", "main"], cwd=gh_repo)
    handle_event(orch(), "issue_comment", event(tmp_path, "opt", {"action": "created", "issue": dict(idea),
        "comment": {"body": "/option 1\nKeep it CSV only", "author_association": "OWNER", "user": {"login": "mark"}}}))
    assert any("Backlog ready for approval" in (c["body"] or "") for c in gh_calls(tmp_path))
    shaper_prompts = [json.loads(l)["prompt"] for l in (tmp_path / "calls.jsonl").read_text().splitlines()]
    assert "Thin slice" in shaper_prompts[-1] and "Keep it CSV only" in shaper_prompts[-1]
    subprocess.run(["git", "checkout", "-q", "main"], cwd=gh_repo)
    handle_event(orch(), "issue_comment", event(tmp_path, "ok", {"action": "created", "issue": dict(idea),
        "comment": {"body": "/approve", "author_association": "OWNER", "user": {"login": "mark"}}}))
    created = [c for c in gh_calls(tmp_path) if c["args"][:2] == ["issue", "create"]]
    assert [c["args"][c["args"].index("--title") + 1] for c in created] == ["CSV export", "Filtered export"]
    assert "#101" in created[1]["body"]  # dependency rewritten to the real issue number
