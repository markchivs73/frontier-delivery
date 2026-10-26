"""Reading and validating handoff envelopes against contracts/envelopes.schema.json."""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from .config import PROCESS_ROOT

CHECK_AGENTS = ["check-requirements", "check-architecture", "check-security", "check-test-adequacy"]


class EnvelopeError(Exception):
    """An agent did not produce a valid envelope."""


@lru_cache(maxsize=None)
def _schema_doc(name: str) -> dict:
    with open(PROCESS_ROOT / "contracts" / name, encoding="utf-8") as fh:
        return json.load(fh)


def schema_name(agent: str) -> str:
    return "check" if agent in CHECK_AGENTS else agent


def validator_for(defn: str) -> Draft202012Validator:
    doc = _schema_doc("envelopes.schema.json")
    if defn not in doc["$defs"]:
        raise KeyError(f"no envelope schema for {defn!r}")
    schema = {"$schema": doc["$schema"], "$defs": doc["$defs"], "$ref": f"#/$defs/{defn}"}
    return Draft202012Validator(schema)


def errors_for(defn: str, data: Any) -> list[str]:
    return [
        f"{'/'.join(str(p) for p in err.absolute_path) or '<root>'}: {err.message}"
        for err in validator_for(defn).iter_errors(data)
    ]


def validate(agent: str, data: Any) -> dict:
    if not isinstance(data, dict):
        raise EnvelopeError(f"{agent}: envelope is not a mapping")
    problems = errors_for(schema_name(agent), data)
    if problems:
        raise EnvelopeError(f"{agent}: invalid envelope:\n  " + "\n  ".join(problems))
    return data


def validate_policy(policy: dict) -> None:
    validator = Draft202012Validator(_schema_doc("policy.schema.json"))
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
