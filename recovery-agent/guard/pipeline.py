"""
guard/pipeline.py — run gates, write audit rows, optionally execute.

Phase 7 wires real adapters via execute_fn (see execute/service.py).
We keep execute_fn optional so tests can prove "no adapter call on block".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from sqlalchemy.orm import Session

from guard.context import GuardContext
from guard.gates import GateCheck, all_passed, run_gates
from guard.stops import StopReason, apply_stop, is_case_stopped
from ledger import writer
from ledger.models import CaseRow
from ledger.schemas import CaseStatus, GateResult, LedgerActor, LedgerKind
from policy.schemas import Action


ExecuteFn = Callable[[Action, CaseRow], dict[str, Any]]


@dataclass
class GuardPipelineResult:
    allowed: bool
    checks: list[GateCheck] = field(default_factory=list)
    executed: bool = False
    execute_result: Optional[dict[str, Any]] = None
    blocked_by: Optional[str] = None
    skipped_because_stopped: bool = False
    ledger_seqs: list[int] = field(default_factory=list)


def record_gate_checks(
    session: Session,
    case_id: str,
    checks: list[GateCheck],
    *,
    policy_version: str = "phase6",
    ctx: Optional[GuardContext] = None,
    audit: Optional[dict[str, Any]] = None,
) -> list[int]:
    """Append one ledger row per gate (pass OR block) with audit metadata."""
    seqs: list[int] = []
    audit_base: dict[str, Any] = dict(audit or {})
    if ctx is not None:
        audit_base.setdefault("proposed_verb", ctx.action.verb.value)
        audit_base.setdefault("proposed_channel", ctx.action.channel.value)
        audit_base.setdefault("failure_class", ctx.failure_class)
        audit_base.setdefault("action_fingerprint", ctx.action_fingerprint)
    for c in checks:
        payload = {
            "gate": c.name,
            "reason_code": c.reason_code,
            "verdict": "pass" if c.passed else "block",
            **audit_base,
        }
        row = writer.append_ledger(
            session,
            case_id=case_id,
            kind=LedgerKind.gate_check,
            actor=LedgerActor.system,
            payload=payload,
            reason_code=c.reason_code,
            policy_version=policy_version,
            gate_name=c.name,
            gate_result=GateResult.passed if c.passed else GateResult.blocked,
            at=ctx.now if ctx is not None else None,
        )
        seqs.append(row.seq)
    return seqs


def guard_and_maybe_execute(
    session: Session,
    case: CaseRow,
    ctx: GuardContext,
    *,
    execute_fn: Optional[ExecuteFn] = None,
    policy_version: str = "phase6",
    audit: Optional[dict[str, Any]] = None,
) -> GuardPipelineResult:
    """
    Main Phase 6 entry.

    If case already stopped/recovered: do not execute (adversarial stop test).
    Else run gates; on full pass, call execute_fn if provided.
    """
    if is_case_stopped(case):
        return GuardPipelineResult(
            allowed=False,
            skipped_because_stopped=True,
            blocked_by=case.stop_reason or "stopped",
        )

    # Opt-out is both a stop signal and an immediate refuse.
    if ctx.opt_out:
        apply_stop(session, case, StopReason.opt_out, policy_version=policy_version)
        return GuardPipelineResult(
            allowed=False,
            blocked_by="opt_out",
            skipped_because_stopped=True,
        )

    checks = run_gates(ctx)
    audit_meta = dict(audit or {})
    if ctx.action.proposed_by is not None:
        audit_meta.setdefault("proposed_by", ctx.action.proposed_by.value)
    seqs = record_gate_checks(
        session,
        case.id,
        checks,
        policy_version=policy_version,
        ctx=ctx,
        audit=audit_meta,
    )

    if not all_passed(checks):
        blocked = next(c for c in checks if not c.passed)
        # Mark case blocked for visibility (still not a terminal stop).
        case.status = CaseStatus.blocked.value
        session.add(case)
        session.flush()
        return GuardPipelineResult(
            allowed=False,
            checks=checks,
            blocked_by=blocked.name,
            ledger_seqs=seqs,
        )

    # Passed — reopen if previously blocked
    if case.status == CaseStatus.blocked.value:
        case.status = CaseStatus.open.value
        session.add(case)

    executed = False
    exec_result = None
    if execute_fn is not None:
        exec_result = execute_fn(ctx.action, case)
        executed = True
        writer.append_ledger(
            session,
            case_id=case.id,
            kind=LedgerKind.action,
            actor=LedgerActor.system,
            payload={
                "action": ctx.action.model_dump(mode="json"),
                "execute_result": exec_result,
            },
            reason_code=ctx.action.reason_code or ctx.action.verb.value,
            policy_version=policy_version,
        )
        # Track fingerprint as executed for idempotency
        # (caller may persist fingerprints; for in-memory ctx we mutate set)
        ctx.executed_fingerprints.add(ctx.action_fingerprint or "")

    session.flush()
    return GuardPipelineResult(
        allowed=True,
        checks=checks,
        executed=executed,
        execute_result=exec_result,
        ledger_seqs=seqs,
    )
