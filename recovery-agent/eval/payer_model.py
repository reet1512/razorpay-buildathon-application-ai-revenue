"""
payer_model.py — hidden truth + outcome dice rolls.

Teaching analogy:
- Imagine each customer has a private bank life you cannot see.
- The simulator peeks at that private life to decide if a retry/link worked.
- Your policy only sees failure_reason + coarse hints — like production.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from eval.types import FailureReason, HiddenPayerTruth, PlannedAction, SimCase, SimVerb


@dataclass
class FatigueState:
    """Tracks how many times we have already contacted this payer."""

    contacts_so_far: int = 0

    def response_prob(self, base: float) -> float:
        """
        Fatigue curve (ASSUMPTION — documented in METHODOLOGY.md).

        Each prior contact multiplies response chance by 0.55.
        Contact #1: base
        Contact #2: base * 0.55
        Contact #3: base * 0.55^2
        ...
        """
        return base * (0.55 ** self.contacts_so_far)


def sample_hidden_truth(
    rng: random.Random,
    reason: FailureReason,
) -> HiddenPayerTruth:
    """
    Draw latent payer traits conditional on the failure reason.

    This is how we encode domain knowledge into the scoreboard:
    - expired/revoked => instrument usually dead => retries almost never work
    - NSF => instrument OK, money returns near salary day
    - transient => instrument OK, quick retry often works
    """
    credit_day = rng.randint(1, 7)  # salary clustering heuristic

    if reason in {
        FailureReason.card_expired,
        FailureReason.token_invalid,
        FailureReason.mandate_revoked,
    }:
        return HiddenPayerTruth(
            instrument_valid=False,
            true_credit_day=credit_day,
            natural_recovery_prob=0.02,
            base_contact_response_prob=0.35,  # link/update can still save them
            retry_success_if_funded=0.0,
        )

    if reason == FailureReason.risk_fraud:
        return HiddenPayerTruth(
            instrument_valid=True,
            true_credit_day=credit_day,
            natural_recovery_prob=0.01,
            base_contact_response_prob=0.05,
            retry_success_if_funded=0.05,
        )

    if reason == FailureReason.insufficient_funds:
        return HiddenPayerTruth(
            instrument_valid=True,
            true_credit_day=credit_day,
            natural_recovery_prob=0.08,
            base_contact_response_prob=0.25,
            retry_success_if_funded=0.88,
        )

    if reason in {FailureReason.issuer_transient, FailureReason.gateway_timeout}:
        return HiddenPayerTruth(
            instrument_valid=True,
            true_credit_day=credit_day,
            natural_recovery_prob=0.20,
            base_contact_response_prob=0.15,
            retry_success_if_funded=0.80,
        )

    # do_not_honour and anything else: ambiguous
    return HiddenPayerTruth(
        instrument_valid=True,
        true_credit_day=credit_day,
        natural_recovery_prob=0.10,
        base_contact_response_prob=0.20,
        retry_success_if_funded=0.45,
    )


def funds_available_on_day(case: SimCase, absolute_dom: int) -> bool:
    """
    Rough salary-window model.

    ASSUMPTION: funded on true_credit_day and the next 2 calendar days (wrap 1..28).
    Outside that window, NSF-like retries fail even if instrument is valid.
    Transient failures can still succeed outside window (rail glitch, not empty account).
    """
    reason = case.visible.failure_reason
    if reason in {FailureReason.issuer_transient, FailureReason.gateway_timeout}:
        return True
    if reason == FailureReason.risk_fraud:
        return True
    if not case.hidden.instrument_valid:
        return False

    credit = case.hidden.true_credit_day
    # Normalize day into 1..28 space used by the batch generator.
    day = ((absolute_dom - 1) % 28) + 1
    window = {credit, (credit % 28) + 1, ((credit + 1) % 28) + 1}
    return day in window


def try_retry(rng: random.Random, case: SimCase, day_offset: int) -> bool:
    """Silent retry success?"""
    if not case.hidden.instrument_valid:
        return False
    abs_dom = case.failure_dom + day_offset
    if not funds_available_on_day(case, abs_dom):
        return False
    return rng.random() < case.hidden.retry_success_if_funded


def try_contact(
    rng: random.Random,
    case: SimCase,
    fatigue: FatigueState,
) -> bool:
    """
    Contact / payment-link success?

    Dead instruments can still recover via link (customer updates card).
    """
    p = fatigue.response_prob(case.hidden.base_contact_response_prob)
    fatigue.contacts_so_far += 1
    return rng.random() < p


def try_natural_recovery(rng: random.Random, case: SimCase) -> bool:
    """B0 path: sometimes money clears with no merchant action."""
    return rng.random() < case.hidden.natural_recovery_prob


def is_contact_verb(verb: SimVerb) -> bool:
    return verb in {SimVerb.send_payment_link, SimVerb.generic_nag}


def is_retry_verb(verb: SimVerb) -> bool:
    return verb == SimVerb.schedule_retry
