"""
guard/stops.py — terminal conditions. Once stopped, never execute again.

Teaching:
- Stop != gate block.
- Gate block: this action refused; case may continue later.
- Stop: case closed; future events are recorded only.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from sqlalchemy.orm import Session

from ledger import writer
from ledger.models import CaseRow
from ledger.schemas import CaseStatus, LedgerActor, LedgerKind
from ledger.schemas import MandateState


class StopReason(str, Enum):
    recovered = "recovered"
    mandate_revoked = "mandate_revoked"
    attempt_cap = "attempt_cap"
    opt_out = "opt_out"
    human_override = "human_override"


@dataclass(frozen=True)
class StopDecision:
    should_stop: bool
    reason: Optional[StopReason] = None


def is_case_stopped(case: CaseRow) -> bool:
    return case.status == CaseStatus.stopped.value or case.status == CaseStatus.recovered.value


def evaluate_stop_signals(
    *,
    recovered: bool = False,
    mandate_state: Optional[MandateState] = None,
    attempts_used: int = 0,
    max_attempts: int = 3,
    opt_out: bool = False,
    human_override: bool = False,
) -> StopDecision:
    """Pure function: given signals, should we stop?"""
    if human_override:
        return StopDecision(True, StopReason.human_override)
    if recovered:
        return StopDecision(True, StopReason.recovered)
    if opt_out:
        return StopDecision(True, StopReason.opt_out)
    if mandate_state is not None and mandate_state.value == "revoked":
        return StopDecision(True, StopReason.mandate_revoked)
    if attempts_used >= max_attempts:
        return StopDecision(True, StopReason.attempt_cap)
    return StopDecision(False, None)


def apply_stop(
    session: Session,
    case: CaseRow,
    reason: StopReason,
    *,
    policy_version: str = "phase6",
) -> CaseRow:
    """
    Terminal write:
    - case.status = stopped (or recovered)
    - ledger kind=stop
    """
    if reason == StopReason.recovered:
        case.status = CaseStatus.recovered.value
    else:
        case.status = CaseStatus.stopped.value
    case.stop_reason = reason.value
    session.add(case)
    writer.append_ledger(
        session,
        case_id=case.id,
        kind=LedgerKind.stop,
        actor=LedgerActor.system,
        payload={"stop_reason": reason.value},
        reason_code=reason.value,
        policy_version=policy_version,
    )
    session.flush()
    return case
