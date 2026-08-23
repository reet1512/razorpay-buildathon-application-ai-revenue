"""
schemas.py — Pydantic models (the "pipeline language").

Teaching analogy:
- Razorpay sends messy JSON (webhook).
- Our simulator invents JSON (batch).
- BOTH must become the SAME shape: RiskEvent.

RiskEvent = observed truth the agent is allowed to see.
It is NOT the hidden sim payer_model truth (that lives only in eval later).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums — closed sets beat free text.
# If a value is not in the enum, Pydantic rejects it early (good!).
# ---------------------------------------------------------------------------


class EventSource(str, Enum):
    """Where this RiskEvent came from."""

    razorpay_webhook = "razorpay_webhook"
    simulator = "simulator"


class Rail(str, Enum):
    """Indian recurring rails we care about for this hackathon lane."""

    card = "card"
    upi_autopay = "upi_autopay"
    enach = "enach"


class MandateState(str, Enum):
    """Simplified mandate lifecycle (sandbox may not give full fidelity)."""

    active = "active"
    paused = "paused"
    revoked = "revoked"
    expired = "expired"
    unknown = "unknown"


class CaseStatus(str, Enum):
    """
    Mutable status on the Case row (solo shortcut).

    Senior note:
    - Pure event-sourcing would derive status only by folding the ledger.
    - We store status on Case for speed, AND still append every fact to ledger.
    """

    open = "open"
    blocked = "blocked"
    stopped = "stopped"
    recovered = "recovered"


class LedgerKind(str, Enum):
    """What kind of fact we are recording. Append-only diary entries."""

    event = "event"
    classification = "classification"
    decision = "decision"
    gate_check = "gate_check"
    action = "action"
    outcome = "outcome"
    stop = "stop"
    memory_retrieval = "memory_retrieval"


class LedgerActor(str, Enum):
    """Who caused this ledger row."""

    system = "system"
    policy = "policy"
    llm = "llm"
    human = "human"


class GateResult(str, Enum):
    passed = "pass"
    blocked = "block"


# ---------------------------------------------------------------------------
# Nested context — hints about the payer, still NOT raw PII.
# ---------------------------------------------------------------------------


class PayerContext(BaseModel):
    """
    Lightweight history we keep ourselves.

    Important:
    - tenure_days / prior_failures: help scoring later
    - observed_credit_day: salary-cycle heuristic (1..28-ish)
    - preferred_language / dnd_flag: contact gates later
    - Never put phone, email, or card PAN here.
    """

    tenure_days: int = 0
    prior_failures: int = 0
    prior_recoveries: int = 0
    observed_credit_day: Optional[int] = Field(
        default=None,
        ge=1,
        le=28,
        description="Day of month money usually arrives, if known",
    )
    preferred_language: str = "en"
    dnd_flag: bool = False


# ---------------------------------------------------------------------------
# RiskEvent — THE core inbound object for Phase 1+
# ---------------------------------------------------------------------------


class RiskEvent(BaseModel):
    """
    One failed-payment moment, normalized.

    Truth model (memorize this):
    1) Observed truth  -> RiskEvent (what agent may see)
    2) Decision truth  -> LedgerEntry rows (what we did)
    3) Hidden sim truth -> eval payer_model only (NOT here)
    """

    event_id: str = Field(..., description="Idempotency key. Same id => process once.")
    source: EventSource
    occurred_at: datetime
    merchant_id: str
    payer_ref: str = Field(..., description="Pseudonymous payer id, e.g. payer_9c2")

    subscription_id: Optional[str] = None
    mandate_id: Optional[str] = None
    payment_ref: Optional[str] = Field(
        default=None,
        description="Razorpay pay_xxx on real path; may be null in pure sim",
    )

    amount_paise: int = Field(..., ge=0, description="Always store money in paise")
    currency: str = "INR"
    rail: Rail

    raw_error_code: str = ""
    raw_error_reason: str = Field(
        ...,
        description="Best failure signal we have, e.g. insufficient_funds / card_expired",
    )
    attempt_number: int = Field(default=1, ge=1)

    mandate_state: Optional[MandateState] = None
    mandate_cap_paise: Optional[int] = Field(default=None, ge=0)

    payer_context: PayerContext = Field(default_factory=PayerContext)


# ---------------------------------------------------------------------------
# CaseView / LedgerView — what APIs and tests return (not DB tables)
# ---------------------------------------------------------------------------


class CaseView(BaseModel):
    """Readable snapshot of a recovery case."""

    case_id: str
    status: CaseStatus
    failure_class: Optional[str] = None
    score: Optional[float] = None
    attempts_used: int = 0
    contacts_used: int = 0
    stop_reason: Optional[str] = None
    last_action: Optional[str] = None
    payer_ref: str
    amount_paise: int
    rail: Rail
    created_at: datetime
    updated_at: datetime


class LedgerEntryView(BaseModel):
    """One append-only audit fact, as returned to callers."""

    seq: int
    case_id: str
    at: datetime
    kind: LedgerKind
    actor: LedgerActor
    policy_version: str
    payload: dict[str, Any]
    reason_code: str
    gate_name: Optional[str] = None
    gate_result: Optional[GateResult] = None


class IngestResult(BaseModel):
    """
    What ingest_event() returns.

    duplicate=True means: we already saw this event_id.
    That is SUCCESS for payments systems (idempotent), not an error.
    """

    case_id: str
    event_id: str
    duplicate: bool
    ledger_seq: Optional[int] = None


class PaymentLinkPaidEvent(BaseModel):
    """Normalised payment_link.paid webhook (test-mode edge)."""

    event_id: str
    event_name: str = "payment_link.paid"
    payment_link_id: str
    payment_id: Optional[str] = None
    amount_paise: int = Field(default=0, ge=0)
    currency: str = "INR"
    case_id: Optional[str] = None
    occurred_at: datetime
    raw: dict[str, Any] = Field(default_factory=dict)


class PaymentLinkPaidResult(BaseModel):
    case_id: str
    event_id: str
    duplicate: bool
    recovered: bool
    payment_link_id: str
    payment_id: Optional[str] = None
    ledger_seq: Optional[int] = None
