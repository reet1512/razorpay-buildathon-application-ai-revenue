"""
types.py — shared shapes for the eval harness.

Teaching:
- Keep eval types SEPARATE from ledger schemas for now.
- Eval simulates a mini-world. Ledger stores real/product facts.
- Later phases can map eval cases -> RiskEvent for end-to-end tests.
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Optional

from pydantic import BaseModel, Field

if TYPE_CHECKING:  # pragma: no cover - import only for type checkers
    from eval.recovery_class import RecoveryClass


class SimVerb(str, Enum):
    """Actions a baseline/policy may schedule inside the simulator."""

    schedule_retry = "schedule_retry"
    send_payment_link = "send_payment_link"  # counts as a contact
    generic_nag = "generic_nag"  # B2-style dumb contact
    noop = "noop"


class PlannedAction(BaseModel):
    """
    One planned intervention at a day offset from failure day 0.

    day_offset=0 means "same day as failure"
    day_offset=3 means "three days later"
    """

    verb: SimVerb
    day_offset: int = Field(ge=0, le=60)
    note: str = ""


class FailureReason(str, Enum):
    """Decline mix used by the batch generator (estimated, not Razorpay private data)."""

    insufficient_funds = "insufficient_funds"
    issuer_transient = "issuer_transient"
    gateway_timeout = "gateway_timeout"
    card_expired = "card_expired"
    token_invalid = "token_invalid"
    mandate_revoked = "mandate_revoked"
    risk_fraud = "risk_fraud"
    do_not_honour = "do_not_honour"


class VisibleCase(BaseModel):
    """
    What a policy is ALLOWED to see (observed truth).

    Same spirit as RiskEvent — no hidden balances here.
    """

    case_key: str
    payer_ref: str
    amount_paise: int
    rail: str
    failure_reason: FailureReason
    attempt_number: int = 1
    # Observed hint only (not the secret balance). May be None.
    observed_credit_day: Optional[int] = None


class HiddenPayerTruth(BaseModel):
    """
    Latent variables ONLY the simulator uses to score outcomes.

    The policy/baseline must NEVER read this directly.
    If it does, your metric is cheating.
    """

    instrument_valid: bool
    # Day-of-month when salary/credit usually lands (1..28)
    true_credit_day: int
    # Probability they recover with NO intervention over the horizon
    natural_recovery_prob: float
    # Base probability they act on a contact/link before fatigue
    base_contact_response_prob: float
    # Multiplier for silent retry success when funds ARE present
    retry_success_if_funded: float = 0.92


class SimCase(BaseModel):
    """One row in the seeded batch: visible + hidden glued for bookkeeping."""

    visible: VisibleCase
    hidden: HiddenPayerTruth
    # Calendar day-of-month when the failure happened (1..28) for timing logic
    failure_dom: int


class CaseOutcome(BaseModel):
    """Result after playing one policy against one case."""

    case_key: str
    recovered: bool
    recovered_paise: int
    contacts: int
    retries: int
    wasted_attempts: int = Field(
        default=0,
        description="Retries against CUSTOMER_ACTION (structurally zero recovery)",
    )
    natural: bool = False
    notes: list[str] = Field(default_factory=list)


def recovery_class_for_reason(reason: FailureReason) -> "RecoveryClass":
    """Lazy import to keep types.py free of circular imports."""
    from eval.recovery_class import recovery_class_for

    return recovery_class_for(reason)
