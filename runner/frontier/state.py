"""Delivery state: work/<id>/state.yaml. The runner's (and the orchestrator's) memory."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class State:
    def __init__(self, path: Path, data: dict[str, Any]):
        self.path = path
        self.data = data

    @classmethod
    def load(cls, work_dir: Path, *, work_item: str, work_id: str, kind: str = "delivery") -> "State":
        path = work_dir / "state.yaml"
        if path.is_file():
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        else:
            data = {}
        data.setdefault("work_item", work_item)
        data.setdefault("work_id", work_id)
        data.setdefault("kind", kind)
        data.setdefault("stage", "new")
        data.setdefault("counters", {})
        data.setdefault("gates", {})
        data.setdefault("history", [])
        return cls(path, data)

    @classmethod
    def read(cls, work_dir: Path) -> "State":
        path = work_dir / "state.yaml"
        if not path.is_file():
            raise FileNotFoundError(f"no delivery state at {path}")
        return cls(path, yaml.safe_load(path.read_text(encoding="utf-8")))

    # ---- accessors ---------------------------------------------------------
    @property
    def stage(self) -> str:
        return self.data["stage"]

    @property
    def work_item(self) -> str:
        return self.data["work_item"]

    def gate(self, name: str) -> dict:
        return self.data["gates"].setdefault(name, {})

    def bump(self, counter: str) -> int:
        self.data["counters"][counter] = self.data["counters"].get(counter, 0) + 1
        return self.data["counters"][counter]

    def count(self, counter: str) -> int:
        return self.data["counters"].get(counter, 0)

    def move(self, stage: str, note: str = "", **extra: Any) -> None:
        self.data["stage"] = stage
        entry = {"at": now(), "stage": stage}
        if note:
            entry["note"] = note
        entry.update(extra)
        self.data["history"].append(entry)

    def escalate(self, stage: str, attempted: str, blocking: str, question: str, options: list[str] | None = None) -> dict:
        esc = {"stage": stage, "attempted": attempted, "blocking": blocking, "question": question}
        if options:
            esc["options"] = options
        self.data["escalation"] = esc
        self.data["resume_stage"] = stage
        self.move("escalate", blocking)
        return esc

    def clear_escalation(self) -> None:
        self.data.pop("escalation", None)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(yaml.safe_dump(self.data, sort_keys=False, allow_unicode=True), encoding="utf-8")
