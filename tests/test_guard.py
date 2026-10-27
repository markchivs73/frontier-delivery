import json
import subprocess
import sys
from pathlib import Path

import pytest

from frontier import guard

GUARD = Path(guard.__file__)


def decide(tool, tool_input, agent_type=None, cwd="/tmp", strict=False, monkeypatch=None):
    payload = {"tool_name": tool, "tool_input": tool_input, "cwd": cwd}
    if agent_type:
        payload["agent_type"] = agent_type
    return guard.evaluate(payload)


@pytest.fixture(autouse=True)
def not_strict(monkeypatch):
    monkeypatch.delenv("FRONTIER_STRICT", raising=False)


@pytest.mark.parametrize("command", [
    "gh pr merge 12 --squash",
    "gh pr ready 12",
    "cd repo && gh pr merge --auto 3",
    "gh api -X PUT repos/o/r/pulls/12/merge",
    "git push --force origin delivery/x",
    "git push -f",
    "git push origin +delivery/x",
    "git push origin main",
    "git push origin HEAD:main",
    "git -C /work push origin master",
    "env git push origin main",
    "GIT_TRACE=0 git push origin main",
    "command git push origin main",
    "git push --all",
    "git push origin 'refs/heads/*:refs/heads/*'",
    "git push -fu origin delivery/x",
    "git push origin HEAD:frontier/metrics",
])
def test_agents_never_merge_or_force(command):
    assert decide("Bash", {"command": command}, "frontier-delivery:implementer")


@pytest.mark.parametrize("command", [
    "git push origin delivery/gh-o-r-1",
    "git status && git diff main...HEAD",
    "pytest -q",
    "gh pr view 12 --json state",
])
def test_ordinary_commands_allowed_for_implementer(command):
    assert decide("Bash", {"command": command}, "frontier-delivery:implementer") is None


def test_main_session_is_the_humans_unless_strict(monkeypatch):
    assert decide("Bash", {"command": "gh pr merge 1"}) is None
    monkeypatch.setenv("FRONTIER_STRICT", "1")
    assert decide("Bash", {"command": "gh pr merge 1"})


@pytest.mark.parametrize("role,path,allowed", [
    ("check-security", "work/x/envelopes/check-security.yaml", True),
    ("check-security", "src/app.py", False),
    ("check-architecture", "work/x/verification-report.md", False),
    ("planner", "work/x/design.md", True),
    ("planner", "src/app.py", False),
    ("shaper", "work/x/backlog.yaml", True),
    ("requirements-analyst", "README.md", False),
    ("implementer", "src/app.py", True),
    ("implementer", "work/x/tasks.md", True),
    ("implementer", "work/x/design.md", False),
    ("implementer", ".frontier/policy.yaml", False),
    ("retro", "roles/planner.md", True),
    ("implementer", ".claude/settings.json", False),
    ("implementer", "hooks/useCart.ts", True),        # a product repo's own hooks/ folder
    ("implementer", "contracts/Token.sol", True),     # a product repo's own contracts/ folder
])
def test_write_scopes(role, path, allowed):
    result = decide("Write", {"file_path": path}, f"frontier-delivery:{role}")
    assert (result is None) == allowed, result


@pytest.mark.parametrize("role,path", [
    ("retro", "policy/policy.yaml"),
    ("retro", "contracts/contracts.lock.json"),
    ("retro", "hooks/hooks.json"),
    ("implementer", "runner/frontier/guard.py"),
])
def test_process_repo_governance(role, path):
    root = str(Path(guard.__file__).resolve().parents[2])
    assert decide("Write", {"file_path": path}, f"frontier-delivery:{role}", cwd=root)
    assert decide("Write", {"file_path": "roles/planner.md"}, "frontier-delivery:retro", cwd=root) is None


def test_absolute_paths_are_made_relative():
    assert decide("Edit", {"file_path": "/repo/src/app.py"}, "frontier-delivery:planner", cwd="/repo")
    assert decide("Edit", {"file_path": "/repo/work/a/design.md"}, "frontier-delivery:planner", cwd="/repo") is None


def test_check_agents_cannot_commit():
    assert decide("Bash", {"command": "git commit -am fix"}, "frontier-delivery:check-security")
    assert decide("Bash", {"command": "pytest && git diff"}, "frontier-delivery:check-security") is None


def test_commit_on_default_branch_blocked(tmp_path):
    subprocess.run(["git", "init", "-q", "-b", "main", str(tmp_path)], check=True)
    assert decide("Bash", {"command": "git commit -m x"}, "frontier-delivery:implementer", cwd=str(tmp_path))


def test_hook_protocol_end_to_end():
    payload = {"tool_name": "Bash", "tool_input": {"command": "gh pr merge 3"}, "agent_type": "frontier-delivery:implementer", "cwd": "/tmp"}
    out = subprocess.run([sys.executable, str(GUARD)], input=json.dumps(payload), capture_output=True, text=True)
    assert out.returncode == 0
    decision = json.loads(out.stdout)["hookSpecificOutput"]
    assert decision["permissionDecision"] == "deny"
    allowed = subprocess.run([sys.executable, str(GUARD)], input=json.dumps(dict(payload, tool_input={"command": "ls"})), capture_output=True, text=True)
    assert allowed.stdout == ""
    garbage = subprocess.run([sys.executable, str(GUARD)], input="not json", capture_output=True, text=True)
    assert garbage.returncode == 0 and garbage.stdout == ""


def test_bare_and_head_pushes_resolve_the_current_branch(tmp_path):
    subprocess.run(["git", "init", "-q", "-b", "main", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-q", "--allow-empty", "-m", "x"], check=True)
    for command in ("git push", "git push origin HEAD", "git push origin @"):
        assert decide("Bash", {"command": command}, "frontier-delivery:implementer", cwd=str(tmp_path)), command
    subprocess.run(["git", "-C", str(tmp_path), "checkout", "-q", "--detach"], check=True)
    assert decide("Bash", {"command": "git commit -m y"}, "frontier-delivery:implementer", cwd=str(tmp_path))
    subprocess.run(["git", "-C", str(tmp_path), "checkout", "-q", "-b", "delivery/x"], check=True)
    assert decide("Bash", {"command": "git push"}, "frontier-delivery:implementer", cwd=str(tmp_path)) is None


def test_paths_are_judged_from_the_repo_root(tmp_path):
    subprocess.run(["git", "init", "-q", "-b", "main", str(tmp_path)], check=True)
    (tmp_path / "src").mkdir()
    assert decide("Write", {"file_path": "../.frontier/policy.yaml"}, "frontier-delivery:implementer", cwd=str(tmp_path / "src"))
    assert decide("Write", {"file_path": "../work/a/design.md"}, "frontier-delivery:planner", cwd=str(tmp_path / "src")) is None
