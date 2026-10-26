"""The few git operations the runner needs. Agents commit their own code; the runner
only manages branches and commits the process artifacts under work/."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .gate import DiffStats


class GitError(Exception):
    pass


def git(repo: Path, *args: str, check: bool = True) -> str:
    proc = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout.strip()


def current_branch(repo: Path) -> str:
    return git(repo, "rev-parse", "--abbrev-ref", "HEAD")


def default_branch(repo: Path) -> str:
    if os.environ.get("FRONTIER_BASE"):
        return os.environ["FRONTIER_BASE"]
    ref = git(repo, "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD", check=False)
    if ref:
        return ref.rsplit("/", 1)[-1]
    for candidate in ("main", "master"):
        if git(repo, "rev-parse", "--verify", "--quiet", candidate, check=False):
            return candidate
    return "main"


def ensure_branch(repo: Path, branch: str) -> None:
    """Switch to `branch`, creating it from the current HEAD (or origin) if needed."""
    if current_branch(repo) == branch:
        return
    if git(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}", check=False):
        git(repo, "checkout", branch)
    elif git(repo, "rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{branch}", check=False):
        git(repo, "checkout", "-b", branch, "--track", f"origin/{branch}")
    else:
        git(repo, "checkout", "-b", branch)


def commit_paths(repo: Path, paths: list[str], message: str) -> bool:
    git(repo, "add", "--force", "--", *paths)  # --force: work/ may be gitignored in some repos
    if not git(repo, "diff", "--cached", "--name-only", check=False):
        return False
    git(repo, "commit", "-m", message)
    return True


def diff_stats(repo: Path, base: str) -> DiffStats:
    """Changed files and lines on this branch vs base, excluding process artifacts."""
    merge_base = git(repo, "merge-base", base, "HEAD", check=False) or base
    out = git(repo, "diff", "--numstat", f"{merge_base}...HEAD", "--", ".", ":(exclude)work/**", check=False)
    files, lines = [], 0
    for row in out.splitlines():
        parts = row.split("\t")
        if len(parts) != 3:
            continue
        added, removed, path = parts
        files.append(path)
        lines += (int(added) if added.isdigit() else 0) + (int(removed) if removed.isdigit() else 0)
    return DiffStats(files=files, lines=lines)
