"""
eval/costing.py — priced batch economics from sim outcomes + config/costs.json.

All rates come from config.costs.get_cost_value(); no hardcoded fees here.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Sequence

from config.costs import get_cost_value
from eval.baselines import baseline_b2
from eval.payer_model import is_contact_verb, is_retry_verb
from eval.recovery_class import RecoveryClass, recovery_class_for
from eval.types import CaseOutcome, PlannedAction, SimCase, SimVerb


@dataclass(frozen=True)
class CaseCostBreakdown:
    attempt_cost_inr: float
    mdr_cost_inr: float
    risk_cost_inr: float
    customer_cost_inr: float
    scheme_cap_breach: bool
    forgone_recovery_inr: float


@dataclass(frozen=True)
class BatchCostTotals:
    attempt_cost_inr: float
    mdr_cost_inr: float
    risk_cost_inr: float
    customer_cost_inr: float
    total_cost_inr: float
    wasted_attempts: int
    total_attempts: int
    scheme_cap_breaches: int
    forgone_recovery_inr: float


def paise_to_inr(paise: int) -> float:
    return paise / 100.0


def _executed_actions(
    case: SimCase,
    outcome: CaseOutcome,
    plan_fn: Callable[[SimCase], list[PlannedAction]],
) -> list[PlannedAction]:
    """Actions actually played, in plan order (matches simulate stop rules)."""
    planned = sorted(plan_fn(case), key=lambda a: a.day_offset)
    retries_left = outcome.retries
    contacts_left = outcome.contacts
    executed: list[PlannedAction] = []
    for action in planned:
        if is_retry_verb(action.verb) and retries_left > 0:
            executed.append(action)
            retries_left -= 1
        elif is_contact_verb(action.verb) and contacts_left > 0:
            executed.append(action)
            contacts_left -= 1
        if retries_left == 0 and contacts_left == 0:
            break
    return executed


def _contact_unit_cost(verb: SimVerb) -> float:
    if verb == SimVerb.generic_nag:
        return get_cost_value("attempt.sms_dlt")
    if verb == SimVerb.send_payment_link:
        return get_cost_value("attempt.whatsapp_utility")
    return get_cost_value("attempt.email")


def _is_inappropriate_contact(case: SimCase, action: PlannedAction) -> bool:
    rc = recovery_class_for(case.visible.failure_reason)
    if rc == RecoveryClass.PROHIBITED:
        return True
    if rc == RecoveryClass.CUSTOMER_ACTION and action.verb == SimVerb.generic_nag:
        return True
    return False


def _forgone_prohibited_inr(
    case: SimCase,
    outcome: CaseOutcome,
    *,
    label: str,
) -> float:
    """
    Expected recovery given up by refusing PROHIBITED automation (ours only).

    Uses hidden retry_success_if_funded × B2 retry slots not taken.
    """
    if label != "ours":
        return 0.0
    if recovery_class_for(case.visible.failure_reason) != RecoveryClass.PROHIBITED:
        return 0.0
    if outcome.recovered:
        return 0.0

    b2_retries = sum(
        1 for a in baseline_b2(case) if is_retry_verb(a.verb)
    )
    refused = max(0, b2_retries - outcome.retries)
    if refused == 0:
        return 0.0

    amount_inr = paise_to_inr(case.visible.amount_paise)
    p = case.hidden.retry_success_if_funded
    # Expected value of refused independent retry slots (linear approx for demo).
    return round(amount_inr * p * refused, 4)


def compute_case_costs(
    case: SimCase,
    outcome: CaseOutcome,
    plan_fn: Callable[[SimCase], list[PlannedAction]],
    *,
    label: str,
) -> CaseCostBreakdown:
    executed = _executed_actions(case, outcome, plan_fn)
    scheme_cap = int(get_cost_value("scheme_limits.max_attempts_per_transaction_30d"))
    psp_fee = get_cost_value("attempt.psp_fee_on_failed_attempt")
    excess_penalty = get_cost_value("attempt.network_excess_retry_penalty")
    mdr_pct = get_cost_value("success.mdr_pct")
    chargeback_fee = get_cost_value("risk.chargeback_fee")
    support_ticket = get_cost_value("risk.support_ticket")
    decay_pct = get_cost_value("risk.issuer_auth_decay_pct_per_excess_attempt")
    churn_prob = get_cost_value("customer.churn_prob_per_inappropriate_contact")
    ltv = get_cost_value("customer.ltv")

    attempt_cost = 0.0
    risk_cost = 0.0
    customer_cost = 0.0
    retry_index = 0

    for action in executed:
        if is_retry_verb(action.verb):
            retry_index += 1
            attempt_cost += psp_fee
            if retry_index > scheme_cap:
                attempt_cost += excess_penalty
                amount_inr = paise_to_inr(case.visible.amount_paise)
                risk_cost += amount_inr * decay_pct
        elif is_contact_verb(action.verb):
            attempt_cost += _contact_unit_cost(action.verb)
            if _is_inappropriate_contact(case, action):
                customer_cost += churn_prob * ltv
                if recovery_class_for(case.visible.failure_reason) == RecoveryClass.PROHIBITED:
                    risk_cost += support_ticket
                    # Modelled chargeback exposure on risky contact (ASSUMPTION).
                    risk_cost += churn_prob * chargeback_fee

    gross_inr = paise_to_inr(outcome.recovered_paise)
    mdr_cost = gross_inr * mdr_pct
    scheme_cap_breach = outcome.retries > scheme_cap
    forgone = _forgone_prohibited_inr(case, outcome, label=label)

    return CaseCostBreakdown(
        attempt_cost_inr=round(attempt_cost, 4),
        mdr_cost_inr=round(mdr_cost, 4),
        risk_cost_inr=round(risk_cost, 4),
        customer_cost_inr=round(customer_cost, 4),
        scheme_cap_breach=scheme_cap_breach,
        forgone_recovery_inr=forgone,
    )


def compute_batch_costs(
    cases: Sequence[SimCase],
    outcomes: Sequence[CaseOutcome],
    plan_fn: Callable[[SimCase], list[PlannedAction]],
    *,
    label: str,
) -> BatchCostTotals:
    if len(cases) != len(outcomes):
        raise ValueError("cases and outcomes length mismatch")

    attempt = mdr = risk = customer = 0.0
    wasted = 0
    total_attempts = 0
    cap_breaches = 0
    forgone = 0.0

    for case, outcome in zip(cases, outcomes, strict=True):
        row = compute_case_costs(case, outcome, plan_fn, label=label)
        attempt += row.attempt_cost_inr
        mdr += row.mdr_cost_inr
        risk += row.risk_cost_inr
        customer += row.customer_cost_inr
        wasted += outcome.wasted_attempts
        total_attempts += outcome.retries + outcome.contacts
        if row.scheme_cap_breach:
            cap_breaches += 1
        forgone += row.forgone_recovery_inr

    total = attempt + mdr + risk + customer
    return BatchCostTotals(
        attempt_cost_inr=round(attempt, 2),
        mdr_cost_inr=round(mdr, 2),
        risk_cost_inr=round(risk, 2),
        customer_cost_inr=round(customer, 2),
        total_cost_inr=round(total, 2),
        wasted_attempts=wasted,
        total_attempts=total_attempts,
        scheme_cap_breaches=cap_breaches,
        forgone_recovery_inr=round(forgone, 2),
    )
