"""The runner's ledger: calibration records and sealed gate recommendations.

Both are runner-only state. Agents must not be able to read sealed
recommendations (that would anchor the human, or let an agent game a gate) or
write calibration records (that would let an agent unlock `auto`). So:

  * The ledger is loaded once, before any agent runs, and kept in memory.
    Decisions are always made from the in-memory copy.
  * New records are tracked separately and written out by the runner alone,
    on top of the snapshot it loaded, never by re-reading a file an agent
    could have touched in the meantime.
  * Nothing sealed is ever written under work/ or committed to a delivery branch.

Local mode persists to `.frontier/calibration.jsonl` and `.frontier/sealed.json`
in the product repo (keep them out of git). GitHub mode keeps both on the orphan
`frontier/metrics` branch (see github.py), which only the runner pushes.
"""
from __future__ import annotations

import json
from pathlib import Path


class Ledger:
    def __init__(self, records: list[dict] | None = None, seals: dict | None = None,
                 records_path: Path | None = None, seals_path: Path | None = None):
        self.loaded_records = list(records or [])
        self.appended: list[dict] = []
        self.seals = dict(seals or {})
        self.records_path = records_path
        self.seals_path = seals_path

    # ---- construction -----------------------------------------------------
    @staticmethod
    def parse_records(text: str) -> list[dict]:
        out = []
        for line in (text or "").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out

    @classmethod
    def from_files(cls, records_path: Path, seals_path: Path) -> "Ledger":
        records = cls.parse_records(records_path.read_text(encoding="utf-8")) if records_path.is_file() else []
        seals = json.loads(seals_path.read_text(encoding="utf-8")) if seals_path.is_file() else {}
        return cls(records, seals, records_path, seals_path)

    # ---- records ------------------------------------------------------------
    def records(self) -> list[dict]:
        return self.loaded_records + self.appended

    def append(self, record: dict) -> None:
        from . import contracts  # records are themselves a contract

        violations = contracts.get("frontier.delivery.gate-record").validate(record)
        if violations:
            raise ValueError("gate record violates frontier.delivery.gate-record: " + "; ".join(map(str, violations)))
        self.appended.append(record)
        if self.records_path is not None:
            self.records_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.records_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, sort_keys=True) + "\n")

    def records_text(self) -> str:
        return "".join(json.dumps(r, sort_keys=True) + "\n" for r in self.records())

    # ---- seals -------------------------------------------------------------
    @staticmethod
    def key(work_id: str, gate: str) -> str:
        return f"{work_id}/{gate}"

    def seal(self, work_id: str, gate: str, sealed: dict) -> None:
        self.seals[self.key(work_id, gate)] = sealed
        self._save_seals()

    def unseal(self, work_id: str, gate: str) -> dict | None:
        sealed = self.seals.pop(self.key(work_id, gate), None)
        self._save_seals()
        return sealed

    def seals_text(self) -> str:
        return json.dumps(self.seals, indent=2, sort_keys=True) + "\n"

    def _save_seals(self) -> None:
        if self.seals_path is not None:
            self.seals_path.parent.mkdir(parents=True, exist_ok=True)
            self.seals_path.write_text(self.seals_text(), encoding="utf-8")
