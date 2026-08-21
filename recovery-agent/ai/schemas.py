"""
ai/schemas.py — structured outputs we demand from the model.

Teaching:
- The LLM must speak JSON that fits these models.
- Free text never becomes an executable action.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from policy.schemas import Action, ActionVerb, Channel, DecisionBundle


class CaseContext(BaseModel):
    """
    De-identified facts sent to the model.

    NEVER put phone, email, card PAN, or real name here.
    """

    event_id: str = "unknown"
    case_id: Optional[str] = None
    raw_error_reason: str
    raw_error_code: str = ""
    rail: str = "card"
    amount_bucket_inr: str = Field(
        description="Coarse bucket only, e.g. '100-500', not exact if you prefer"
    )
    amount_paise: int
    attempt_number: int = 1
    failure_dom: int = 15
    observed_credit_day: Optional[int] = None
    contacts_used: int = 0
    tenure_days: int = 0
    allowed_classes: list[str] = Field(default_factory=list)
    allowed_verbs: list[str] = Field(default_factory=list)


class Diagnosis(BaseModel):
    summary: str
    likely_class: str
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str


class MessageDraft(BaseModel):
    channel: Channel = Channel.link
    subject: str = ""
    body: str


class ProposalPayload(BaseModel):
    """What we ask the model to return for the action step."""

    verb: ActionVerb
    day_offset: int = Field(default=0, ge=0, le=60)
    channel: Channel = Channel.none
    reason_code: str = "AI_PROPOSAL"
    note: str = ""


class AgentRunResult(BaseModel):
    """Full Phase 5 output for one case (demo + ledger friendly)."""

    context: CaseContext
    diagnosis: Diagnosis
    proposal_raw: Optional[ProposalPayload] = None
    action_validated: Action
    message: Optional[MessageDraft] = None
    used_llm: bool
    fallback_reason: Optional[str] = None
    decision_rules: Optional[DecisionBundle] = None
    ledger_events: list[dict[str, Any]] = Field(default_factory=list)
