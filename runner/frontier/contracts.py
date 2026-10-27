"""Contracts as data: closed JSON Schema 2020-12 for shape, plus CEL rules scoped to
`self` for the cross-field invariants a schema can't express.

This follows the E27 contract model (a Kubernetes CRD analogue):
  * one closed schema per contract, self-contained, with no remote $ref;
  * CEL rules embedded under `x-frontier-validations` (cf. x-kubernetes-validations),
    with no I/O and no cross-contract lookups;
  * each contract is pinned by id, major and sha256 of its canonical bytes in
    contracts/contracts.lock.json. The runner refuses bytes that don't match the
    pin; it never fetches a contract mid-run. This repo stands in for the
    registry until contracts are published there.

Canonical form: JSON with sorted keys, no insignificant whitespace, UTF-8, which
matches RFC 8785 (JCS) for these documents (no floats). If the registry settles on
a different canonicalisation, change `canonical_bytes` and re-lock.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import celpy
from jsonschema import Draft202012Validator

from .config import PROCESS_ROOT

CONTRACTS_DIR = PROCESS_ROOT / "contracts" / "delivery"
LOCK_FILE = PROCESS_ROOT / "contracts" / "contracts.lock.json"
RULES_KEY = "x-frontier-validations"


class ContractError(Exception):
    """A contract is missing, unpinned, tampered with, or malformed."""


def canonical_bytes(doc: Any) -> bytes:
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def digest(doc: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(doc)).hexdigest()


def _load_doc(path: Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def discover(directory: Path = CONTRACTS_DIR) -> dict[str, dict]:
    """contract id -> {major, file, doc} for every *.schema.json in the directory."""
    found = {}
    for path in sorted(directory.glob("*.schema.json")):
        doc = _load_doc(path)
        meta = doc.get("x-frontier-contract") or {}
        if "id" not in meta or "major" not in meta:
            raise ContractError(f"{path.name}: missing x-frontier-contract id/major")
        found[meta["id"]] = {"major": meta["major"], "file": path.name, "doc": doc}
    return found


def build_lock(directory: Path = CONTRACTS_DIR) -> dict:
    return {
        "lockVersion": 1,
        "canonicalisation": "json-sorted-keys-compact-utf8",
        "contracts": {
            cid: {"major": c["major"], "file": f"delivery/{c['file']}", "digest": digest(c["doc"])}
            for cid, c in discover(directory).items()
        },
    }


def write_lock() -> dict:
    lock = build_lock()
    LOCK_FILE.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
    return lock


def verify_lock() -> list[str]:
    """Every contract file pinned, every pin matching its bytes. Empty list = good."""
    if not LOCK_FILE.is_file():
        return ["contracts.lock.json is missing; run `python -m frontier contracts lock`"]
    pinned = json.loads(LOCK_FILE.read_text(encoding="utf-8"))["contracts"]
    actual = build_lock()["contracts"]
    problems = []
    for cid, entry in actual.items():
        if cid not in pinned:
            problems.append(f"{cid} is not pinned in the lock")
        elif pinned[cid]["digest"] != entry["digest"]:
            problems.append(f"{cid} bytes changed since it was pinned (a published version is immutable: bump the major or re-lock before publishing)")
    for cid in pinned.keys() - actual.keys():
        problems.append(f"{cid} is pinned but its file is missing")
    return problems


@dataclass
class Violation:
    path: str
    message: str
    rule: str | None = None   # set for CEL violations

    def __str__(self) -> str:
        where = self.path or "<root>"
        return f"{where}: {self.message}" + (f"  [rule: {self.rule}]" if self.rule else "")


class Contract:
    """One pinned contract: the closed schema validator plus compiled CEL rules."""

    def __init__(self, contract_id: str, doc: dict):
        self.id = contract_id
        self.doc = doc
        self.digest = digest(doc)
        Draft202012Validator.check_schema(doc)
        self._schema = Draft202012Validator(doc)
        env = celpy.Environment()
        self._rules = []
        for spec in doc.get(RULES_KEY, []):
            try:
                program = env.program(env.compile(spec["rule"]))
            except Exception as exc:  # type-check at registration, not at runtime
                raise ContractError(f"{contract_id}: rule does not compile: {spec['rule']}: {exc}") from exc
            self._rules.append((spec, program))

    def validate(self, payload: Any) -> list[Violation]:
        violations = [
            Violation("/".join(str(p) for p in err.absolute_path), err.message)
            for err in self._schema.iter_errors(payload)
        ]
        if violations:
            return violations  # CEL rules assume a structurally valid payload, as in Kubernetes
        activation = {"self": celpy.json_to_cel(payload)}
        for spec, program in self._rules:
            try:
                ok = bool(program.evaluate(activation))
            except Exception as exc:
                violations.append(Violation(spec.get("fieldPath", ""), f"rule could not be evaluated: {exc}", spec["rule"]))
                continue
            if not ok:
                violations.append(Violation(spec.get("fieldPath", ""), spec["message"], spec["rule"]))
        return violations


@lru_cache(maxsize=None)
def registry() -> dict[str, Contract]:
    """All pinned contracts, verified against the lock before first use."""
    problems = verify_lock()
    if problems:
        raise ContractError("contract pins do not match:\n  " + "\n  ".join(problems))
    return {cid: Contract(cid, c["doc"]) for cid, c in discover().items()}


def get(contract_id: str) -> Contract:
    try:
        return registry()[contract_id]
    except KeyError:
        raise ContractError(f"unknown contract {contract_id!r}") from None
