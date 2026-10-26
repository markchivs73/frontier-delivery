"""GitHub-native mode: turn GitHub Actions events into runner calls, and Outcomes
into comments, labels, branches and PRs.

Humans drive everything through labels and comments:
  label `frontier:shape` on an idea issue      -> shape (options)
  label `frontier:deliver` on a story issue    -> intake + plan -> plan gate
  `/option <n|title>`                          -> write the backlog for that option
  `/approve`                                   -> approve the pending gate and continue
  `/changes <text>`                            -> send the pending stage back with your words
  `/reject`                                    -> stop
  `/answer <text>`                             -> answer an escalation and resume
  PR merged/closed                             -> record the merge gate, run retro

Only comments from OWNER/MEMBER/COLLABORATOR associations are acted on.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

from .config import slugify
from .git import git
from .orchestrate import Orchestrator, Outcome
from .state import State

LABELS = {
    "frontier:shape": ("5319e7", "Shape this idea into a backlog"),
    "frontier:deliver": ("0e8a16", "Deliver this story"),
    "frontier:story": ("c5def5", "A shaped story"),
    "frontier:needs-decision": ("d93f0b", "Waiting on a human decision"),
    "frontier:gate-backlog": ("fbca04", "Backlog gate pending"),
    "frontier:gate-plan": ("fbca04", "Plan gate pending"),
    "frontier:gate-merge": ("fbca04", "Merge gate pending"),
    "frontier:escalated": ("b60205", "Escalated to a human"),
}
GATE_LABELS = ["frontier:gate-backlog", "frontier:gate-plan", "frontier:gate-merge", "frontier:needs-decision", "frontier:escalated"]
TRUSTED = {"OWNER", "MEMBER", "COLLABORATOR"}
COMMAND = re.compile(r"^/(approve|changes|reject|option|answer)\b[ \t]*(.*)", re.DOTALL)
METRICS_BRANCH = "frontier/metrics"


class GH:
    def __init__(self, repo_slug: str, cwd: Path):
        self.repo = repo_slug
        self.cwd = cwd
        self.bin = os.environ.get("FRONTIER_GH_BIN", "gh")
        self._labels_ready = False

    def __call__(self, *args: str, input_text: str | None = None, check: bool = True) -> str:
        proc = subprocess.run([self.bin, *args], cwd=self.cwd, input=input_text, capture_output=True, text=True)
        if check and proc.returncode != 0:
            raise RuntimeError(f"gh {' '.join(args[:3])} failed: {proc.stderr.strip()}")
        return proc.stdout.strip()

    def ensure_labels(self) -> None:
        if self._labels_ready:
            return
        for name, (color, desc) in LABELS.items():
            self("label", "create", name, "--repo", self.repo, "--color", color, "--description", desc, "--force", check=False)
        self._labels_ready = True

    def comment(self, number: int, body: str) -> None:
        self("issue", "comment", str(number), "--repo", self.repo, "--body-file", "-", input_text=body)

    def set_labels(self, number: int, add: list[str], remove: list[str]) -> None:
        self.ensure_labels()
        args = ["issue", "edit", str(number), "--repo", self.repo]
        for label in add:
            args += ["--add-label", label]
        for label in remove:
            if label not in add:
                args += ["--remove-label", label]
        if len(args) > 5:
            self(*args, check=False)

    def find_pr(self, branch: str) -> dict | None:
        out = self("pr", "list", "--repo", self.repo, "--head", branch, "--state", "open", "--json", "number,url,isDraft", check=False)
        prs = json.loads(out or "[]")
        return prs[0] if prs else None


def _push(repo: Path, branch: str) -> None:
    git(repo, "push", "--set-upstream", "origin", branch)


def _checkout_remote(repo: Path, branch: str) -> bool:
    if not git(repo, "ls-remote", "--heads", "origin", branch, check=False):
        return False
    git(repo, "fetch", "origin", f"{branch}:refs/remotes/origin/{branch}")
    if git(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}", check=False):
        git(repo, "checkout", branch)
        git(repo, "reset", "--hard", f"origin/{branch}")
    else:
        git(repo, "checkout", "-b", branch, "--track", f"origin/{branch}")
    return True


# ---- calibration records live on an orphan branch ----------------------------
class Metrics:
    """calibration.jsonl on the frontier/metrics branch, kept out of main's history."""

    def __init__(self, repo: Path):
        self.repo = repo
        self.dir = Path(tempfile.mkdtemp(prefix="frontier-metrics-"))
        self.file = self.dir / "calibration.jsonl"

    def pull(self) -> Path:
        if git(self.repo, "ls-remote", "--heads", "origin", METRICS_BRANCH, check=False):
            git(self.repo, "fetch", "origin", f"{METRICS_BRANCH}:refs/remotes/origin/{METRICS_BRANCH}")
            content = git(self.repo, "show", f"origin/{METRICS_BRANCH}:calibration.jsonl", check=False)
            self.file.write_text(content + ("\n" if content else ""), encoding="utf-8")
        else:
            self.file.write_text("", encoding="utf-8")
        self.original = self.file.read_text(encoding="utf-8")
        os.environ["FRONTIER_RECORDS"] = str(self.file)
        return self.file

    def push(self, message: str) -> None:
        if self.file.read_text(encoding="utf-8") == self.original:
            return
        wt = self.dir / "wt"
        remote = bool(git(self.repo, "ls-remote", "--heads", "origin", METRICS_BRANCH, check=False))
        if remote:
            git(self.repo, "worktree", "add", "-B", METRICS_BRANCH, str(wt), f"origin/{METRICS_BRANCH}")
        else:
            git(self.repo, "worktree", "add", "--detach", str(wt))
            git(wt, "checkout", "--orphan", METRICS_BRANCH)
            git(wt, "rm", "-rf", "--quiet", ".", check=False)
        (wt / "calibration.jsonl").write_text(self.file.read_text(encoding="utf-8"), encoding="utf-8")
        (wt / "README.md").write_text("Gate calibration records written by frontier-delivery. Do not edit by hand.\n", encoding="utf-8")
        git(wt, "add", "calibration.jsonl", "README.md")
        git(wt, "commit", "-m", message)
        git(wt, "push", "origin", f"HEAD:{METRICS_BRANCH}")
        git(self.repo, "worktree", "remove", "--force", str(wt), check=False)


