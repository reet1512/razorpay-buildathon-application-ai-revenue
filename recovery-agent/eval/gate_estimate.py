"""
eval/gate_estimate.py — how many planned actions would gates refuse?

Batch metrics stay money-true in metrics.py.
This estimates compliance pressure for the Batch UI (gate block count).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from eval.types import PlannedAction, SimCase, SimVerb
from guard.context import GuardContext
from guard.gates import all_passed, run_gates
from ledger.schemas import CaseStatus, MandateState
from policy.schemas import Action, ActionVerb, Channel, ProposedBy


def _to_action(pa: PlannedAction) -> Action:
    verb_map = {
        SimVerb.schedule_retry: ActionVerb.schedule_retry,
        SimVerb.send_payment_link: ActionVerb.send_payment_link,
        SimVerb.generic_nag: ActionVerb.send_payment_link,
        SimVerb.noop: ActionVerb.escalate_human,
    }
    verb = verb_map.get(pa.verb, ActionVerb.escalate_human)
    channel = Channel.none
    if pa.verb in {SimVerb.send_payment_link, SimVerb.generic_nag}:
        channel = Channel.link
    return Action(
        verb=verb,
        day_offset=pa.day_offset,
        channel=channel,
        reason_code=pa.note or "EVAL_PLAN",
        proposed_by=ProposedBy.rules_fallback,
    )


def count_gate_blocks(
    cases: list[SimCase],
    plan_fn: Callable[[SimCase], list[PlannedAction]],
    *,
    # Fixed daytime so contact_window is not the only story in batch estimate
    now: datetime | None = None,
) -> int:
    """
    Walk each case's plan; increment when gates refuse an action.
    Counters advance only when an action would have been allowed.
    """
    now = now or datetime(2026, 8, 21, 6, 0, tzinfo=timezone.utc)  # ~11:30 IST
    blocks = 0
    for case in cases:
        contacts = 0
        attempts = 0
        # Revoked mandates are structural stops for money actions
        mandate = MandateState.active
        if case.visible.failure_reason.value == "mandate_revoked":
            mandate = MandateState.revoked

        for pa in sorted(plan_fn(case), key=lambda a: a.day_offset):
            if pa.verb == SimVerb.noop:
                continue
            action = _to_action(pa)
            ctx = GuardContext(
                case_id=case.visible.case_key,
                case_status=CaseStatus.open,
                action=action,
                now=now,
                failure_class=case.visible.failure_reason.value,
                contacts_used=contacts,
                attempts_used=attempts,
                max_contacts=2,
                max_attempts=3,
                mandate_state=mandate,
            )
            checks = run_gates(ctx)
            if not all_passed(checks):
                blocks += 1
                continue
            if action.verb == ActionVerb.schedule_retry:
                attempts += 1
            elif action.verb in {
                ActionVerb.send_payment_link,
                ActionVerb.request_mandate_update,
            }:
                contacts += 1
                attempts += 1
    return blocks
