"""
eval/recovery_class.py — failure reason → recovery class (the core argument).

Four classes:
  RETRY_FIXABLE   — timing/transient; retries can work
  CUSTOMER_ACTION — dead instrument; retries are structurally zero in the sim
  AMBIGUOUS       — do_not_honour; careful contact, capped retries
  PROHIBITED      — risk/fraud; payer model allows tiny retry chance but gates block
"""

from __future__ import annotations

from enum import Enum

from eval.types import FailureReason


class RecoveryClass(str, Enum):
    RETRY_FIXABLE = "RETRY_FIXABLE"
    CUSTOMER_ACTION = "CUSTOMER_ACTION"
    AMBIGUOUS = "AMBIGUOUS"
    PROHIBITED = "PROHIBITED"


FAILURE_TO_RECOVERY_CLASS: dict[FailureReason, RecoveryClass] = {
    FailureReason.insufficient_funds: RecoveryClass.RETRY_FIXABLE,
    FailureReason.issuer_transient: RecoveryClass.RETRY_FIXABLE,
    FailureReason.gateway_timeout: RecoveryClass.RETRY_FIXABLE,
    FailureReason.card_expired: RecoveryClass.CUSTOMER_ACTION,
    FailureReason.token_invalid: RecoveryClass.CUSTOMER_ACTION,
    FailureReason.mandate_revoked: RecoveryClass.CUSTOMER_ACTION,
    FailureReason.do_not_honour: RecoveryClass.AMBIGUOUS,
    FailureReason.risk_fraud: RecoveryClass.PROHIBITED,
}


def recovery_class_for(reason: FailureReason) -> RecoveryClass:
    try:
        return FAILURE_TO_RECOVERY_CLASS[reason]
    except KeyError as exc:
        raise KeyError(f"no recovery class for failure reason {reason!r}") from exc


def retry_probability_is_structurally_zero(reason: FailureReason) -> bool:
    """
    True only for CUSTOMER_ACTION — retries cannot fix a dead instrument.

    PROHIBITED is blocked at the gate layer, not here.
    """
    return recovery_class_for(reason) == RecoveryClass.CUSTOMER_ACTION