# ---- outcome → GitHub ---------------------------------------------------------
GATE_LABEL = {"backlog": "frontier:gate-backlog", "plan": "frontier:gate-plan", "merge": "frontier:gate-merge"}


def publish_outcome(gh: GH, orch: Orchestrator, outcome: Outcome, *, issue: int, branch: str, title: str) -> None:
    """Push the branch, make sure a PR exists for deliveries, comment, and set labels."""
    repo = orch.ctx.repo
    _push(repo, branch)
    target = issue
    if branch.startswith("delivery/"):
        pr = gh.find_pr(branch)
        body = outcome.data.get("pr_body") or f"Delivery for #{issue} via frontier-delivery. Plan under review.\n\nCloses #{issue}"
        if "Closes #" not in body:
            body += f"\n\nCloses #{issue}"
        if not pr:
            gh("pr", "create", "--repo", gh.repo, "--draft", "--head", branch, "--title", f"[frontier] {title}", "--body-file", "-", input_text=body)
            pr = gh.find_pr(branch)
        elif outcome.data.get("pr_body"):
            gh("pr", "edit", str(pr["number"]), "--repo", gh.repo, "--body-file", "-", input_text=body)
        target = pr["number"] if pr else issue
        if issue != target:
            gh.set_labels(issue, [], GATE_LABELS)
    if outcome.message:
        gh.comment(target, outcome.message)
    add: list[str] = []
    if outcome.status == "waiting" and outcome.gate:
        add = [GATE_LABEL[outcome.gate], "frontier:needs-decision"]
    elif outcome.status == "escalated":
        add = ["frontier:escalated", "frontier:needs-decision"]
    gh.set_labels(target, add, GATE_LABELS)
    if "enable_auto_merge" in outcome.actions and branch.startswith("delivery/"):
        # Deterministic code, not an agent, enables auto-merge; branch protection still decides.
        gh("pr", "ready", str(target), "--repo", gh.repo, check=False)
        gh("pr", "merge", str(target), "--repo", gh.repo, "--auto", "--squash", check=False)


