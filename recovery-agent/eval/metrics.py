"""
metrics.py — single place that turns CaseOutcomes into headline numbers.

Senior rule:
- UI must NOT recompute these formulas.
- Harness / API return BatchMetrics; UI only displays them.
"""

from __future__ import annotations

from typing import Sequence

from pydantic import BaseModel, Field

from eval.types import CaseOutcome, SimCase


class BatchMetrics(BaseModel):
    """All money figures are in INR (rupees), not paise, for human readout."""

    label: str
    seed: int
    n: int
    at_risk_inr: float
    recovered_inr: float
    recovery_rate: float = Field(description="recovered_inr / at_risk_inr")
    contacts: int
    retries: int
    recoveries: int
    contacts_per_recovery: float
    natural_recoveries: int = 0

    def net_vs(self, other: "BatchMetrics") -> float:
        """INR recovered by self minus other (positive => we beat them)."""
        return self.recovered_inr - other.recovered_inr


def paise_to_inr(paise: int) -> float:
    return paise / 100.0


def compute_metrics(
    *,
    label: str,
    seed: int,
    cases: Sequence[SimCase],
    outcomes: Sequence[CaseOutcome],
) -> BatchMetrics:
    if len(cases) != len(outcomes):
        raise ValueError("cases and outcomes length mismatch")

    at_risk = sum(c.visible.amount_paise for c in cases)
    recovered = sum(o.recovered_paise for o in outcomes)
    contacts = sum(o.contacts for o in outcomes)
    retries = sum(o.retries for o in outcomes)
    recoveries = sum(1 for o in outcomes if o.recovered)
    natural = sum(1 for o in outcomes if o.natural)

    at_risk_inr = paise_to_inr(at_risk)
    recovered_inr = paise_to_inr(recovered)
    recovery_rate = (recovered_inr / at_risk_inr) if at_risk_inr else 0.0
    cpr = (contacts / recoveries) if recoveries else float("inf")

    return BatchMetrics(
        label=label,
        seed=seed,
        n=len(cases),
        at_risk_inr=round(at_risk_inr, 2),
        recovered_inr=round(recovered_inr, 2),
        recovery_rate=round(recovery_rate, 6),
        contacts=contacts,
        retries=retries,
        recoveries=recoveries,
        contacts_per_recovery=round(cpr, 4) if recoveries else -1.0,
        natural_recoveries=natural,
    )


def format_metrics(m: BatchMetrics) -> str:
    """Pretty console block for demos and CI logs."""
    cpr = (
        f"{m.contacts_per_recovery:.3f}"
        if m.contacts_per_recovery >= 0
        else "n/a"
    )
    return "\n".join(
        [
            f"label              : {m.label}",
            f"seed / n           : {m.seed} / {m.n}",
            f"at_risk_inr        : {m.at_risk_inr:,.2f}",
            f"recovered_inr      : {m.recovered_inr:,.2f}",
            f"recovery_rate      : {m.recovery_rate:.4%}",
            f"contacts           : {m.contacts}",
            f"retries            : {m.retries}",
            f"recoveries         : {m.recoveries}",
            f"contacts/recovery  : {cpr}",
            f"natural_recoveries : {m.natural_recoveries}",
        ]
    )
