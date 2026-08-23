"""
metrics.py — single place that turns CaseOutcomes into headline numbers.

Senior rule:
- UI must NOT recompute these formulas.
- Harness / API return BatchMetrics; UI only displays them.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Optional, Sequence

from pydantic import BaseModel, Field

from eval.costing import compute_batch_costs
from eval.types import CaseOutcome, PlannedAction, SimCase


class BatchMetrics(BaseModel):
    """All money figures are in INR (rupees), not paise, for human readout."""

    label: str
    seed: int
    n: int
    at_risk_inr: float
    recovered_inr: float = Field(description="Gross recovered INR (before costs)")
    gross_recovered_inr: float = Field(description="Alias of recovered_inr")
    net_recovered_inr: float = Field(description="Gross minus all priced costs")
    recovery_rate: float = Field(description="gross recovered_inr / at_risk_inr")
    contacts: int
    retries: int
    recoveries: int
    contacts_per_recovery: float
    natural_recoveries: int = 0
    total_attempts: int = 0
    wasted_attempts: int = 0
    attempt_cost_inr: float = 0.0
    mdr_cost_inr: float = 0.0
    risk_cost_inr: float = 0.0
    customer_cost_inr: float = 0.0
    total_cost_inr: float = 0.0
    cost_per_rupee_recovered: float = Field(
        default=-1.0,
        description="total_cost / gross recovered; -1 if zero gross",
    )
    scheme_cap_breaches: int = 0
    forgone_recovery_inr: float = Field(
        default=0.0,
        description="Expected recovery refused on PROHIBITED (ours; compliance cost)",
    )

    def gross_delta_inr(self, other: "BatchMetrics") -> float:
        """Gross INR recovered by self minus other (positive => we beat them on gross)."""
        return self.gross_recovered_inr - other.gross_recovered_inr

    def net_delta_inr(self, other: "BatchMetrics") -> float:
        """Net INR recovered by self minus other (headline comparison)."""
        return self.net_recovered_inr - other.net_recovered_inr


def paise_to_inr(paise: int) -> float:
    return paise / 100.0


def compute_metrics(
    *,
    label: str,
    seed: int,
    cases: Sequence[SimCase],
    outcomes: Sequence[CaseOutcome],
    plan_fn: Optional[Callable[[SimCase], list[PlannedAction]]] = None,
) -> BatchMetrics:
    if len(cases) != len(outcomes):
        raise ValueError("cases and outcomes length mismatch")

    at_risk = sum(c.visible.amount_paise for c in cases)
    recovered = sum(o.recovered_paise for o in outcomes)
    contacts = sum(o.contacts for o in outcomes)
    retries = sum(o.retries for o in outcomes)
    recoveries = sum(1 for o in outcomes if o.recovered)
    natural = sum(1 for o in outcomes if o.natural)
    wasted = sum(o.wasted_attempts for o in outcomes)

    at_risk_inr = paise_to_inr(at_risk)
    recovered_inr = paise_to_inr(recovered)
    recovery_rate = (recovered_inr / at_risk_inr) if at_risk_inr else 0.0
    cpr = (contacts / recoveries) if recoveries else float("inf")

    attempt_cost = mdr_cost = risk_cost = customer_cost = total_cost = 0.0
    total_attempts = retries + contacts
    scheme_cap_breaches = 0
    forgone_recovery_inr = 0.0
    net_recovered_inr = recovered_inr

    if plan_fn is not None:
        costs = compute_batch_costs(cases, outcomes, plan_fn, label=label)
        attempt_cost = costs.attempt_cost_inr
        mdr_cost = costs.mdr_cost_inr
        risk_cost = costs.risk_cost_inr
        customer_cost = costs.customer_cost_inr
        total_cost = costs.total_cost_inr
        total_attempts = costs.total_attempts
        scheme_cap_breaches = costs.scheme_cap_breaches
        forgone_recovery_inr = costs.forgone_recovery_inr
        net_recovered_inr = round(recovered_inr - total_cost, 2)

    cost_per_rupee = (
        round(total_cost / recovered_inr, 6) if recovered_inr > 0 else -1.0
    )

    return BatchMetrics(
        label=label,
        seed=seed,
        n=len(cases),
        at_risk_inr=round(at_risk_inr, 2),
        recovered_inr=round(recovered_inr, 2),
        gross_recovered_inr=round(recovered_inr, 2),
        net_recovered_inr=net_recovered_inr,
        recovery_rate=round(recovery_rate, 6),
        contacts=contacts,
        retries=retries,
        recoveries=recoveries,
        contacts_per_recovery=round(cpr, 4) if recoveries else -1.0,
        natural_recoveries=natural,
        total_attempts=total_attempts,
        wasted_attempts=wasted,
        attempt_cost_inr=attempt_cost,
        mdr_cost_inr=mdr_cost,
        risk_cost_inr=risk_cost,
        customer_cost_inr=customer_cost,
        total_cost_inr=total_cost,
        cost_per_rupee_recovered=cost_per_rupee,
        scheme_cap_breaches=scheme_cap_breaches,
        forgone_recovery_inr=forgone_recovery_inr,
    )


def format_metrics(m: BatchMetrics) -> str:
    """Pretty console block for demos and CI logs."""
    cpr = (
        f"{m.contacts_per_recovery:.3f}"
        if m.contacts_per_recovery >= 0
        else "n/a"
    )
    cost_per = (
        f"{m.cost_per_rupee_recovered:.4f}"
        if m.cost_per_rupee_recovered >= 0
        else "n/a"
    )
    return "\n".join(
        [
            f"label              : {m.label}",
            f"seed / n           : {m.seed} / {m.n}",
            f"at_risk_inr        : {m.at_risk_inr:,.2f}",
            f"gross_recovered_inr: {m.gross_recovered_inr:,.2f}",
            f"net_recovered_inr  : {m.net_recovered_inr:,.2f}",
            f"total_cost_inr     : {m.total_cost_inr:,.2f}",
            f"cost_per_rupee     : {cost_per}",
            f"recovery_rate      : {m.recovery_rate:.4%}",
            f"wasted_attempts    : {m.wasted_attempts}",
            f"scheme_cap_breach  : {m.scheme_cap_breaches}",
            f"forgone_recovery   : {m.forgone_recovery_inr:,.2f}",
            f"contacts           : {m.contacts}",
            f"retries            : {m.retries}",
            f"recoveries         : {m.recoveries}",
            f"contacts/recovery  : {cpr}",
            f"natural_recoveries : {m.natural_recoveries}",
        ]
    )
