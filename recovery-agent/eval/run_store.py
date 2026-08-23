"""
eval/run_store.py — persist batch run results for GET /eval/runs/{id} + UI.

In-memory + optional JSON under data/eval_runs/ so refresh survives restarts
during a demo.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Optional
from uuid import uuid4

from pydantic import BaseModel, Field

from eval.metrics import BatchMetrics
from eval.segments import SegmentCompareRow

_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_DIR = _ROOT / "data" / "eval_runs"


class EvalRunRecord(BaseModel):
    run_id: str
    created_at: str
    seed: int
    n: int
    labels: list[str]
    metrics: list[BatchMetrics]
    gate_blocks: dict[str, int] = Field(default_factory=dict)
    decline_mix: dict[str, int] = Field(default_factory=dict)
    delta_ours_vs_b2_inr: Optional[float] = Field(
        default=None,
        description="Gross recovered INR delta (ours - b2)",
    )
    delta_net_ours_vs_b2_inr: Optional[float] = Field(
        default=None,
        description="Net recovered INR delta (ours - b2); headline winner",
    )
    segments: list[SegmentCompareRow] = Field(
        default_factory=list,
        description="Net/gross by recovery class (Task 5)",
    )
    cost_overrides: dict[str, float] = Field(
        default_factory=dict,
        description="Live assumption overrides applied for this run (Task 6)",
    )
    sample_case_ids: list[str] = Field(
        default_factory=list,
        description="Optional product case ids created for UI deep-links",
    )


class EvalRunStore:
    def __init__(self, directory: Optional[Path] = None) -> None:
        self.directory = Path(directory or os.getenv("EVAL_RUN_DIR", str(_DEFAULT_DIR)))
        self.directory.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._mem: dict[str, EvalRunRecord] = {}
        self._load_disk()

    def _load_disk(self) -> None:
        for path in self.directory.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                rec = EvalRunRecord.model_validate(data)
                self._mem[rec.run_id] = rec
            except Exception:
                continue

    def save(self, record: EvalRunRecord) -> EvalRunRecord:
        with self._lock:
            self._mem[record.run_id] = record
            path = self.directory / f"{record.run_id}.json"
            path.write_text(
                json.dumps(record.model_dump(mode="json"), indent=2),
                encoding="utf-8",
            )
        return record

    def get(self, run_id: str) -> Optional[EvalRunRecord]:
        with self._lock:
            return self._mem.get(run_id)

    def latest(self) -> Optional[EvalRunRecord]:
        with self._lock:
            if not self._mem:
                return None
            return max(self._mem.values(), key=lambda r: r.created_at)

    def list_runs(self, limit: int = 20) -> list[EvalRunRecord]:
        with self._lock:
            rows = sorted(self._mem.values(), key=lambda r: r.created_at, reverse=True)
            return rows[:limit]


_STORE: Optional[EvalRunStore] = None


def get_store() -> EvalRunStore:
    global _STORE
    if _STORE is None:
        _STORE = EvalRunStore()
    return _STORE


def new_run_id() -> str:
    return f"run_{uuid4().hex[:10]}"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
