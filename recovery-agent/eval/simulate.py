"""
simulate.py — play a policy against the hidden payer model.

Teaching:
- Policy outputs PlannedActions (intentions).
- This module rolls the dice using HiddenPayerTruth.
- Output is CaseOutcome per case — then metrics.py aggregates.
"""

from __future__ import annotations

import random
from collections.abc import Callable

from eval.payer_model import (
    FatigueState,
    is_contact_verb,
    is_retry_verb,
    try_contact,
    try_natural_recovery,
    try_retry,
)
from eval.recovery_class import RecoveryClass, recovery_class_for
from eval.types import CaseOutcome, PlannedAction, SimCase


def run_case(
    rng: random.Random,
    case: SimCase,
    plan_fn: Callable[[SimCase], list[PlannedAction]],
) -> CaseOutcome:
    """
    Execute one case plan in chronological order.

    Stops at first recovery. Remaining planned actions are skipped
    (mirrors a real stop rule: recovered => halt).
    """
    actions = sorted(plan_fn(case), key=lambda a: a.day_offset)
    fatigue = FatigueState()
    contacts = 0
    retries = 0
    wasted_attempts = 0
    notes: list[str] = []
    rc = recovery_class_for(case.visible.failure_reason)

    # If the policy does nothing, still allow natural recovery (B0 spirit).
    if not actions:
        if try_natural_recovery(rng, case):
            return CaseOutcome(
                    case_key=case.visible.case_key,
                    recovered=True,
                    recovered_paise=case.visible.amount_paise,
                    contacts=0,
                    retries=0,
                    wasted_attempts=0,
                    natural=True,
                    notes=["natural_recovery"],
                )
        return CaseOutcome(
            case_key=case.visible.case_key,
            recovered=False,
            recovered_paise=0,
            contacts=0,
            retries=0,
            wasted_attempts=0,
            notes=["no_action_no_natural"],
        )

    for action in actions:
        if is_retry_verb(action.verb):
            retries += 1
            if rc == RecoveryClass.CUSTOMER_ACTION:
                wasted_attempts += 1
            ok = try_retry(rng, case, action.day_offset)
            notes.append(f"retry@{action.day_offset}:{'ok' if ok else 'fail'}")
            if ok:
                return CaseOutcome(
                    case_key=case.visible.case_key,
                    recovered=True,
                    recovered_paise=case.visible.amount_paise,
                    contacts=contacts,
                    retries=retries,
                    wasted_attempts=wasted_attempts,
                    notes=notes,
                )

        elif is_contact_verb(action.verb):
            contacts += 1
            ok = try_contact(rng, case, fatigue)
            notes.append(f"contact@{action.day_offset}:{'ok' if ok else 'fail'}")
            if ok:
                return CaseOutcome(
                    case_key=case.visible.case_key,
                    recovered=True,
                    recovered_paise=case.visible.amount_paise,
                    contacts=contacts,
                    retries=retries,
                    wasted_attempts=wasted_attempts,
                    notes=notes,
                )

        else:
            notes.append(f"noop@{action.day_offset}")

    # After all interventions failed, a small late natural chance (optional).
    # Keep it OFF for clarity: only B0 uses pure natural path above.
    return CaseOutcome(
        case_key=case.visible.case_key,
        recovered=False,
        recovered_paise=0,
        contacts=contacts,
        retries=retries,
        wasted_attempts=wasted_attempts,
        notes=notes,
    )


def run_batch(
    seed: int,
    cases: list[SimCase],
    plan_fn: Callable[[SimCase], list[PlannedAction]],
) -> list[CaseOutcome]:
    """
    Run every case with a dedicated RNG stream derived from seed + case_key.

    Why per-case RNG?
    - Changing policy action counts should not reshuffle unrelated dice rolls
      across the whole batch in surprising ways.
    - Still fully deterministic given seed + case_key.
    """
    outcomes: list[CaseOutcome] = []
    for case in cases:
        case_rng = random.Random(f"{seed}:{case.visible.case_key}")
        outcomes.append(run_case(case_rng, case, plan_fn))
    return outcomes
