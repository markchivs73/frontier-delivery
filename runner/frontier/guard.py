#!/usr/bin/env python3
"""PreToolUse guard hook for the frontier-delivery Claude Code plugin.

Enforces the process safety invariants deterministically, whatever the model
decides to do. Standard library only: it runs inside every Claude Code session
that has the plugin enabled, including CI.

Invariants enforced:
  * Agents never merge: `gh pr merge`, `gh pr ready`, merge API calls.

This is a guard rail, not a sandbox: a determined agent can get round shell-pattern
checks (`bash -c`, curl). The hard controls are outside it: in GitHub mode agents
get no GitHub or git credentials (the runner strips them), branch protection
guards the default branch, and the runner, not an agent, writes calibration data.
  * No force pushes, no pushes to the default branch, no commits on it.
  * Scope: rules apply to agent roles (subagents, or `--agent` sessions) and to
    any session with FRONTIER_STRICT=1 (the runner sets it). An ordinary
    interactive main session belongs to the human and is not restricted.
  * Single writer: only the implementer edits source. Planning roles write only
    under work/; check agents write only their envelope; retro and implementer
    cannot edit the policy or the guard itself.

Input: the hook JSON on stdin (tool_name, tool_input, cwd, agent_type).
Output: a PreToolUse deny decision on stdout, or nothing (no opinion).
"""
from __future__ import annotations

import fnmatch
import json
import os
import re
import shlex
import subprocess
import sys

DEFAULT_BRANCHES = {"main", "master", "trunk", "develop"}

WRITE_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}

CHECK_ROLES = {"check-requirements", "check-architecture", "check-security", "check-test-adequacy"}
PLANNING_ROLES = {"shaper", "requirements-analyst", "planner"}

# Paths no agent role may edit (the main session, which is the human's, may).
# In any repo using the process:
GOVERNANCE_PATHS = [
    ".frontier/policy.yaml",
    ".frontier/calibration.jsonl",
    ".claude/settings.json",
    ".github/workflows/frontier.yml",
]
# Additionally, when working in the frontier-delivery process repo itself:
PROCESS_GOVERNANCE_PATHS = [
    "policy/*",
    "contracts/*",
    "hooks/*",
    "runner/frontier/guard.py",
]


def governance_paths(cwd: str) -> list[str]:
    manifest = os.path.join(cwd, ".claude-plugin", "plugin.json")
    try:
        with open(manifest, encoding="utf-8") as fh:
            if json.load(fh).get("name") == "frontier-delivery":
                return GOVERNANCE_PATHS + PROCESS_GOVERNANCE_PATHS
    except (OSError, ValueError):
        pass
    return GOVERNANCE_PATHS


# Implementer may not edit the approved plan inputs.
IMPLEMENTER_FORBIDDEN = [
    "work/*/requirements.md",
    "work/*/design.md",
    "work/*/state.yaml",
    "work/*/backlog.yaml",
]

MERGE_PATTERNS = [
    (re.compile(r"\bgh\s+pr\s+merge\b"), "agents never merge PRs (gh pr merge)"),
    (re.compile(r"\bgh\s+pr\s+ready\b"), "agents never mark PRs ready; the gate does"),
    (re.compile(r"\bgh\s+api\b[^|;&]*/pulls/\d+/merge\b"), "agents never merge PRs (merge API)"),
    (re.compile(r"\bgh\s+api\b[^|;&]*\bmergePullRequest\b"), "agents never merge PRs (GraphQL)"),
    (re.compile(r"\bgh\s+api\b[^|;&]*\benablePullRequestAutoMerge\b"), "agents never enable auto-merge"),
]

READONLY_GIT = re.compile(
    r"\bgit\s+(commit|push|reset|rebase|merge|cherry-pick|revert|checkout\s+-b|switch\s+-c|branch\s+-[dDmM]|tag|stash)\b"
)


def role_of(agent_type: str | None) -> str | None:
    """`frontier-delivery:check-security` -> `check-security`. None = main session."""
    if not agent_type:
        return None
    return agent_type.rsplit(":", 1)[-1].strip() or None


def repo_root(cwd: str) -> str:
    """The git top level, so paths are judged relative to the repo, not a subdirectory."""
    try:
        out = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=cwd, capture_output=True, text=True, timeout=5)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except Exception:
        pass
    return cwd


def rel_path(path: str, cwd: str) -> str:
    if not path:
        return ""
    if not os.path.isabs(path):
        path = os.path.join(cwd, path)
    root = repo_root(cwd)
    try:
        path = os.path.relpath(os.path.normpath(path), root)
    except ValueError:
        pass
    return path.replace("\\", "/")


def matches_any(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, p) for p in patterns)


def head_is_default(cwd: str) -> str | None:
    """Name of the default branch if HEAD is on it, or detached at its tip."""
    branch = current_branch(cwd)
    if branch in DEFAULT_BRANCHES:
        return branch
    if branch is None:
        try:
            head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=cwd, capture_output=True, text=True, timeout=5).stdout.strip()
            for name in DEFAULT_BRANCHES:
                for ref in (name, f"origin/{name}"):
                    tip = subprocess.run(["git", "rev-parse", "--verify", "--quiet", ref], cwd=cwd, capture_output=True, text=True, timeout=5).stdout.strip()
                    if head and tip == head:
                        return f"{name} (detached)"
        except Exception:
            return None
    return None


def current_branch(cwd: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", "symbolic-ref", "--quiet", "--short", "HEAD"],
            cwd=cwd, capture_output=True, text=True, timeout=5,
        )
        return out.stdout.strip() if out.returncode == 0 else None
    except Exception:
        return None


