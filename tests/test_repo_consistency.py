"""Keeps the process definition in sync: workflow.yaml, role files, harness wrappers,
plugin manifest, envelope contracts, handoffs.md and the policy."""
import json
import re
from pathlib import Path

import yaml

from frontier import contracts, envelopes
from frontier.config import Context

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = yaml.safe_load((ROOT / "process/workflow.yaml").read_text())


def workflow_agents():
    agents = set()
    for stage in WORKFLOW["stages"].values():
        if "agent" in stage:
            agents.add(stage["agent"])
        agents.update(stage.get("parallel", []))
    return agents


ROLES = workflow_agents()


def test_every_role_has_definition_and_wrappers():
    listed = {p.stem for p in (ROOT / "agents").glob("*.md")}  # plugin default agents/ folder
    for role in ROLES:
        assert (ROOT / f"roles/{role}.md").is_file(), role
        assert (ROOT / f"agents/{role}.md").is_file(), role
        assert (ROOT / f".github/agents/{role}.agent.md").is_file(), role
        assert role in listed, f"{role} has no plugin wrapper in agents/"
    assert (ROOT / "roles/orchestrator.md").is_file()
    assert (ROOT / ".github/agents/orchestrator.agent.md").is_file()
    assert listed == ROLES, "agents/ holds wrappers that are not workflow roles"


def test_wrappers_are_thin_and_point_at_their_role():
    for role in ROLES:
        text = (ROOT / f"agents/{role}.md").read_text()
        front = re.match(r"---\n(.*?)\n---\n", text, re.S).group(1)
        assert yaml.safe_load(front)["name"] == role
        assert f"${{CLAUDE_PLUGIN_ROOT}}/roles/{role}.md" in text
        assert len(text.splitlines()) < 25, f"{role} wrapper is not thin"


def test_check_naming_convention():
    for role in ROLES:
        assert not role.startswith("verifier"), role
    assert all(a.startswith("check-") for a in WORKFLOW["stages"]["verify"]["parallel"])


def test_stage_contracts_are_pinned_and_match_the_runner():
    lock = json.loads((ROOT / "contracts/contracts.lock.json").read_text())["contracts"]
    for name, stage in WORKFLOW["stages"].items():
        if "contract" not in stage:
            continue
        cid, major = stage["contract"].split("@")
        assert cid in lock and lock[cid]["major"] == int(major), f"{name}: {stage['contract']} not pinned"
        for agent in ([stage["agent"]] if "agent" in stage else stage["parallel"]):
            assert envelopes.contract_for(agent) == cid, f"{agent} runner/workflow contract mismatch"


def test_handoffs_doc_covers_every_role():
    text = (ROOT / "process/handoffs.md").read_text()
    for role in ROLES - set(WORKFLOW["stages"]["verify"]["parallel"]):
        assert f"### {role} → orchestrator" in text or f"### {role} → repo" in text, role
    assert "### check-* → orchestrator" in text


def test_default_policy_is_valid_and_conservative():
    policy = Context.load(ROOT).policy
    assert policy["gates"]["merge"]["mode"] != "auto", "the shipped default must not auto-merge"
    assert policy["gates"]["backlog"]["mode"] == "human"


def test_hooks_reference_the_guard():
    hooks = json.loads((ROOT / "hooks/hooks.json").read_text())
    command = hooks["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    assert "runner/frontier/guard.py" in command
    assert (ROOT / "runner/frontier/guard.py").is_file()


def test_no_stale_references():
    stale = ["contracts/envelopes.schema.json", "work/<id>/state.md", ".agents/", ".commands/deliver.md"]
    for path in ROOT.rglob("*.md"):
        if ".git" in path.parts or "node_modules" in path.parts:
            continue
        text = path.read_text()
        for s in stale:
            assert s not in text, f"{path.relative_to(ROOT)} mentions {s}"


def test_relative_markdown_links_resolve():
    broken = []
    for path in ROOT.rglob("*.md"):
        if ".git" in path.parts or ".pytest_cache" in path.parts:
            continue
        for match in re.finditer(r"\]\(([^)#\s]+)(#[^)]*)?\)", path.read_text()):
            target = match.group(1)
            if not target.startswith(("http", "mailto:")) and not (path.parent / target).exists():
                broken.append(f"{path.relative_to(ROOT)} -> {target}")
    assert not broken, broken
