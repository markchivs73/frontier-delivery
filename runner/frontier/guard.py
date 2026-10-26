#!/usr/bin/env python3
"""PreToolUse guard hook for the frontier-delivery Claude Code plugin.

Enforces the process safety invariants deterministically, whatever the model
decides to do. Standard library only: it runs inside every Claude Code session
that has the plugin enabled, including CI.

Invariants enforced:
  * Agents never merge: `gh pr merge`, `gh pr ready`, merge API calls.
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


def rel_path(path: str, cwd: str) -> str:
    if not path:
        return ""
    if os.path.isabs(path):
        try:
            path = os.path.relpath(path, cwd)
        except ValueError:
            return path.replace("\\", "/")
    path = os.path.normpath(path).replace("\\", "/")
    return path


def matches_any(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, p) for p in patterns)


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


def check_push(cmd: str) -> str | None:
    try:
        tokens = shlex.split(cmd)
    except ValueError:
        tokens = cmd.split()
    if len(tokens) < 2 or tokens[0] != "git":
        return None
    # tolerate `git -C dir push`
    i = 1
    while i < len(tokens) and tokens[i].startswith("-"):
        i += 2 if tokens[i] in ("-C", "-c") else 1
    if i >= len(tokens) or tokens[i] != "push":
        return None
    args = tokens[i + 1:]
    if any(a in ("-f", "--force", "--mirror", "--delete", "-d") or a.startswith("--force") for a in args):
        return "force pushes and remote deletes are not allowed"
    if any(a.startswith("+") for a in args):
        return "force pushes (+refspec) are not allowed"
    for a in args:
        target = a.split(":", 1)[-1]
        target = target.removeprefix("refs/heads/")
        if target in DEFAULT_BRANCHES:
            return f"pushes to the default branch ({target}) are not allowed; push delivery/<id> and open a PR"
    return None


def evaluate_bash(command: str, role: str | None, cwd: str) -> str | None:
    for pattern, reason in MERGE_PATTERNS:
        if pattern.search(command):
            return reason
    for cmd in split_commands(command):
        reason = check_push(cmd)
        if reason:
            return reason
    if re.search(r"\bgit\b[^;&|]*\bcommit\b", command):
        branch = current_branch(cwd)
        if branch in DEFAULT_BRANCHES:
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