def split_commands(command: str) -> list[str]:
    """Split a shell line on ;, &&, ||, | and newlines into simple commands."""
    return [c.strip() for c in re.split(r"(?:&&|\|\||;|\||\n)", command) if c.strip()]


PREFIXES = {"env", "command", "exec", "sudo", "nohup", "time", "builtin"}
PROTECTED_REMOTE_BRANCHES = {"frontier/metrics"}


def strip_prefixes(tokens: list[str]) -> list[str]:
    """Drop `VAR=value`, `env`, `command`, `sudo`, … so `env git push` is judged as `git push`."""
    i = 0
    while i < len(tokens) and (tokens[i] in PREFIXES or re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tokens[i]) or (tokens[i].startswith("-") and i > 0 and tokens[i - 1] in PREFIXES)):
        i += 1
    return tokens[i:]


def check_push(cmd: str, cwd: str = ".") -> str | None:
    try:
        tokens = shlex.split(cmd)
    except ValueError:
        tokens = cmd.split()
    tokens = strip_prefixes(tokens)
    if len(tokens) < 2 or os.path.basename(tokens[0]) != "git":
        return None
    # tolerate `git -C dir push`
    i = 1
    while i < len(tokens) and tokens[i].startswith("-"):
        i += 2 if tokens[i] in ("-C", "-c") else 1
    if i >= len(tokens) or tokens[i] != "push":
        return None
    args = tokens[i + 1:]
    flags = [a for a in args if a.startswith("-")]
    positional = [a for a in args if not a.startswith("-")]
    for a in flags:
        if a.startswith("--force") or a in ("--mirror", "--delete", "--all", "--prune"):
            return f"{a} pushes are not allowed"
        if not a.startswith("--") and ("f" in a[1:] or "d" in a[1:]):
            return "force pushes and remote deletes are not allowed"
    refspecs = positional[1:]  # the first positional is the remote
    if not refspecs:
        refspecs = ["HEAD"]  # a bare `git push` pushes the current branch
    for spec in refspecs:
        if spec.startswith("+"):
            return "force pushes (+refspec) are not allowed"
        if "*" in spec:
            return "glob refspecs are not allowed; push delivery/<id> explicitly"
        target = spec.split(":", 1)[-1] or spec
        if target in ("HEAD", "@"):
            target = current_branch(cwd) or head_is_default(cwd) or "HEAD"
        target = target.removeprefix("refs/heads/").split(" ")[0]
        if target.split(" ")[0] in DEFAULT_BRANCHES or target.startswith(tuple(f"{b} " for b in DEFAULT_BRANCHES)):
            return f"pushes to the default branch ({target}) are not allowed; push delivery/<id> and open a PR"
        if target in PROTECTED_REMOTE_BRANCHES:
            return f"{target} is written only by the runner"
    return None


def evaluate_bash(command: str, role: str | None, cwd: str) -> str | None:
    for pattern, reason in MERGE_PATTERNS:
        if pattern.search(command):
            return reason
    for cmd in split_commands(command):
        reason = check_push(cmd, cwd)
        if reason:
            return reason
    if re.search(r"\bgit\b[^;&|]*\bcommit\b", command):
        branch = head_is_default(cwd)
        if branch:
            return f"commits on the default branch ({branch}) are not allowed; work on delivery/<id>"
    if role in CHECK_ROLES and READONLY_GIT.search(command):
        return f"{role} is read-only: git history changes are not allowed"
    if role in PLANNING_ROLES and re.search(r"\bgit\s+(push|reset|rebase|merge)\b", command):
        return f"{role} may not change git history"
    return None


def evaluate_write(path: str, role: str | None, cwd: str = ".") -> str | None:
    governed = governance_paths(cwd)
    if role is None:
        # Strict main session (headless orchestrator runs): never edits governance.
        if matches_any(path, governed):
            return f"headless sessions may not edit governance files ({path})"
        return None
    if matches_any(path, governed):
        return f"{role} may not edit governance files ({path}); policy changes are the owner's PR"
    if role in CHECK_ROLES:
        if fnmatch.fnmatch(path, "work/*/envelopes/*"):
            return None
        return f"{role} is read-only; it may only write its envelope under work/<id>/envelopes/"
    if role in PLANNING_ROLES:
        if path.startswith("work/"):
            return None
        return f"{role} may only write under work/<id>/ (single-writer rule)"
    if role == "implementer" and matches_any(path, IMPLEMENTER_FORBIDDEN):
        return f"implementer may not edit approved plan artifacts ({path}); return needs_input instead"
    return None


def evaluate(payload: dict) -> str | None:
    tool = payload.get("tool_name", "")
    tool_input = payload.get("tool_input") or {}
    cwd = payload.get("cwd") or os.getcwd()
    role = role_of(payload.get("agent_type"))
    if role is None and os.environ.get("FRONTIER_STRICT") != "1":
        # The interactive main session belongs to the human. Headless runner
        # sessions set FRONTIER_STRICT=1 so the rules apply to them as well.
        return None
    if tool == "Bash":
        return evaluate_bash(str(tool_input.get("command", "")), role, cwd)
    if tool in WRITE_TOOLS:
        path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
        return evaluate_write(rel_path(str(path), cwd), role, cwd)
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0  # never break the session on malformed input
    reason = evaluate(payload)
    if reason:
        json.dump(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": f"frontier-delivery guard: {reason}",
                }
            },
            sys.stdout,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
