"""
baselines.py — cause-blind (and early cause-aware) policies.

Teaching:
- A baseline is just: SimCase -> list[PlannedAction]
- Baselines should look like what merchants actually do today.
- Beating a straw man is worse than not measuring.

B2 one-liner for judges:
  "Three fixed retries plus one generic nag — same ladder for every failure reason."
"""

from __future__ import annotations

from collections.abc import Callable

from eval.types import PlannedAction, SimCase, SimVerb

PolicyFn = Callable[[SimCase], list[PlannedAction]]


def baseline_b0(_case: SimCase) -> list[PlannedAction]:
    """Do nothing. Count only natural recovery."""
    return []


def baseline_b1(_case: SimCase) -> list[PlannedAction]:
    """Naive: retry once immediately."""
    return [
        PlannedAction(verb=SimVerb.schedule_retry, day_offset=0, note="b1_immediate_retry"),
    ]


def baseline_b2(_case: SimCase) -> list[PlannedAction]:
    """
    Fixed ladder (cause-blind) — the main rival to beat.

    Schedule:
      day 0: retry
      day 1: generic nag email/SMS
      day 2: retry
      day 5: retry
    """
    return [
        PlannedAction(verb=SimVerb.schedule_retry, day_offset=0, note="b2_retry_0"),
        PlannedAction(verb=SimVerb.generic_nag, day_offset=1, note="b2_nag"),
        PlannedAction(verb=SimVerb.schedule_retry, day_offset=2, note="b2_retry_2"),
        PlannedAction(verb=SimVerb.schedule_retry, day_offset=5, note="b2_retry_5"),
    ]


def baseline_b3(case: SimCase) -> list[PlannedAction]:
    """
    Aggressive: many retries + multiple contacts (still cause-blind).

    Optional. May win raw INR and lose on contacts/recovery — a useful story.
    """
    _ = case
    actions = [
        PlannedAction(verb=SimVerb.schedule_retry, day_offset=d, note=f"b3_retry_{d}")
        for d in (0, 1, 2, 3, 5, 8, 13)
    ]
    actions.extend(
        [
            PlannedAction(verb=SimVerb.generic_nag, day_offset=0, note="b3_nag_0"),
            PlannedAction(verb=SimVerb.generic_nag, day_offset=3, note="b3_nag_3"),
            PlannedAction(verb=SimVerb.generic_nag, day_offset=7, note="b3_nag_7"),
            PlannedAction(
                verb=SimVerb.send_payment_link, day_offset=10, note="b3_link"
            ),
        ]
    )
    return actions


def policy_ours_v0(case: SimCase) -> list[PlannedAction]:
    """
    Cause-aware policy backed by policy/taxonomy.yaml (Phase 4).

    Kept as a thin wrapper so the harness still says `--policy ours`.
    """
    from policy.engine import policy_ours_from_taxonomy

    return policy_ours_from_taxonomy(case)


POLICIES: dict[str, PolicyFn] = {
    "b0": baseline_b0,
    "b1": baseline_b1,
    "b2": baseline_b2,
    "b3": baseline_b3,
    "ours": policy_ours_v0,
}
