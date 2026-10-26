#!/usr/bin/env python3
"""Stand-in for the gh CLI: records calls to FRONTIER_FAKE_GH_LOG, keeps one fake PR."""
import json
import os
import sys
from pathlib import Path

args = sys.argv[1:]
log = Path(os.environ["FRONTIER_FAKE_GH_LOG"])
state_file = log.with_suffix(".state.json")
state = json.loads(state_file.read_text()) if state_file.exists() else {"prs": [], "issues": 100}
stdin = sys.stdin.read() if "--body-file" in args else None
with open(log, "a") as fh:
    fh.write(json.dumps({"args": args, "body": stdin}) + "\n")

out = ""
if args[:2] == ["pr", "list"]:
    head = args[args.index("--head") + 1]
    out = json.dumps([{"number": p["number"], "url": f"https://github.com/o/r/pull/{p['number']}", "isDraft": True} for p in state["prs"] if p["head"] == head])
elif args[:2] == ["pr", "create"]:
    number = 7 + len(state["prs"])
    state["prs"].append({"number": number, "head": args[args.index("--head") + 1], "title": args[args.index("--title") + 1], "body": stdin})
    out = f"https://github.com/o/r/pull/{number}"
elif args[:2] == ["pr", "view"]:
    pr = next(p for p in state["prs"] if p["number"] == int(args[2]))
    out = json.dumps({"headRefName": pr["head"], "title": pr["title"], "body": pr["body"]})
elif args[:2] == ["issue", "create"]:
    state["issues"] += 1
    out = f"https://github.com/o/r/issues/{state['issues']}"
elif args[0] == "api":
    out = "[]"
state_file.write_text(json.dumps(state))
print(out)
