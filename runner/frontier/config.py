"""Locating the process files, the product repo, and loading policy/workflow."""
from __future__ import annotations

import copy
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

PROCESS_ROOT = Path(__file__).resolve().parents[2]


def slugify(ref: str) -> str:
    """Work-item reference -> directory/branch-safe id. gh:o/r#42 -> gh-o-r-42."""
    slug = re.sub(r"[^a-z0-9]+", "-", ref.lower()).strip("-")
    if not slug:
        raise ValueError(f"cannot derive a work id from {ref!r}")
    return slug[:80]


def load_yaml(path: Path) -> Any:
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


@dataclass
class Context:
    """Everything a runner command needs: where things are and what the rules are."""

    repo: Path
    process_root: Path = PROCESS_ROOT
    policy: dict = field(default_factory=dict)
    workflow: dict = field(default_factory=dict)
    policy_source: Path | None = None

    @classmethod
    def load(cls, repo: str | os.PathLike | None = None, policy_path: str | None = None) -> "Context":
        repo_path = Path(repo or os.getcwd()).resolve()
        default_policy = load_yaml(PROCESS_ROOT / "policy" / "policy.yaml")
        candidates = [Path(policy_path)] if policy_path else [repo_path / ".frontier" / "policy.yaml"]
        policy, source = default_policy, PROCESS_ROOT / "policy" / "policy.yaml"
        for candidate in candidates:
            if candidate.is_file():
                # Product policy overrides the default key by key, so a short
                # product file only needs to state what it changes.
                policy = deep_merge(default_policy, load_yaml(candidate) or {})
                source = candidate
                break
        ctx = cls(
            repo=repo_path,
            policy=policy,
            workflow=load_yaml(PROCESS_ROOT / "process" / "workflow.yaml"),
            policy_source=source,
        )
        from .envelopes import validate_policy  # late import: avoids a cycle

        validate_policy(ctx.policy)
        return ctx

    # ---- paths -------------------------------------------------------------
    def work_dir(self, work_id: str) -> Path:
        return self.repo / "work" / work_id

    def records_path(self) -> Path:
        override = os.environ.get("FRONTIER_RECORDS")
        path = Path(override) if override else Path(self.policy["calibration"]["records"])
        return path if path.is_absolute() else self.repo / path

    # ---- policy helpers ----------------------------------------------------
    def budget(self, name: str) -> int:
        return int(self.policy["budgets"][name])

    def runner_setting(self, key: str, default: Any = None) -> Any:
        return (self.policy.get("runner") or {}).get(key, default)
