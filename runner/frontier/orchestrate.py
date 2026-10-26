"""The deterministic orchestrator: roles/orchestrator.md as code.

Every public method runs the flow forward until it reaches a gate that needs a
human, an escalation, or the end, then returns an Outcome describing where it
stopped and what to tell the human. Callers (the CLI and the GitHub glue) turn
Outcomes into terminal output or issue/PR comments.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from . import envelopes, gate, messages, prompts, report
from .claude import ClaudeRunner, clear_envelope
from .config import Context, slugify
from .envelopes import CHECK_AGENTS, EnvelopeError
from .git import commit_paths, default_branch, diff_stats, ensure_branch
from .state import State, now


@dataclass
class Outcome:
    work_id: str
    stage: str                      # where the flow stopped
    status: str                     # waiting | escalated | continue | done
    message: str = ""               # markdown for the human
    gate: str | None = None
    actions: list[str] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


class Orchestrator:
    def __init__(self, ctx: Context, runner: ClaudeRunner | None = None, commit: bool = True):
        self.ctx = ctx
        self.runner = runner or ClaudeRunner(ctx)
        self.commit = commit

    # ---- helpers -----------------------------------------------------------
    def _run_agent(self, agent: str, prompt: str, work_dir: Path) -> dict:
        clear_envelope(work_dir, agent)
        run = self.runner.run(agent, prompt)
        try:
            return envelopes.read(work_dir, agent, run.reply)
        except EnvelopeError as exc:
            raise EnvelopeError(f"{exc}\n(exit {run.returncode}) {run.stderr.strip()[-800:]}") from exc

    def _commit(self, work_id: str, message: str) -> None:
        if self.commit:
            commit_paths(self.ctx.repo, [f"work/{work_id}"], message)

    def _escalate(self, state: State, stage: str, attempted: str, blocking: str, question: str, options=None) -> Outcome:
        esc = state.escalate(stage, attempted, blocking, question, options)
        state.save()
        self._commit(state.data["work_id"], f"frontier({stage}): escalate {state.data['work_id']}")
        return Outcome(state.data["work_id"], "escalate", "escalated", messages.escalation(esc), data={"escalation": esc})

    def _escalate_envelope(self, state: State, stage: str, agent: str, env: dict) -> Outcome:
        ni = env.get("needs_input") or {}
        if env["status"] == "failed":
            return self._escalate(state, stage, f"ran {agent}", f"{agent} failed: {env.get('summary', '')}", "How should this proceed?")
        return self._escalate(state, stage, f"ran {agent}", env.get("summary", f"{agent} needs input"),
                              ni.get("question", "What is missing?"), ni.get("options"))

    def _apply_gate(self, state: State, evaluation: gate.Evaluation) -> tuple[dict, bool]:
        records = gate.load_records(self.ctx.records_path())
        mode, notes = gate.effective_mode(self.ctx.policy, evaluation.gate, records)
        gs = {
            "mode": mode,
            "recommendation": evaluation.recommendation,
            "risk_tier": evaluation.risk_tier,
            "reasons": evaluation.reasons,
            "pending": True,
            "requested_at": now(),
        }
        if notes:
            gs["notes"] = notes
        if mode == "auto" and gate.auto_allows(self.ctx.policy, evaluation):
            gs.update(pending=False, decision="auto-approved", decided_by="policy", decided_at=now())
            rec = gate.record(gs, gate=evaluation.gate, work_item=state.work_item, decision="auto-approved",
                              decided_by="policy", policy_version=self.ctx.policy["version"])
            gate.append_record(self.ctx.records_path(), rec)
            state.data["gates"][evaluation.gate] = gs
            return gs, True
        state.data["gates"][evaluation.gate] = gs
        return gs, False

    # ---- shaping -----------------------------------------------------------
    def shape(self, work_item: str, idea: str | None = None, choice: str | None = None, comments: str | None = None) -> Outcome:
        wid = slugify(work_item)
        wdir = self.ctx.work_dir(wid)
        state = State.load(wdir, work_item=work_item, work_id=wid, kind="shape")
        if self.commit:
            ensure_branch(self.ctx.repo, f"shape/{wid}")
        if comments and state.bump("reshape") > self.ctx.budget("reshape"):
            return self._escalate(state, "shape", "re-shaped the backlog", "re-shape budget exhausted",
                                  "Approve the current backlog, reject it, or give one consolidated set of changes?")
        if idea:
            wdir.mkdir(parents=True, exist_ok=True)
            (wdir / "idea.md").write_text(idea, encoding="utf-8")
        idea_text = idea or messages.read_text(wdir / "idea.md")
        state.move("shape")
        try:
            env = self._run_agent("shaper", prompts.shaper(self.ctx, work_item=work_item, work_id=wid,
                                                          idea=idea_text, choice=choice, comments=comments), wdir)
        except EnvelopeError as exc:
            return self._escalate(state, "shape", "ran shaper", str(exc), "Retry shaping, or shape this idea by hand?")
        if env["phase"] == "options" and env["status"] == "needs_input":
            gs = {"phase": "options", "mode": "human", "pending": True, "requested_at": now(),
                  "options": [o["title"] for o in env.get("options", [])]}
            state.data["gates"]["backlog"] = gs
            state.move("gate-backlog", "options ready")
            state.save()
            self._commit(wid, f"frontier(shape): options for {wid}")
            return Outcome(wid, "gate-backlog", "waiting", messages.backlog_options(wid, env, gs), gate="backlog",
                           data={"phase": "options"})
        if env["status"] != "ok":
            return self._escalate_envelope(state, "shape", "shaper", env)
        backlog = yaml.safe_load(messages.read_text(wdir / "backlog.yaml") or "null")
        evaluation = gate.evaluate_backlog(self.ctx.policy, env, backlog)
        gs, auto = self._apply_gate(state, evaluation)
        gs["phase"] = "backlog"
        state.move("publish-backlog" if auto else "gate-backlog", "backlog ready")
        state.save()
        self._commit(wid, f"frontier(shape): backlog for {wid}")
        if auto:
            return Outcome(wid, "publish-backlog", "continue", messages.backlog(wid, env, backlog, gs), gate="backlog",
                           actions=["publish_backlog"], data={"phase": "backlog"})
        return Outcome(wid, "gate-backlog", "waiting", messages.backlog(wid, env, backlog or {}, gs), gate="backlog",
                       data={"phase": "backlog"})

    def stories(self, shape_id: str) -> list[dict]:
        """The approved backlog as issue-ready stories (title, body, depends_on, risk_flags)."""
        wdir = self.ctx.work_dir(shape_id)
        backlog = yaml.safe_load(messages.read_text(wdir / "backlog.yaml") or "null") or {}
        problems = gate.backlog_problems(backlog)
        if problems:
            raise ValueError("backlog.yaml is not publishable: " + "; ".join(problems))
        epic = backlog.get("epic", {})
        out = []
        for story in backlog["stories"]:
            acs = "\n".join(
                f"### {ac['id']}\n- **Criterion (EARS)**: {ac['ears']}\n- **Original wording**: \"{ac['ears']}\"\n"
                for ac in story["acceptance_criteria"]
            )
            body = (
                f"Part of epic **{epic.get('title', shape_id)}** (shaped in `work/{shape_id}/`).\n\n"
                f"## Context\n{story.get('value', '')}\n\n"
                f"- **Depends on**: {', '.join(story.get('depends_on') or []) or 'none'}\n"
                f"- **Size**: {story.get('size', '?')}\n"
                f"- **Risk flags**: {', '.join(story.get('risk_flags') or []) or 'none'}\n\n"
                f"## Acceptance criteria\n\n{acs}"
            )
            out.append({"id": story["id"], "title": story["title"], "body": body,
                        "depends_on": story.get("depends_on") or [], "risk_flags": story.get("risk_flags") or []})
        return out

    # ---- delivery: intake + plan ------------------------------------------
    def plan(self, work_item: str, source: str | None = None, comments: str | None = None, answer: str | None = None) -> Outcome:
        wid = slugify(work_item)
        wdir = self.ctx.work_dir(wid)
        state = State.load(wdir, work_item=work_item, work_id=wid)
        if self.commit:
            ensure_branch(self.ctx.repo, f"delivery/{wid}")
        resume = state.data.get("resume_stage")
        state.clear_escalation()
        if comments is not None and state.bump("replan") > self.ctx.budget("replan"):
            return self._escalate(state, "gate-plan", "re-planned with your comments", "re-plan budget exhausted",
                                  "Approve the current plan, reject it, or reshape the story?")
        if source:
            wdir.mkdir(parents=True, exist_ok=True)
            (wdir / "source.md").write_text(source, encoding="utf-8")
        need_intake = not (wdir / "requirements.md").is_file() or (answer and resume == "intake")
        analyst_env = None
        if need_intake:
            state.move("intake")
            try:
                analyst_env = self._run_agent("requirements-analyst", prompts.analyst(
                    self.ctx, work_item=work_item, work_id=wid,
                    source=source or messages.read_text(wdir / "source.md") or None,
                    answer=answer if resume == "intake" else None), wdir)
            except EnvelopeError as exc:
                return self._escalate(state, "intake", "ran requirements-analyst", str(exc), "Retry intake?")
            if analyst_env["status"] != "ok":
                return self._escalate_envelope(state, "intake", "requirements-analyst", analyst_env)
        else:
            try:
                analyst_env = envelopes.read(wdir, "requirements-analyst")
            except EnvelopeError:
                analyst_env = None
        state.move("plan")
        try:
            planner_env = self._run_agent("planner", prompts.planner(
                self.ctx, work_item=work_item, work_id=wid, comments=comments,
                answer=answer if resume == "plan" else None), wdir)
        except EnvelopeError as exc:
            return self._escalate(state, "plan", "ran planner", str(exc), "Retry planning?")
        if planner_env["status"] != "ok":
            return self._escalate_envelope(state, "plan", "planner", planner_env)
        evaluation = gate.evaluate_plan(self.ctx.policy, planner_env, analyst_env)
        gs, auto = self._apply_gate(state, evaluation)
        state.move("implement" if auto else "gate-plan", f"plan gate {gs['mode']}")
        state.save()
        self._commit(wid, f"frontier(plan): plan for {wid}")
        message = messages.plan(wid, planner_env, gs)
        if auto:
            return Outcome(wid, "implement", "continue", message, gate="plan", actions=["build"])
        return Outcome(wid, "gate-plan", "waiting", message, gate="plan")

    # ---- gate decisions ---------------------------------------------------
    def decide(self, work_id: str, gate_name: str, decision: str, decided_by: str = "human", comments: str | None = None) -> Outcome:
        if decision not in ("approve", "changes", "reject"):
            raise ValueError(f"unknown decision {decision!r}")
        wdir = self.ctx.work_dir(work_id)
        state = State.read(wdir)
        gs = state.data.get("gates", {}).get(gate_name)
        if not gs or not gs.get("pending"):
            raise ValueError(f"no pending {gate_name} gate for {work_id}")
        gs.update(pending=False, decision=decision, decided_by=decided_by, decided_at=now())
        if comments:
            gs.setdefault("comments", []).append(comments)
        message = f"{messages.MARKER}\nRecorded `{decision}` at the {gate_name} gate."
        if gs.get("mode") in ("shadow", "auto") and "recommendation" in gs:
            rec = gate.record(gs, gate=gate_name, work_item=state.work_item, decision=decision,
                              decided_by=decided_by, policy_version=self.ctx.policy["version"])
            gate.append_record(self.ctx.records_path(), rec)
            gs["agreed"] = rec["agreed"]
            message = messages.reveal(gate_name, rec)
        next_stage = {
            ("backlog", "approve"): "publish-backlog", ("backlog", "changes"): "shape", ("backlog", "reject"): "done",
            ("plan", "approve"): "implement", ("plan", "changes"): "plan", ("plan", "reject"): "done",
            ("merge", "approve"): "merged", ("merge", "changes"): "implement", ("merge", "reject"): "done",
        }[(gate_name, decision)]
        state.move(next_stage, f"{gate_name} gate: {decision} by {decided_by}")
        state.save()
        self._commit(work_id, f"frontier(gate-{gate_name}): {decision} {work_id}")
        return Outcome(work_id, next_stage, "continue" if next_stage not in ("done", "merged") else "done", message, gate=gate_name)

    # ---- delivery: implement + verify + deliver ----------------------------
    def build(self, work_id: str, human_comments: str | None = None) -> Outcome:
        wdir = self.ctx.work_dir(work_id)
        state = State.read(wdir)
        state.clear_escalation()
        plan_gate = state.data["gates"].get("plan", {})
        if plan_gate.get("decision") not in ("approve", "auto-approved"):
            raise ValueError(f"{work_id}: the plan has not been approved (plan gate: {plan_gate.get('decision', 'pending')})")
        branch = f"delivery/{work_id}"
        if self.commit:
            ensure_branch(self.ctx.repo, branch)
        base = default_branch(self.ctx.repo)
        budget = self.ctx.budget("verify_fix")
        work_item = state.work_item
        history: list[dict] = []
        findings_text: str | None = None
        checks: dict[str, dict] = {}
        impl_env: dict = {}
        for attempt in range(1, budget + 1):
            state.move("implement", f"attempt {attempt}")
            state.bump("implement_runs")
            try:
                impl_env = self._run_agent("implementer", prompts.implementer(
                    self.ctx, work_item=work_item, work_id=work_id, branch=branch, fix_iteration=attempt - 1,
                    findings=findings_text, human_comments=human_comments if attempt == 1 else None), wdir)
            except EnvelopeError as exc:
                return self._escalate(state, "implement", "ran implementer", str(exc), "Retry implementation?")
            if impl_env["status"] != "ok":
                return self._escalate_envelope(state, "implement", "implementer", impl_env)
            state.move("verify", f"attempt {attempt}")
            prompts_by_agent = {a: prompts.check(self.ctx, agent=a, work_item=work_item, work_id=work_id, base=base, branch=branch)
                                for a in CHECK_AGENTS}
            for a in CHECK_AGENTS:
                clear_envelope(wdir, a)
            runs = self.runner.run_parallel(prompts_by_agent)
            checks = {}
            for agent, run in runs.items():
                try:
                    checks[agent] = envelopes.read(wdir, agent, run.reply)
                except EnvelopeError as exc:
                    return self._escalate(state, "verify", f"ran {agent}", str(exc), "Retry verification?")
            blocking = report.blocking_findings(checks)
            history.append({"iteration": attempt, "blocking": [f["id"] for f in blocking]})
            state.data["verify_history"] = state.data.get("verify_history", []) + [history[-1]]
            if not blocking:
                break
            if attempt == budget:
                (wdir / "verification-report.md").write_text(
                    report.render(work_item, checks, impl_env, attempt, "escalated: fix budget exhausted", history), encoding="utf-8")
                return self._escalate(state, "verify", f"{attempt} implement/verify iterations",
                                      f"{len(blocking)} blocking finding(s) remain after the fix budget: " + ", ".join(f["id"] for f in blocking),
                                      "Resolve the findings with guidance (/answer), accept them as-is (/answer accept), or stop (/reject)?")
            findings_text = yaml.safe_dump(blocking, sort_keys=False, allow_unicode=True)
        fix_iterations = len(history) - 1
        (wdir / "verification-report.md").write_text(
            report.render(work_item, checks, impl_env, fix_iterations, "delivered", history), encoding="utf-8")
        diff = diff_stats(self.ctx.repo, base)
        evaluation = gate.evaluate_merge(self.ctx.policy, diff, list(checks.values()), impl_env, fix_iterations)
        gs, auto = self._apply_gate(state, evaluation)
        state.move("gate-merge", f"merge gate {gs['mode']}")
        state.save()
        self._commit(work_id, f"frontier(verify): report for {work_id}")
        summary = report.summary_table(checks, fix_iterations, "delivered")
        actions = ["open_pr"] + (["enable_auto_merge"] if auto else [])
        return Outcome(work_id, "gate-merge", "continue" if auto else "waiting", messages.merge(work_id, gs, summary),
                       gate="merge", actions=actions,
                       data={"pr_body": messages.pr_body(work_item, work_id, summary, impl_env, None),
                             "diff_lines": diff.lines, "diff_files": len(diff.files)})

    # ---- escalation answers -------------------------------------------------
    def answer(self, work_id: str, text: str) -> Outcome:
        wdir = self.ctx.work_dir(work_id)
        state = State.read(wdir)
        resume = state.data.get("resume_stage")
        if state.stage != "escalate" or not resume:
            raise ValueError(f"{work_id} is not waiting on an escalation")
        if state.data.get("kind") == "shape":
            return self.shape(state.work_item, comments=text)
        if resume in ("intake", "plan", "gate-plan"):
            return self.plan(state.work_item, answer=text)
        if resume in ("implement", "verify", "gate-merge"):
            return self.build(work_id, human_comments=text)
        raise ValueError(f"cannot resume {work_id} from stage {resume!r}")

    # ---- learn --------------------------------------------------------------
    def learn(self, work_id: str, merged: bool, review: str | None = None, decided_by: str = "human") -> Outcome:
        wdir = self.ctx.work_dir(work_id)
        state = State.read(wdir)
        merge_gate = state.data.get("gates", {}).get("merge", {})
        reveal = ""
        if merge_gate.get("pending"):
            reveal = self.decide(work_id, "merge", "approve" if merged else "reject", decided_by).message
            state = State.read(wdir)
        state.move("learn")
        lessons: list[dict] = []
        try:
            env = self._run_agent("retro", prompts.retro(self.ctx, work_item=state.work_item, work_id=work_id,
                                                         merged=merged, review=review), wdir)
            lessons = env.get("lessons", [])
        except EnvelopeError as exc:
            lessons = [{"observation": f"retro did not produce an envelope: {exc}", "agent": "retro", "proposed_change": "none"}]
        state.data["lessons"] = lessons
        state.move("done", "merged" if merged else "closed")
        state.save()
        body = "\n".join(f"- **{l['agent']}**: {l['observation']}  \n  Proposed: {l['proposed_change']}" for l in lessons) or "- No lessons."
        message = f"{messages.MARKER}\n### Retro\n\n{body}"
        if reveal:
            message = reveal + "\n\n" + message
        return Outcome(work_id, "done", "done", message, data={"lessons": lessons})

    # ---- status -------------------------------------------------------------
    def status(self) -> list[dict]:
        rows = []
        root = self.ctx.repo / "work"
        if not root.is_dir():
            return rows
        for path in sorted(root.glob("*/state.yaml")):
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            pending = [g for g, s in (data.get("gates") or {}).items() if s.get("pending")]
            rows.append({
                "work_id": data.get("work_id"), "work_item": data.get("work_item"), "kind": data.get("kind"),
                "stage": data.get("stage"), "pending_gates": pending,
                "needs_decision": bool(pending) or data.get("stage") == "escalate",
                "question": (data.get("escalation") or {}).get("question"),
            })
        return rows
