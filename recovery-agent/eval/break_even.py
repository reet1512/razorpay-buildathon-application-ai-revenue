"""
eval/break_even.py — find cost assumption where Ours net ≈ B2 net (Task 6).
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from config.costs import clear_cost_overrides, get_cost_value, set_cost_overrides
from eval.benchmark import compare_seed

BreakEvenParam = Literal[
    "attempt.sms_dlt",
    "attempt.whatsapp_utility",
    "customer.churn_prob_per_inappropriate_contact",
]


class BreakEvenResult(BaseModel):
    param_key: BreakEvenParam
    default_value: float
    break_even_value: Optional[float] = Field(
        description="Cost value where net delta (ours - b2) crosses zero; None if no cross",
    )
    delta_net_at_default: float
    direction: str = Field(
        description="Whether raising the param helps ours or b2",
    )
    seed: int
    n: int
    note: str


def _net_delta_with_override(
    seed: int,
    n: int,
    param_key: str,
    value: float,
) -> float:
    set_cost_overrides({param_key: value})
    try:
        pair = compare_seed(seed, n)
        return pair.delta_net_recovered_inr
    finally:
        clear_cost_overrides()


def solve_break_even(
    *,
    seed: int = 42,
    n: int = 200,
    param_key: BreakEvenParam = "attempt.sms_dlt",
    lo: float = 0.0,
    hi: float = 50.0,
    tol: float = 0.05,
    max_iter: int = 40,
) -> BreakEvenResult:
    """
    Binary-search break-even for one cost knob.

    Primary demo knob: SMS cost — B2 fires generic_nag (SMS) on every failure;
    ours contacts less, so higher SMS cost widens our net advantage.
    """
    default = get_cost_value(param_key)
    delta_default = _net_delta_with_override(seed, n, param_key, default)

    delta_lo = _net_delta_with_override(seed, n, param_key, lo)
    delta_hi = _net_delta_with_override(seed, n, param_key, hi)

    direction = (
        "Raising this cost hurts B2 more than Ours (our net lead grows)."
        if delta_hi >= delta_lo
        else "Raising this cost hurts Ours more than B2."
    )

    # Need opposite signs at bounds for a crossing.
    if delta_lo * delta_hi > 0:
        return BreakEvenResult(
            param_key=param_key,
            default_value=default,
            break_even_value=None,
            delta_net_at_default=round(delta_default, 2),
            direction=direction,
            seed=seed,
            n=n,
            note=(
                f"No zero-crossing on [{lo}, {hi}]. "
                f"Delta at lo={delta_lo:.2f}, hi={delta_hi:.2f}."
            ),
        )

    left, right = lo, hi
    for _ in range(max_iter):
        mid = (left + right) / 2.0
        delta_mid = _net_delta_with_override(seed, n, param_key, mid)
        if abs(delta_mid) <= tol:
            return BreakEvenResult(
                param_key=param_key,
                default_value=default,
                break_even_value=round(mid, 4),
                delta_net_at_default=round(delta_default, 2),
                direction=direction,
                seed=seed,
                n=n,
                note=f"Net delta within ₹{tol} of zero at this {param_key}.",
            )
        if delta_lo * delta_mid <= 0:
            right = mid
            delta_hi = delta_mid
        else:
            left = mid
            delta_lo = delta_mid

    mid = (left + right) / 2.0
    return BreakEvenResult(
        param_key=param_key,
        default_value=default,
        break_even_value=round(mid, 4),
        delta_net_at_default=round(delta_default, 2),
        direction=direction,
        seed=seed,
        n=n,
        note="Approximate break-even from binary search.",
    )