def publish_stories(gh: GH, orch: Orchestrator, shape_id: str, issue: int) -> str:
    stories = orch.stories(shape_id)
    created: dict[str, int] = {}
    lines = []
    for story in stories:
        deps = ", ".join(f"#{created[d]}" if d in created else d for d in story["depends_on"]) or "none"
        body = story["body"].replace(f"- **Depends on**: {', '.join(story['depends_on']) or 'none'}", f"- **Depends on**: {deps}")
        body += f"\n\nShaped from #{issue}."
        url = gh("issue", "create", "--repo", gh.repo, "--title", story["title"], "--label", "frontier:story", "--body-file", "-", input_text=body)
        number = int(url.rstrip("/").rsplit("/", 1)[-1])
        created[story["id"]] = number
        lines.append(f"- {story['id']}: #{number} {story['title']}")
    policy = orch.ctx.policy.get("backlog") or {}
    started = []
    if policy.get("auto_start"):
        ready = [s for s in stories if not s["depends_on"]][: int(policy.get("max_parallel", 1))]
        workflow = os.environ.get("FRONTIER_CALLER_WORKFLOW", "frontier.yml")
        for s in ready:
            # workflow_dispatch is one of the few events GITHUB_TOKEN may trigger.
            gh("workflow", "run", workflow, "--repo", gh.repo, "-f", "stage=deliver", "-f", f"issue={created[s['id']]}", check=False)
            started.append(f"#{created[s['id']]}")
    msg = "Published the backlog:\n" + "\n".join(lines)
    if started:
        msg += f"\n\nStarted delivery for {', '.join(started)} (backlog.auto_start)."
    else:
        msg += "\n\nAdd the `frontier:deliver` label to a story to start its delivery."
    return msg


# ---- event handling ------------------------------------------------------------
def _issue_source(issue: dict) -> str:
    return f"# {issue.get('title', '')}\n\n{issue.get('body') or ''}"


def _start_shape(orch: Orchestrator, gh: GH, repo_slug: str, issue: dict) -> int:
    ref = f"gh:{repo_slug}#{issue['number']}"
    outcome = orch.shape(ref, idea=_issue_source(issue))
    publish_outcome(gh, orch, outcome, issue=issue["number"], branch=f"shape/{slugify(ref)}", title=issue["title"])
    return 3 if outcome.status == "escalated" else 0


def _start_delivery(orch: Orchestrator, gh: GH, repo_slug: str, issue: dict) -> int:
    ref = f"gh:{repo_slug}#{issue['number']}"
    wid = slugify(ref)
    branch = f"delivery/{wid}"
    _checkout_remote(orch.ctx.repo, branch)
    outcome = orch.plan(ref, source=_issue_source(issue))
    if outcome.status == "continue" and "build" in outcome.actions:
        publish_outcome(gh, orch, outcome, issue=issue["number"], branch=branch, title=issue["title"])
        outcome = orch.build(wid)
    publish_outcome(gh, orch, outcome, issue=issue["number"], branch=branch, title=issue["title"])
    return 3 if outcome.status == "escalated" else 0


def _handle_command(orch: Orchestrator, gh: GH, repo_slug: str, event: dict) -> int:
    comment = event["comment"]
    if comment.get("author_association") not in TRUSTED or (comment.get("user") or {}).get("type") == "Bot":
        return 0
    match = COMMAND.match((comment.get("body") or "").strip())
    if not match:
        return 0
    cmd, text = match.group(1), match.group(2).strip()
    issue = event["issue"]
    number = issue["number"]
    by = (comment.get("user") or {}).get("login", "human")
    repo = orch.ctx.repo
    if issue.get("pull_request"):
        pr = json.loads(gh("pr", "view", str(number), "--repo", repo_slug, "--json", "headRefName,title,body"))
        branch = pr["headRefName"]
        found = re.search(r"Closes #(\d+)", pr.get("body") or "")
        story_issue = int(found.group(1)) if found else number
        title = pr["title"].removeprefix("[frontier] ")
    else:
        wid = slugify(f"gh:{repo_slug}#{number}")
        branch = next((b for b in (f"delivery/{wid}", f"shape/{wid}") if git(repo, "ls-remote", "--heads", "origin", b, check=False)), "")
        story_issue, title = number, issue["title"]
    if not branch.startswith(("delivery/", "shape/")) or not _checkout_remote(repo, branch):
        gh.comment(number, "frontier-delivery: nothing to act on here (no shape/ or delivery/ branch).")
        return 0
    wid = branch.split("/", 1)[1]
    state = State.read(orch.ctx.work_dir(wid))
    pending = next((g for g, s in state.data.get("gates", {}).items() if s.get("pending")), None)

    if cmd == "answer":
        outcome = orch.answer(wid, text)
    elif cmd == "option":
        if pending != "backlog" or state.data["gates"]["backlog"].get("phase") != "options":
            gh.comment(number, "frontier-delivery: `/option` only applies while choosing a shaping option.")
            return 0
        options = state.data["gates"]["backlog"].get("options", [])
        head, _, notes = text.partition("\n")
        choice = options[int(head) - 1] if head.strip().isdigit() and 0 < int(head) <= len(options) else head.strip()
        state.data["gates"]["backlog"].update(pending=False, decision="option", decided_by=by)
        state.save()
        outcome = orch.shape(state.work_item, choice=choice + (f"\n\n{notes.strip()}" if notes.strip() else ""))
    elif cmd == "reject" and state.stage == "escalate":
        state.move("done", f"rejected by {by}")
        state.save()
        orch._commit(wid, f"frontier: rejected {wid}")
        outcome = Outcome(wid, "done", "done", f"Stopped at your request (@{by}).")
    else:
        if not pending:
            gh.comment(number, f"frontier-delivery: no gate is waiting here (stage `{state.stage}`).")
            return 0
        decision = {"approve": "approve", "changes": "changes", "reject": "reject"}[cmd]
        decided = orch.decide(wid, pending, decision, by, text or None)
        gh.comment(number, decided.message)
        if decision == "reject":
            outcome = decided
        elif pending == "backlog" and decision == "approve":
            gh.comment(number, publish_stories(gh, orch, wid, story_issue))
            outcome = Outcome(wid, "done", "done")
        elif pending == "backlog":
            outcome = orch.shape(state.work_item, comments=text)
        elif pending == "plan" and decision == "approve":
            publish_outcome(gh, orch, Outcome(wid, "implement", "continue"), issue=story_issue, branch=branch, title=title)
            outcome = orch.build(wid)
        elif pending == "plan":
            outcome = orch.plan(state.work_item, comments=text)
        elif pending == "merge" and decision == "approve":
            gh("pr", "ready", str(number), "--repo", repo_slug, check=False)
            outcome = Outcome(wid, "merged", "done")
        else:  # merge changes
            outcome = orch.build(wid, human_comments=text)
    publish_outcome(gh, orch, outcome, issue=story_issue, branch=branch, title=title)
    return 3 if outcome.status == "escalated" else 0


