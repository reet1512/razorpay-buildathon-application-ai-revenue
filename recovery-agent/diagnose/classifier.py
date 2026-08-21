"""
classifier.py — map raw decline text/codes -> taxonomy class.

Teaching:
- Input looks like Razorpay error.reason / error.code.
- Output is a class name that MUST exist in taxonomy.yaml (or 'ambiguous').
- Unknown reasons do NOT invent a class — they become 'ambiguous'
  so Phase 5 AI / human escalation can take over safely.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURE = ROOT / "fixtures" / "decline_codes.json"


@dataclass(frozen=True)
class Classification:
    """Result of rules classification."""

    failure_class: str
    matched_on: str  # "reason" | "code" | "ambiguous"
    raw_reason: str
    raw_code: str
    confidence: float  # 1.0 for fixture hit, 0.0 for ambiguous


def _load_fixture(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


class Classifier:
    """
    Deterministic mapper.

    Keep this boring. Cleverness belongs in taxonomy + (later) AI, not here.
    """

    def __init__(self, fixture_path: Path | None = None) -> None:
        data = _load_fixture(fixture_path or DEFAULT_FIXTURE)
        self.by_reason: dict[str, str] = {
            k.lower(): v for k, v in (data.get("by_reason") or {}).items()
        }
        self.by_code: dict[str, Optional[str]] = {
            k.upper(): v for k, v in (data.get("by_code") or {}).items()
        }

    def classify(self, raw_reason: str, raw_code: str = "") -> Classification:
        reason = (raw_reason or "").strip().lower()
        code = (raw_code or "").strip().upper()

        if reason and reason in self.by_reason:
            return Classification(
                failure_class=self.by_reason[reason],
                matched_on="reason",
                raw_reason=raw_reason,
                raw_code=raw_code,
                confidence=1.0,
            )

        if code and code in self.by_code and self.by_code[code]:
            return Classification(
                failure_class=str(self.by_code[code]),
                matched_on="code",
                raw_reason=raw_reason,
                raw_code=raw_code,
                confidence=0.8,
            )

        return Classification(
            failure_class="ambiguous",
            matched_on="ambiguous",
            raw_reason=raw_reason,
            raw_code=raw_code,
            confidence=0.0,
        )


# Module-level helper for simple call sites.
_default = Classifier()


def classify(raw_reason: str, raw_code: str = "") -> Classification:
    return _default.classify(raw_reason, raw_code)
