"""Reading handoff envelopes and validating them against their pinned contracts."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from . import contracts
from .config import PROCESS_ROOT

CHECK_AGENTS = ["check-requirements", "check-architecture", "check-security", "check-test-adequacy"]


class EnvelopeError(Exception):
    """An agent did not produce a valid envelope."""


# Envelope contract ids, keyed by agent (all four check agents share one contract).
CONTRACT_FOR = {
    "shaper": "frontier.delivery.shaper-envelope",
    "requirements-analyst": "frontier.delivery.requirements-analyst-envelope",
    "planner": "frontier.delivery.planner-envelope",
    "implementer": "frontier.delivery.implementer-envelope",
    "retro": "frontier.delivery.retro-envelope",
    **{a: "frontier.delivery.check-envelope" for a in CHECK_AGENTS},
}


def contract_for(agent: str) -> str:
    if agent not in CONTRACT_FOR:
        raise KeyError(f"no envelope contract for {agent!r}")
    return CONTRACT_FOR[agent]


def errors_for(agent: str, data: Any) -> list[str]:
    return [str(v) for v in contracts.get(contract_for(agent)).validate(data)]


def validate(agent: str, data: Any) -> dict:
    if not isinstance(data, dict):
        raise EnvelopeError(f"{agent}: envelope is not a mapping")
    problems = errors_for(agent, data)
    if problems:
        raise EnvelopeError(f"{agent}: envelope violates {contract_for(agent)}:\n  " + "\n  ".join(problems))
    return data


def validate_policy(policy: dict) -> None:
    """The gate policy is configuration bound beside the process, not a contract."""
    with open(PROCESS_ROOT / "policy" / "policy.schema.json", encoding="utf-8") as fh:
        validator = Draft202012Validator(json.load(fh))
    problems = [f"{'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}" for e in validator.iter_errors(policy)]
    if problems:
        raise ValueError("invalid policy:\n  " + "\n  ".join(problems))


FENCE = re.compile(r"```(?:ya?ml)\s*\n(.*?)```", re.DOTALL)


def parse_from_text(text: str) -> dict | None:
    """Fallback: the last fenced YAML block in an agent's reply."""
    for block in reversed(FENCE.findall(text or "")):
        try:
            data = yaml.safe_load(block)
        except yaml.YAMLError:
            continue
        if isinstance(data, dict) and "status" in data:
            return data
    return None


def envelope_path(work_dir: Path, agent: str) -> Path:
    return work_dir / "envelopes" / f"{agent}.yaml"


def read(work_dir: Path, agent: str, reply_text: str = "") -> dict:
    """Read an agent's envelope: the file first, then the reply text."""
    path = envelope_path(work_dir, agent)
    data = None
    if path.is_file():
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise EnvelopeError(f"{agent}: {path} is not valid YAML: {exc}") from exc
    if data is None:
        data = parse_from_text(reply_text)
        if data is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    if data is None:
        raise EnvelopeError(f"{agent}: no envelope at {path} and none in the reply")
    return validate(agent, data)
