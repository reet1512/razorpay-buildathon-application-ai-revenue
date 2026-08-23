"""
guard/context.py — everything a gate is allowed to inspect.

Teaching:
- Gates should not reach into random globals.
- Pass an explicit GuardContext so tests can freeze time / mandate state.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Set

from pydantic import BaseModel, Field

from ledger.schemas import CaseStatus, MandateState
from policy.schemas import Action


class GuardContext(BaseModel):
    """Runtime facts for gate evaluation."""

    case_id: str
    case_status: CaseStatus = CaseStatus.open
    action: Action

    # Clock (inject in tests)
    now: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Contact / attempt counters on the case
    attempts_used: int = 0
    contacts_used: int = 0
    max_attempts: int = 3
    max_contacts: int = 2

    # Mandate
    mandate_state: Optional[MandateState] = MandateState.active

    # Payer flags
    opt_out: bool = False
    dnd_flag: bool = False

    # Contact window in local hours [start, end) — default 09:00-21:00
    # For demos we treat `now` hour in this timezone-naive sense using now.hour
    # after converting to IST offset (+5:30) approximately via hour math in gate.
    contact_window_start_hour_ist: int = 9
    contact_window_end_hour_ist: int = 21

    # Idempotency: fingerprints of actions already executed for this case/event
    executed_fingerprints: Set[str] = Field(default_factory=set)
    action_fingerprint: str = ""

    stop_reason: Optional[str] = None

    # Taxonomy class for prohibited-recovery gate (e.g. risk_fraud)
    failure_class: Optional[str] = None
