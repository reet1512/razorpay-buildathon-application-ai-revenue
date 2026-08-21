"""
policy/schemas.py — Action shape the AI must emit (Phase 5) and rules emit now.

Closed verbs = the agent cannot invent "call_customer_on_whatsapp_at_3am".
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class ActionVerb(str, Enum):
    schedule_retry = "schedule_retry"
    send_payment_link = "send_payment_link"
    request_mandate_update = "request_mandate_update"
    escalate_human = "escalate_human"


class Channel(str, Enum):
    none = "none"
    sms = "sms"
    email = "email"
    link = "link"


class ProposedBy(str, Enum):
    llm = "llm"
    rules_fallback = "rules_fallback"


class Action(BaseModel):
    """
    One bounded intervention.

    `when` may be absolute datetime for product path.
    Eval path mainly uses day_offset via PlannedAction bridge.
    """

    verb: ActionVerb
    when: Optional[datetime] = None
    day_offset: Optional[int] = Field(
        default=None,
        ge=0,
        description="Eval/sim convenience: days after failure",
    )
    channel: Channel = Channel.none
    amount_paise: Optional[int] = Field(default=None, ge=0)
    reason_code: str = ""
    policy_version: str = "unset"
    proposed_by: ProposedBy = ProposedBy.rules_fallback
    failure_class: str = ""
    score: Optional[float] = None
    note: str = ""


class DecisionBundle(BaseModel):
    """Everything Phase 4 produces for one case/event."""

    failure_class: str
    category: str
    score: float
    effort_band: str
    actions: list[Action]
    classification_matched_on: str = ""
    policy_version: str = ""
