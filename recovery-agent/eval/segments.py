"""
eval/segments.py — net/gross breakdown by recovery class (Task 5).
"""

from __future__ import annotations

from collections import defaultdict
from typing import Sequence

from pydantic import BaseModel, Field

from eval.baselines import POLICIES
from eval.metrics import compute_metrics
from eval.recovery_class import RecoveryClass, recovery_class_for
from eval.types import CaseOutcome, SimCase

_CLASS_ORDER = (
    RecoveryClass.RETRY_FIXABLE,
    RecoveryClass.CUSTOMER_ACTION,
    RecoveryClass.AMBIGUOUS,
    RecoveryClass.PROHIBITED,
)


class PolicySegmentRow(BaseModel):
    label: str
    recovery_class: str
    n_cases: int
    at_risk_inr: float
    gross_recovered_inr: float
    net_recovered_inr: float
    retries: int
    contacts: int
    wasted_attempts: int
    recoveries: int
    total_cost_inr: float = 0.0


class SegmentCompareRow(BaseModel):
    recovery_class: str
    n_cases: int
    ours: PolicySegmentRow
    b2: PolicySegmentRow
    delta_net_inr: float
    delta_gross_inr: float
    b2_zero_recovery_with_spend: bool = Field(
        description="B2 spent retries/contacts but recovered nothing in this class",
    )


def compute_policy_segments(
    *,
    label: str,
    cases: Sequence[SimCase],
    outcomes: Sequence[CaseOutcome],
    plan_fn,
    seed: int = 0,
) -> list[PolicySegmentRow]:
    buckets: dict[RecoveryClass, list[tuple[SimCase, CaseOutcome]]] = defaultdict(list)
    for case, outcome in zip(cases, outcomes, strict=True):
        rc = recovery_class_for(case.visible.failure_reason)
        buckets[rc].append((case, outcome))

    rows: list[PolicySegmentRow] = []
    for rc in _CLASS_ORDER:
        group = buckets.get(rc, [])
        if not group:
            continue
        sub_cases = [c for c, _ in group]
        sub_outcomes = [o for _, o in group]
        m = compute_metrics(
            label=label,
            seed=seed,
            cases=sub_cases,
            outcomes=sub_outcomes,
            plan_fn=plan_fn,
        )
        rows.append(
            PolicySegmentRow(
                label=label,
                recovery_class=rc.value,
                n_cases=len(group),
                at_risk_inr=m.at_risk_inr,
                gross_recovered_inr=m.gross_recovered_inr,
                net_recovered_inr=m.net_recovered_inr,
                retries=m.retries,
                contacts=m.contacts,
                wasted_attempts=m.wasted_attempts,
                recoveries=m.recoveries,
                total_cost_inr=m.total_cost_inr,
            )
        )
    return rows


def compute_segment_compare(
    *,
    cases: Sequence[SimCase],
    ours_outcomes: Sequence[CaseOutcome],
    b2_outcomes: Sequence[CaseOutcome],
    seed: int = 42,
) -> list[SegmentCompareRow]:
    ours_rows = {
        r.recovery_class: r
        for r in compute_policy_segments(
            label="ours",
            cases=cases,
            outcomes=ours_outcomes,
            plan_fn=POLICIES["ours"],
            seed=seed,
        )
    }
    b2_rows = {
        r.recovery_class: r
        for r in compute_policy_segments(
            label="b2",
            cases=cases,
            outcomes=b2_outcomes,
            plan_fn=POLICIES["b2"],
            seed=seed,
        )
    }
    out: list[SegmentCompareRow] = []
    for rc in _CLASS_ORDER:
        key = rc.value
        if key not in ours_rows and key not in b2_rows:
            continue
        ours = ours_rows.get(key)
        b2 = b2_rows.get(key)
        if ours is None or b2 is None:
            continue
        b2_spent = b2.retries + b2.contacts > 0
        out.append(
            SegmentCompareRow(
                recovery_class=key,
                n_cases=ours.n_cases,
                ours=ours,
                b2=b2,
                delta_net_inr=round(ours.net_recovered_inr - b2.net_recovered_inr, 2),
                delta_gross_inr=round(ours.gross_recovered_inr - b2.gross_recovered_inr, 2),
                b2_zero_recovery_with_spend=b2_spent and b2.recoveries == 0,
            )
        )
    return out
