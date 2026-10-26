#!/usr/bin/env python3
"""Stand-in for `claude -p --agent …` in runner tests.

Reads a scenario (JSON, path in FRONTIER_FAKE_SCENARIO): for each agent a list of
envelope bodies, one per call (the last repeats). Fills in the common envelope
fields, writes the artifacts a real role would write, and records every call.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

args = sys.argv[1:]
agent = args[args.index("--agent") + 1].split(":")[-1]
prompt = args[-1]
scenario = json.loads(Path(os.environ["FRONTIER_FAKE_SCENARIO"]).read_text())
log = Path(os.environ["FRONTIER_FAKE_LOG"])
calls = [json.loads(l) for l in log.read_text().splitlines()] if log.exists() else []
n = sum(1 for c in calls if c["agent"] == agent)
with open(log, "a") as fh:  # appends are atomic enough for the parallel check agents
    fh.write(json.dumps({"agent": agent, "args": args[:-1], "prompt": prompt, "strict": os.environ.get("FRONTIER_STRICT"), "env": sorted(k for k in os.environ if k.startswith(("GH_", "GITHUB_", "FRONTIER_")))}) + "\n")

field = lambda name: re.search(rf"^{name}: (.+)$", prompt, re.M).group(1).strip()
work_item, work_id = field("WORK_ITEM"), field("WORK_ID")
wdir = Path("work") / work_id
wdir.mkdir(parents=True, exist_ok=True)
bodies = scenario.get(agent, [{}])
body = bodies[min(n, len(bodies) - 1)]
if body == "garbage":
    print(json.dumps({"result": "I could not finish."}))
    sys.exit(0)

env = {"agent": agent, "work_item": work_item, "status": "ok", "artifacts": [], "summary": f"{agent} call {n + 1}"}
if agent.startswith("check-"):
    env.update(check=agent.removeprefix("check-"), verdict="pass", findings=[])
if agent == "implementer":
    env.update(branch=f"delivery/{work_id}", tasks_completed={"done": 2, "total": 2},
               test_run={"command": "pytest", "passed": 4, "failed": 0},
               ac_self_check=[{"ac": "AC-1", "met": True, "evidence": "tests/test_feature.py::test_ac1"}],
               fix_iteration=int(field("FIX_ITERATION")))
    Path("src").mkdir(exist_ok=True)
    Path(f"src/feature_{n}.py").write_text("print('hi')\n")
    subprocess.run(["git", "add", "src"], check=True)
    subprocess.run(["git", "commit", "-qm", f"implement {n}"], check=True)
if agent == "requirements-analyst":
    env.update(source="inline", acceptance_criteria_count=1)
    (wdir / "requirements.md").write_text("# Requirements\nAC-1: WHEN x THE SYSTEM SHALL y\n")
if agent == "planner":
    env.update(technology={"detected": "python", "source": "repo"}, task_count=2, acceptance_test_count=1,
               planned_paths=["src/**"], risks=[])
    (wdir / "design.md").write_text("# Design\n")
    (wdir / "tasks.md").write_text("- [ ] T1\n- [ ] T2\n")
if agent == "shaper":
    if "PHASE: options" in prompt:
        env.update(status="needs_input", phase="options",
                   needs_input={"question": "Which option?", "options": ["Thin slice", "Full feature"]},
                   options=[{"title": "Thin slice", "summary": "a", "recommended": True}, {"title": "Full feature", "summary": "b"}])
    else:
        env.update(phase="backlog", chosen_option="Thin slice", story_count=2)
        (wdir / "backlog.yaml").write_text(json.dumps({
            "epic": {"title": "Exports", "outcome": "Users export"},
            "stories": [
                {"id": "S-1", "title": "CSV export", "value": "v", "size": "S", "depends_on": [], "risk_flags": [],
                 "acceptance_criteria": [{"id": "AC-1", "ears": "WHEN the user clicks Export THE SYSTEM SHALL download a CSV"}]},
                {"id": "S-2", "title": "Filtered export", "value": "v", "size": "S", "depends_on": ["S-1"], "risk_flags": [],
                 "acceptance_criteria": [{"id": "AC-1", "ears": "WHILE a filter is applied THE SYSTEM SHALL export only matching rows"}]},
            ]}))
if agent == "retro":
    env.update(lessons=[{"observation": "fine", "agent": "planner", "proposed_change": "none — process worked"}])
env.update(body)
(wdir / "envelopes").mkdir(exist_ok=True)
if not body.get("_reply_only"):
    env.pop("_reply_only", None)
    (wdir / "envelopes" / f"{agent}.yaml").write_text(json.dumps(env))
    print(json.dumps({"result": "done", "total_cost_usd": 0.01}))
else:
    env.pop("_reply_only")
    import yaml
    print(json.dumps({"result": "Here you go\n```yaml\n" + yaml.safe_dump(env) + "```\n"}))
