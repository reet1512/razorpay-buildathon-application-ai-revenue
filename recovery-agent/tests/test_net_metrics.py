"""
tests/test_net_metrics.py — Task 3 net recovery arithmetic and renames.
"""

from __future__ import annotations

import pytest

from config.costs import clear_cost_overrides, set_cost_overrides
from eval.baselines import POLICIES, baseline_b2
from eval.batch import generate_batch
from eval.costing import compute_case_costs
from eval.metrics import BatchMetrics, compute_metrics
from eval.recovery_class import RecoveryClass, recovery_class_for
from eval.simulate import run_batch
from eval.types import (
    CaseOutcome,
    FailureReason,
    HiddenPayerTruth,
    SimCase,
    VisibleCase,
)


def _case(reason: FailureReason) -> SimCase:
    return SimCase(
        visible=VisibleCase(
            case_key="c1",
            payer_ref="p1",
            amount_paise=100000,
            rail="card",
            failure_reason=reason,
        ),
        hidden=HiddenPayerTruth(
            instrument_valid=reason
            not in {
                FailureReason.card_expired,
                FailureReason.token_invalid,
                FailureReason.mandate_revoked,
            },
            true_credit_day=5,
            natural_recovery_prob=0.01,
            base_contact_response_prob=0.2,
            retry_success_if_funded=0.05 if reason == FailureReason.risk_fraud else 0.8,
        ),
        failure_dom=5,
    )


def test_gross_delta_inr_rename():
    a = BatchMetrics(
        label="ours",
        seed=1,
        n=1,
        at_risk_inr=1000,
        recovered_inr=500,
        gross_recovered_inr=500,
        net_recovered_inr=450,
        recovery_rate=0.5,
        contacts=0,
        retries=0,
        recoveries=1,
        contacts_per_recovery=-1,
    )
    b = a.model_copy(update={"label": "b2", "gross_recovered_inr": 400, "net_recovered_inr": 380, "recovered_inr": 400})
    assert a.gross_delta_inr(b) == pytest.approx(100)
    assert a.net_delta_inr(b) == pytest.approx(70)


def test_net_recovered_equals_gross_minus_costs():
    clear_cost_overrides()
    try:
        set_cost_overrides({"attempt.sms_dlt": 1.0, "success.mdr_pct": 0.1})
        seed, n = 42, 80
        cases = generate_batch(seed=seed, n=n)
        outcomes = run_batch(seed=seed, cases=cases, plan_fn=baseline_b2)
        m = compute_metrics(
            label="b2",
            seed=seed,
            cases=cases,
            outcomes=outcomes,
            plan_fn=baseline_b2,
        )
        assert m.net_recovered_inr == pytest.approx(
            m.gross_recovered_inr - m.total_cost_inr, abs=0.02
        )
        assert m.total_cost_inr == pytest.approx(
            m.attempt_cost_inr + m.mdr_cost_inr + m.risk_cost_inr + m.customer_cost_inr,
            abs=0.02,
        )
    finally:
        clear_cost_overrides()


def test_wasted_attempts_increase_b2_attempt_cost_on_expired():
    case = _case(FailureReason.card_expired)
    plan = baseline_b2(case)
    outcome = CaseOutcome(
        case_key="c1",
        recovered=False,
        recovered_paise=0,
        contacts=1,
        retries=3,
        wasted_attempts=3,
    )
    row = compute_case_costs(case, outcome, lambda _: plan, label="b2")
    assert row.attempt_cost_inr > 0
    assert recovery_class_for(FailureReason.card_expired) == RecoveryClass.CUSTOMER_ACTION


def test_forgone_recovery_only_for_ours_prohibited():
    case = _case(FailureReason.risk_fraud)
    outcome = CaseOutcome(
        case_key="c1",
        recovered=False,
        recovered_paise=0,
        contacts=0,
        retries=0,
        wasted_attempts=0,
    )
    ours_row = compute_case_costs(case, outcome, POLICIES["ours"], label="ours")
    b2_row = compute_case_costs(case, outcome, baseline_b2, label="b2")
    assert ours_row.forgone_recovery_inr > 0
    assert b2_row.forgone_recovery_inr == 0


def test_cost_per_rupee_recovered():
    m = BatchMetrics(
        label="x",
        seed=1,
        n=10,
        at_risk_inr=10000,
        recovered_inr=1000,
        gross_recovered_inr=1000,
        net_recovered_inr=900,
        recovery_rate=0.1,
        contacts=5,
        retries=10,
        recoveries=2,
        contacts_per_recovery=2.5,
        total_cost_inr=100,
        cost_per_rupee_recovered=0.1,
    )
    assert m.cost_per_rupee_recovered == pytest.approx(0.1)


def test_compare_seed_winner_uses_net():
    from eval.benchmark import compare_seed

    result = compare_seed(42, 100)
    assert result.winner == (
        "ours"
        if result.delta_net_recovered_inr > 0.005
        else "b2"
        if result.delta_net_recovered_inr < -0.005
        else "tie"
    )
