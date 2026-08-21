"""
batch.py — seeded batch generator.

Teaching:
- SAME seed => SAME list of SimCase objects.
- That is what makes baseline comparisons fair ("identical batch").
- Decline mix below is ESTIMATED for the hackathon, not Razorpay private stats.
"""

from __future__ import annotations

import random
from typing import Sequence

from eval.payer_model import sample_hidden_truth
from eval.types import FailureReason, SimCase, VisibleCase

# Approximate mix (weights). Documented in docs/METHODOLOGY.md.
DECLINE_WEIGHTS: dict[FailureReason, float] = {
    FailureReason.insufficient_funds: 0.34,
    FailureReason.issuer_transient: 0.14,
    FailureReason.gateway_timeout: 0.08,
    FailureReason.card_expired: 0.16,
    FailureReason.token_invalid: 0.08,
    FailureReason.mandate_revoked: 0.06,
    FailureReason.do_not_honour: 0.10,
    FailureReason.risk_fraud: 0.04,
}

RAILS = ("card", "upi_autopay", "enach")
# Paise amounts (INR * 100): 199, 499, 999, 1499, 2999
AMOUNTS_PAISE = (19900, 49900, 99900, 149900, 299900)


def _weighted_choice(rng: random.Random, weights: dict[FailureReason, float]) -> FailureReason:
    keys = list(weights.keys())
    vals = list(weights.values())
    return rng.choices(keys, weights=vals, k=1)[0]


def generate_batch(seed: int, n: int = 500) -> list[SimCase]:
    """
    Build n simulated at-risk subscription failures.

    Determinism contract:
      generate_batch(42, 500) == generate_batch(42, 500)  (deep equality)
    """
    if n <= 0:
        raise ValueError("n must be positive")

    rng = random.Random(seed)
    cases: list[SimCase] = []

    for i in range(n):
        reason = _weighted_choice(rng, DECLINE_WEIGHTS)
        hidden = sample_hidden_truth(rng, reason)
        failure_dom = rng.randint(1, 28)
        amount = rng.choice(AMOUNTS_PAISE)
        rail = rng.choice(RAILS)

        # Observed credit day is a NOISY hint (sometimes missing / wrong).
        # Policies may use it; hidden.true_credit_day is the actual sim truth.
        observed: int | None
        if rng.random() < 0.55:
            # Correct-ish observation
            observed = hidden.true_credit_day
        elif rng.random() < 0.5:
            observed = None
        else:
            observed = rng.randint(1, 7)

        visible = VisibleCase(
            case_key=f"sim_{seed}_{i:04d}",
            payer_ref=f"payer_{seed}_{i:04d}",
            amount_paise=amount,
            rail=rail,
            failure_reason=reason,
            attempt_number=1,
            observed_credit_day=observed,
        )
        cases.append(
            SimCase(visible=visible, hidden=hidden, failure_dom=failure_dom)
        )

    return cases


def summarize_mix(cases: Sequence[SimCase]) -> dict[str, int]:
    """Helper for debugging / methodology slides."""
    counts: dict[str, int] = {}
    for c in cases:
        key = c.visible.failure_reason.value
        counts[key] = counts.get(key, 0) + 1
    return counts
