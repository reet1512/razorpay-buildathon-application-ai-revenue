"""
scoring.py — deterministic recoverability score (0..1).

Teaching:
- Score answers: "how hard should we try?"
- It does NOT pick the verb (taxonomy does).
- Keep it explainable: a judge should be able to ask "why 0.7?" and get terms.
"""

from __future__ import annotations

from typing import Any, Mapping


def recoverability_score(
    *,
    category: str,
    amount_paise: int,
    contacts_used: int = 0,
    tenure_days: int = 0,
    scoring_cfg: Mapping[str, Any],
) -> float:
    """
    score = base(category)
          + value_weight (capped)
          + tenure_bonus (capped)
          - fatigue_penalty
    clipped to [0, 1]
    """
    base_map = scoring_cfg.get("base_by_category") or {}
    base = float(base_map.get(category, 0.4))

    inr = amount_paise / 100.0
    per_1000 = float(scoring_cfg.get("value_weight_per_1000_inr", 0.02))
    value_cap = float(scoring_cfg.get("value_weight_cap", 0.10))
    value_weight = min(value_cap, (inr / 1000.0) * per_1000)

    tenure_per = float(scoring_cfg.get("tenure_bonus_per_365_days", 0.03))
    tenure_cap = float(scoring_cfg.get("tenure_bonus_cap", 0.06))
    tenure_bonus = min(tenure_cap, (tenure_days / 365.0) * tenure_per)

    fatigue = float(scoring_cfg.get("fatigue_penalty_per_contact", 0.08)) * max(
        0, contacts_used
    )

    raw = base + value_weight + tenure_bonus - fatigue
    return round(min(1.0, max(0.0, raw)), 4)


def effort_band(score: float, bands_cfg: Mapping[str, Any]) -> str:
    """Pick low/medium/high from taxonomy effort_bands."""
    # Sort by min_score descending so highest matching band wins.
    items = []
    for name, cfg in (bands_cfg or {}).items():
        items.append((float(cfg.get("min_score", 0.0)), name))
    items.sort(reverse=True)
    for min_score, name in items:
        if score >= min_score:
            return name
    return "low"
