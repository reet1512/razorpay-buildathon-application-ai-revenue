"""
Local manifest for Inherent document idempotency and corpus tracking.

Maps logical episode identity -> Inherent document_id + ingestion status.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from memory.constants import CORPUS_VERSION, DATA_SOURCE, SIMULATION_VERSION

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST_PATH = ROOT / "artifacts" / "payment_memory_manifest.json"


def _git_commit() -> Optional[str]:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if out.returncode == 0:
            return out.stdout.strip() or None
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


class MemoryManifest:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or DEFAULT_MANIFEST_PATH
        self.data: dict[str, Any] = self._empty()
        if self.path.exists():
            self.load()

    @staticmethod
    def _empty() -> dict[str, Any]:
        return {
            "corpus_version": CORPUS_VERSION,
            "data_source": DATA_SOURCE,
            "simulation_version": SIMULATION_VERSION,
            "seeds": [],
            "cases_per_seed": 0,
            "expected_episodes": 0,
            "uploaded": 0,
            "completed": 0,
            "processing": 0,
            "failed": 0,
            "skipped": 0,
            "retry_exhausted": 0,
            "created_at": None,
            "updated_at": None,
            "seeder_commit": None,
            "episodes": {},
            "metrics": {},
        }

    def load(self) -> None:
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            self.data.update(raw)
            if "episodes" not in self.data or not isinstance(self.data["episodes"], dict):
                self.data["episodes"] = {}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data["updated_at"] = datetime.now(timezone.utc).isoformat()
        self.path.write_text(
            json.dumps(self.data, indent=2, sort_keys=False) + "\n",
            encoding="utf-8",
        )

    def init_run(
        self,
        *,
        seeds: list[int],
        cases_per_seed: int,
        force: bool = False,
    ) -> None:
        if force or not self.data.get("created_at"):
            self.data = self._empty()
            self.data["created_at"] = datetime.now(timezone.utc).isoformat()
            self.data["seeder_commit"] = _git_commit()
        self.data["seeds"] = seeds
        self.data["cases_per_seed"] = cases_per_seed
        self.data["expected_episodes"] = len(seeds) * cases_per_seed

    def get_episode(self, logical_id: str) -> Optional[dict[str, Any]]:
        ep = self.data.get("episodes", {}).get(logical_id)
        return ep if isinstance(ep, dict) else None

    def record_episode(
        self,
        logical_id: str,
        *,
        seed: int,
        case_id: str,
        document_id: Optional[str] = None,
        document_name: Optional[str] = None,
        status: str,
        error: Optional[str] = None,
    ) -> None:
        episodes = self.data.setdefault("episodes", {})
        existing = episodes.get(logical_id, {})
        row = {
            **existing,
            "logical_id": logical_id,
            "seed": seed,
            "case_id": case_id,
            "simulation_version": SIMULATION_VERSION,
            "status": status,
        }
        if document_id:
            row["document_id"] = document_id
        if document_name:
            row["document_name"] = document_name
        if error:
            row["error"] = error
        episodes[logical_id] = row
        self._recompute_counts()

    def _recompute_counts(self) -> None:
        episodes = self.data.get("episodes", {})
        uploaded = completed = processing = failed = skipped = retry_exhausted = 0
        for row in episodes.values():
            if not isinstance(row, dict):
                continue
            st = str(row.get("status", "")).lower()
            if st in {"skipped"}:
                skipped += 1
            elif st in {"completed", "processed"}:
                completed += 1
                uploaded += 1
            elif st in {"uploaded", "pending", "processing"}:
                processing += 1
                uploaded += 1
            elif st in {"failed", "error"}:
                failed += 1
                uploaded += 1
            elif st in {"retry_exhausted"}:
                retry_exhausted += 1
            elif st in {"uploaded_ok"}:
                uploaded += 1
        self.data["uploaded"] = uploaded
        self.data["completed"] = completed
        self.data["processing"] = processing
        self.data["failed"] = failed
        self.data["skipped"] = skipped
        self.data["retry_exhausted"] = retry_exhausted

    def set_metrics(self, metrics: dict[str, Any]) -> None:
        self.data["metrics"] = metrics

    def should_skip(self, logical_id: str, *, resume: bool) -> bool:
        if not resume:
            return False
        row = self.get_episode(logical_id)
        if not row:
            return False
        return str(row.get("status", "")).lower() in {
            "completed",
            "processed",
            "skipped",
        }
