"""
tests/test_recovery_class.py — Task 2 recovery class invariants.
"""

from __future__ import annotations

import random


from eval.baselines import baseline_b2
from eval.batch import generate_batch
from eval.payer_model import sample_hidden_truth, try_retry
from eval.recovery_class import (
    FAILURE_TO_RECOVERY_CLASS,
    RecoveryClass,
    recovery_class_for,
    retry_probability_is_structurally_zero,
)
from eval.simulate import run_case
from eval.types import (
    FailureReason,
    HiddenPayerTruth,
    PlannedAction,
    SimCase,
    SimVerb,
    VisibleCase,
)


def test_failure_to_class_mapping():
    assert recovery_class_for(FailureReason.insufficient_funds) == RecoveryClass.RETRY_FIXABLE
    assert recovery_class_for(FailureReason.card_expired) == RecoveryClass.CUSTOMER_ACTION
    assert recovery_class_for(FailureReason.do_not_honour) == RecoveryClass.AMBIGUOUS
    assert recovery_class_for(FailureReason.risk_fraud) == RecoveryClass.PROHIBITED
    assert len(FAILURE_TO_RECOVERY_CLASS) == len(FailureReason)


def test_only_customer_action_is_structurally_zero():
    for reason in FailureReason:
        expected = reason in {
            FailureReason.card_expired,
            FailureReason.token_invalid,
            FailureReason.mandate_revoked,
        }
        assert retry_probability_is_structurally_zero(reason) is expected


def _sim_case(reason: FailureReason, hidden: HiddenPayerTruth | None = None) -> SimCase:
    rng = random.Random(0)
    h = hidden or sample_hidden_truth(rng, reason)
    return SimCase(
        visible=VisibleCase(
            case_key="test_case",
            payer_ref="payer_test",
            amount_paise=49900,
            rail="card",
            failure_reason=reason,
        ),
        hidden=h,
        failure_dom=15,
    )


def test_customer_action_retry_always_fails():
    """1000 retries on dead instrument => zero retry recoveries."""
    case = _sim_case(FailureReason.card_expired)
    rng = random.Random(99)

    for _ in range(1000):
        assert try_retry(rng, case, day_offset=0) is False


def test_prohibited_retry_can_succeed_in_payer_model():
    """PROHIBITED keeps nonzero retry_success_if_funded — gates block in Task 7."""
    case = _sim_case(
        FailureReason.risk_fraud,
        HiddenPayerTruth(
            instrument_valid=True,
            true_credit_day=3,
            natural_recovery_prob=0.01,
            base_contact_response_prob=0.05,
            retry_success_if_funded=0.05,
        ),
    )
    rng = random.Random(0)
    # Force success path: rng.random() < 0.05
    rng.random = lambda: 0.01  # type: ignore[method-assign]
    assert try_retry(rng, case, day_offset=0) is True


def test_ambiguous_retry_not_structurally_zero():
    case = _sim_case(FailureReason.do_not_honour)
    # Align failure day with salary window so retry is not blocked by funding model.
    case.failure_dom = case.hidden.true_credit_day
    rng = random.Random(1)
    rng.random = lambda: 0.01  # type: ignore[method-assign]
    assert try_retry(rng, case, day_offset=0) is True


def test_wasted_attempts_count_customer_action_retries_only():
    case = _sim_case(FailureReason.card_expired)

    def only_retries(_c: SimCase) -> list[PlannedAction]:
        return [
            PlannedAction(verb=SimVerb.schedule_retry, day_offset=d, note=f"r{d}")
            for d in range(5)
        ]

    out = run_case(random.Random(7), case, only_retries)
    assert out.recovered is False
    assert out.retries == 5
    assert out.wasted_attempts == 5
    assert out.contacts == 0


def test_b2_accumulates_wasted_retries_on_expired_cards():
    cases = generate_batch(seed=11, n=300)
    expired = [c for c in cases if c.visible.failure_reason == FailureReason.card_expired]
    assert expired

    for case in expired:
        out = run_case(random.Random(f"b2:{case.visible.case_key}"), case, baseline_b2)
        assert 1 <= out.wasted_attempts <= 3
        if not out.recovered:
            assert out.wasted_attempts == 3


def test_contact_on_customer_action_not_counted_as_wasted():
    case = _sim_case(FailureReason.card_expired)

    def contact_only(_c: SimCase) -> list[PlannedAction]:
        return [PlannedAction(verb=SimVerb.send_payment_link, day_offset=0)]

    out = run_case(random.Random(3), case, contact_only)
    assert out.wasted_attempts == 0
    assert out.contacts == 1
