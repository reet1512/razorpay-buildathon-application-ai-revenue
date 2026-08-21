"""
execute/service.py — choose adapter + run behind the guard pipeline.

Teaching:
  Guard first. Adapter second. Ledger always.
"""

from __future__ import annotations

import os
from typing import Any, Optional

from sqlalchemy.orm import Session

from execute.base import ExecuteMeta, Outcome
from execute.razorpay_adapter import RazorpayExecutor
from execute.sim_adapter import SimExecutor
from guard.context import GuardContext
from guard.pipeline import GuardPipelineResult, guard_and_maybe_execute
from guard.stops import StopReason, apply_stop
from ledger import writer
from ledger.models import CaseRow
from ledger.schemas import LedgerActor, LedgerKind
from logging_util import slog
from policy.schemas import Action


def get_executor(mode: Optional[str] = None):
    mode = (mode or os.getenv("EXECUTOR_MODE", "sim")).lower()
    if mode == "razorpay":
        return RazorpayExecutor()
    return SimExecutor()


def execute_with_guards(
    session: Session,
    case: CaseRow,
    ctx: GuardContext,
    *,
    meta: Optional[ExecuteMeta] = None,
    mode: Optional[str] = None,
    policy_version: str = "phase7",
) -> tuple[GuardPipelineResult, Optional[Outcome]]:
    """
    Full Phase 6+7 path:
      gates -> (if allowed) executor.run -> ledger outcome
      if recovered -> stop(recovered)
    """
    executor = get_executor(mode)
    meta = meta or ExecuteMeta(failure_reason="unknown", seed=case.id)
    outcome_box: dict[str, Any] = {"outcome": None}

    def _exec(action: Action, c: CaseRow) -> dict[str, Any]:
        out = executor.run(action, c, meta)
        outcome_box["outcome"] = out
        writer.append_ledger(
            session,
            case_id=c.id,
            kind=LedgerKind.outcome,
            actor=LedgerActor.system,
            payload=out.model_dump(),
            reason_code=out.status,
            policy_version=policy_version,
        )
        if out.recovered:
            apply_stop(session, c, StopReason.recovered, policy_version=policy_version)
        elif action.verb.value == "schedule_retry":
            c.attempts_used = int(c.attempts_used or 0) + 1
            session.add(c)
        elif action.verb.value in {"send_payment_link", "request_mandate_update"}:
            c.contacts_used = int(c.contacts_used or 0) + 1
            c.last_action = action.verb.value
            session.add(c)
        return out.model_dump()

    result = guard_and_maybe_execute(
        session,
        case,
        ctx,
        execute_fn=_exec,
        policy_version=policy_version,
    )
    slog(
        "execute_pipeline",
        case_id=case.id,
        verb=ctx.action.verb.value,
        gate=result.blocked_by,
        status="allowed" if result.allowed else "blocked",
        mode=(mode or "sim"),
    )
    return result, outcome_box["outcome"]
