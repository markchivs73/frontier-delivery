"""Contract conformance: every case in contracts/delivery/conformance/ gets the expected verdict.

These fixtures are implementation-neutral. The .NET engine's validator (closed
JSON Schema + CEL) should pass the same cases; that is the cross-implementation
check on CEL semantics.
"""
from pathlib import Path

import pytest
import yaml

from frontier import contracts

CASES_DIR = Path(contracts.CONTRACTS_DIR) / "conformance"


def load_cases():
    for path in sorted(CASES_DIR.glob("*.yaml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        for case in doc["cases"]:
            yield pytest.param(doc["contract"], case, id=f"{path.stem}: {case['name']}")


def test_lock_matches_contract_bytes():
    assert contracts.verify_lock() == []


def test_every_contract_is_closed_and_self_contained():
    for cid, entry in contracts.discover().items():
        doc = entry["doc"]
        assert doc["$schema"] == "https://json-schema.org/draft/2020-12/schema", cid
        assert doc.get("additionalProperties") is False, f"{cid} root is not closed"
        text = Path(contracts.CONTRACTS_DIR / entry["file"]).read_text()
        assert '"$ref": "http' not in text and '"$ref": "urn' not in text, f"{cid} has a remote $ref"

        def walk(node, where):
            if isinstance(node, dict):
                if node.get("type") == "object" and "properties" in node:
                    assert node.get("additionalProperties") is False, f"{cid} {where} is not closed"
                for k, v in node.items():
                    walk(v, f"{where}/{k}")
            elif isinstance(node, list):
                for i, v in enumerate(node):
                    walk(v, f"{where}/{i}")
        walk(doc, "")


def test_every_contract_has_conformance_cases():
    covered = {yaml.safe_load(p.read_text())["contract"] for p in CASES_DIR.glob("*.yaml")}
    assert covered == set(contracts.discover())


@pytest.mark.parametrize("contract_id,case", list(load_cases()))
def test_conformance(contract_id, case):
    violations = contracts.get(contract_id).validate(case["payload"])
    if case["valid"]:
        assert violations == [], [str(v) for v in violations]
        return
    assert violations, "expected the payload to be rejected"
    if case.get("structural"):
        assert all(v.rule is None for v in violations), "expected a schema (structural) rejection"
    else:
        assert sorted(v.message for v in violations) == sorted(case["violates"])