def _review_text(gh: GH, number: int) -> str:
    parts = []
    for endpoint in ("reviews", "comments"):
        out = gh("api", f"repos/{gh.repo}/pulls/{number}/{endpoint}", "--paginate", check=False)
        try:
            for item in json.loads(out or "[]"):
                body = (item.get("body") or "").strip()
                if body and "<!-- frontier-delivery -->" not in body:
                    where = f" ({item['path']}:{item.get('line')})" if item.get("path") else ""
                    parts.append(f"- @{(item.get('user') or {}).get('login', '?')}{where}: {body}")
        except json.JSONDecodeError:
            continue
    return "\n".join(parts)


def _handle_closed(orch: Orchestrator, gh: GH, event: dict) -> int:
    pr = event["pull_request"]
    branch = pr["head"]["ref"]
    if not branch.startswith("delivery/"):
        return 0
    repo = orch.ctx.repo
    git(repo, "fetch", "origin", f"pull/{pr['number']}/head:refs/remotes/origin/pr-{pr['number']}")
    git(repo, "checkout", "--detach", f"origin/pr-{pr['number']}")
    wid = branch.split("/", 1)[1]
    orch.commit = False  # the PR is closed; nothing more is pushed to it
    outcome = orch.learn(wid, merged=bool(pr.get("merged")), review=_review_text(gh, pr["number"]),
                         decided_by=(pr.get("merged_by") or {}).get("login", "human"))
    gh.comment(pr["number"], outcome.message)
    gh.set_labels(pr["number"], [], GATE_LABELS)
    return 0


def handle_event(orch: Orchestrator, event_name: str, event_path: str) -> int:
    event = json.loads(Path(event_path).read_text(encoding="utf-8"))
    repo_slug = os.environ.get("GITHUB_REPOSITORY") or event["repository"]["full_name"]
    gh = GH(repo_slug, orch.ctx.repo)
    metrics = Metrics(orch.ctx.repo)
    metrics.pull()
    try:
        if event_name == "issues" and event.get("action") == "labeled":
            label = (event.get("label") or {}).get("name")
            if label == "frontier:shape":
                return _start_shape(orch, gh, repo_slug, event["issue"])
            if label == "frontier:deliver":
                return _start_delivery(orch, gh, repo_slug, event["issue"])
            return 0
        if event_name == "workflow_dispatch":
            inputs = event.get("inputs") or {}
            issue = json.loads(gh("issue", "view", str(inputs["issue"]), "--repo", repo_slug, "--json", "number,title,body"))
            if inputs.get("stage") == "shape":
                return _start_shape(orch, gh, repo_slug, issue)
            return _start_delivery(orch, gh, repo_slug, issue)
        if event_name == "issue_comment" and event.get("action") == "created":
            return _handle_command(orch, gh, repo_slug, event)
        if event_name == "pull_request" and event.get("action") == "closed":
            return _handle_closed(orch, gh, event)
        return 0
    finally:
        metrics.push(f"frontier: calibration records ({event_name})")
