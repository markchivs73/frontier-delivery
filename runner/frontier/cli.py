"""`python -m frontier …`: the headless runner CLI.

Run from the product repo root (or pass --repo). Every command prints the
Outcome as JSON on stdout (for scripts and CI) and its message as markdown on
stderr (for you). Exit codes: 0 = advanced or waiting on a gate, 3 = escalated,
2 = usage/state error.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import Context, slugify
from .contracts import ContractError
from .envelopes import EnvelopeError
from .gate import calibration
from .orchestrate import Orchestrator, Outcome


def _read(arg: str | None) -> str | None:
    if arg is None:
        return None
    if arg == "-":
        return sys.stdin.read()
    path = Path(arg)
    return path.read_text(encoding="utf-8") if path.is_file() else arg


def _emit(outcome: Outcome | list | dict) -> int:
    if isinstance(outcome, Outcome):
        if outcome.message:
            print(outcome.message, file=sys.stderr)
        print(json.dumps(outcome.to_dict(), indent=2, default=str))
        return 3 if outcome.status == "escalated" else 0
    print(json.dumps(outcome, indent=2, default=str))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="frontier", description="frontier-delivery headless runner")
    p.add_argument("--repo", help="product repo root (default: cwd)")
    p.add_argument("--policy", help="policy file (default: .frontier/policy.yaml, else the process default)")
    p.add_argument("--no-commit", action="store_true", help="do not switch branches or commit work/ artifacts")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("shape", help="shape an idea into options, then a backlog")
    s.add_argument("work_item", help="idea reference, e.g. gh:owner/repo#12 or local:my-idea")
    s.add_argument("--idea", help="idea text, a file path, or - for stdin")
    s.add_argument("--choice", help="the chosen option (title or number), to write the backlog")
    s.add_argument("--comments", help="re-shape comments (text, file, or -)")

    s = sub.add_parser("stories", help="print the approved backlog as issue-ready stories (JSON)")
    s.add_argument("shape_id")

    s = sub.add_parser("plan", help="intake + plan, then the plan gate")
    s.add_argument("work_item", help="gh:owner/repo#n | ado:org/project/id | local:slug")
    s.add_argument("--source", help="work item content (text, file, or -); omit to let the analyst fetch it")
    s.add_argument("--comments", help="plan-gate comments for a re-plan")

    s = sub.add_parser("decide", help="record a human gate decision")
    s.add_argument("work_id")
    s.add_argument("gate", choices=["backlog", "plan", "merge"])
    s.add_argument("decision", choices=["approve", "changes", "reject"])
    s.add_argument("--by", default="human")
    s.add_argument("--comments")

    s = sub.add_parser("build", help="implement + verify loop, then the merge gate")
    s.add_argument("work_id")
    s.add_argument("--comments", help="human review comments to address (merge-gate changes)")

    s = sub.add_parser("deliver", help="plan → (gate) → build in one go, stopping at any human gate")
    s.add_argument("work_item")
    s.add_argument("--source")

    s = sub.add_parser("answer", help="answer an escalation and resume")
    s.add_argument("work_id")
    s.add_argument("text")

    s = sub.add_parser("learn", help="after the PR is merged/closed: record the merge gate, run retro")
    s.add_argument("work_id")
    s.add_argument("--merged", action="store_true")
    s.add_argument("--review", help="human review comments (text, file, or -)")

    sub.add_parser("status", help="list deliveries and anything waiting on you")

    s = sub.add_parser("calibration", help="gate calibration stats from the records")
    s.add_argument("--gate", choices=["backlog", "plan", "merge"])

    sub.add_parser("validate", help="validate the policy and print the effective configuration")

    s = sub.add_parser("contracts", help="pin, verify or test the envelope contracts")
    s.add_argument("action", choices=["lock", "verify", "check"])
    s.add_argument("--contract", help="contract id (check)")
    s.add_argument("--file", help="YAML/JSON payload to check against --contract")

    s = sub.add_parser("github", help="handle a GitHub Actions event (used by the reusable workflow)")
    s.add_argument("--event-name", required=True)
    s.add_argument("--event-path", required=True)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        ctx = Context.load(args.repo, args.policy)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    orch = Orchestrator(ctx, commit=not args.no_commit)
    try:
        if args.cmd == "shape":
            return _emit(orch.shape(args.work_item, _read(args.idea), args.choice, _read(args.comments)))
        if args.cmd == "stories":
            return _emit(orch.stories(args.shape_id))
        if args.cmd == "plan":
            return _emit(orch.plan(args.work_item, _read(args.source), _read(args.comments)))
        if args.cmd == "decide":
            outcome = orch.decide(args.work_id, args.gate, args.decision, args.by, _read(args.comments))
            return _emit(outcome)
        if args.cmd == "build":
            return _emit(orch.build(args.work_id, _read(args.comments)))
        if args.cmd == "deliver":
            outcome = orch.plan(args.work_item, _read(args.source))
            if outcome.status == "continue" and "build" in outcome.actions:
                outcome = orch.build(slugify(args.work_item))
            return _emit(outcome)
        if args.cmd == "answer":
            return _emit(orch.answer(args.work_id, _read(args.text)))
        if args.cmd == "learn":
            return _emit(orch.learn(args.work_id, args.merged, _read(args.review)))
        if args.cmd == "status":
            return _emit(orch.status())
        if args.cmd == "calibration":
            records = ctx.ledger.records()
            gates = [args.gate] if args.gate else ["backlog", "plan", "merge"]
            return _emit({g: dict(calibration(ctx.policy, g, records).to_dict(), configured_mode=ctx.policy["gates"][g]["mode"]) for g in gates})
        if args.cmd == "validate":
            return _emit({"policy_source": str(ctx.policy_source), "policy": ctx.policy})
        if args.cmd == "contracts":
            from . import contracts
            if args.action == "lock":
                return _emit(contracts.write_lock())
            if args.action == "verify":
                problems = contracts.verify_lock()
                if not problems:
                    contracts.registry()  # compiles (type-checks) every CEL rule
                _emit({"ok": not problems, "problems": problems})
                return 0 if not problems else 1
            import yaml
            payload = yaml.safe_load(Path(args.file).read_text(encoding="utf-8"))
            violations = [str(v) for v in contracts.get(args.contract).validate(payload)]
            _emit({"contract": args.contract, "ok": not violations, "violations": violations})
            return 0 if not violations else 1
        if args.cmd == "github":
            from .github import handle_event
            return handle_event(orch, args.event_name, args.event_path)
    except (ValueError, FileNotFoundError, EnvelopeError, ContractError) as exc:
        print(f"frontier: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    sys.exit(main())
