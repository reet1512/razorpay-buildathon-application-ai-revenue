"""
Convert completed simulator cases into PaymentEpisode records.

Uses authoritative eval outputs — does not rerun recovery logic or recompute
net recovery differently from eval/costing.py.
"""

from __future__ import annotations

from typing import Optional, Sequence

from eval.baselines import POLICIES
from eval.costing import compute_case_costs, paise_to_inr
from eval.costing import _executed_actions  # authoritative executed-action list
from eval.recovery_class import RecoveryClass, recovery_class_for
from eval.simulate import run_case
from eval.types import CaseOutcome, SimCase, SimVerb

from memory.constants import SIMULATION_VERSION
from memory.identity import logical_episode_id
from memory.schemas import DataSource, EpisodeOutcome, PaymentEpisode
from policy.schemas import ActionVerb


def sim_verb_to_action(verb: SimVerb) -> str:
    if verb == SimVerb.schedule_retry:
        return ActionVerb.schedule_retry.value
    if verb == SimVerb.send_payment_link:
        return ActionVerb.send_payment_link.value
    if verb == SimVerb.generic_nag:
        return "generic_nag"
    return "noop"


def _primary_executed_action(
    case: SimCase,
    outcome: CaseOutcome,
    plan_fn,
) -> tuple[str, Optional[int]]:
    executed = _executed_actions(case, outcome, plan_fn)
    if not executed:
        planned = sorted(plan_fn(case), key=lambda a: a.day_offset)
        if planned:
            first = planned[0]
            return sim_verb_to_action(first.verb), first.day_offset * 86400
        return "noop", None
    first = executed[0]
    return sim_verb_to_action(first.verb), first.day_offset * 86400


def net_recovered_paise_for_case(
    case: SimCase,
    outcome: CaseOutcome,
    plan_fn,
    *,
    label: str = "ours",
) -> int:
    costs = compute_case_costs(case, outcome, plan_fn, label=label)
    gross_inr = paise_to_inr(outcome.recovered_paise)
    total_cost = (
        costs.attempt_cost_inr
        + costs.mdr_cost_inr
        + costs.risk_cost_inr
        + costs.customer_cost_inr
    )
    net_inr = gross_inr - total_cost
    return max(0, int(round(net_inr * 100)))


def payment_episode_from_case(
    *,
    case: SimCase,
    outcome: CaseOutcome,
    seed: int,
    plan_fn=None,
    simulation_version: str = SIMULATION_VERSION,
) -> PaymentEpisode:
    """
    Map one simulated case + outcome to a PaymentEpisode.

    Default plan_fn is the Ours policy used by the benchmark harness.
    """
    if plan_fn is None:
        plan_fn = POLICIES["ours"]

    visible = case.visible
    rc = recovery_class_for(visible.failure_reason)
    action, delay_seconds = _primary_executed_action(case, outcome, plan_fn)
    net_paise = net_recovered_paise_for_case(case, outcome, plan_fn, label="ours")
    case_id = visible.case_key

    return PaymentEpisode(
        episode_id=logical_episode_id(
            seed=seed,
            case_id=case_id,
            simulation_version=simulation_version,
        ),
        case_id=case_id,
        seed=seed,
        simulation_version=simulation_version,
        amount_paise=visible.amount_paise,
        rail=visible.rail,
        failure_reason=visible.failure_reason,
        recovery_class=rc,
        attempt_number=visible.attempt_number,
        action=action,
        outcome=EpisodeOutcome.success if outcome.recovered else EpisodeOutcome.failed,
        recovered_paise=outcome.recovered_paise,
        net_recovered_paise=net_paise,
        data_source=DataSource.synthetic_simulation,
        delay_seconds=delay_seconds,
        prohibited=(rc == RecoveryClass.PROHIBITED),
    )


def generate_episodes_for_seed(
    seed: int,
    n: int,
    *,
    simulation_version: str = SIMULATION_VERSION,
    plan_fn=None,
) -> list[PaymentEpisode]:
    """Generate n episodes using the same path as eval/benchmark.compare_seed."""
    import random

    from eval.batch import generate_batch

    if plan_fn is None:
        plan_fn = POLICIES["ours"]

    cases = generate_batch(seed=seed, n=n)
    episodes: list[PaymentEpisode] = []
    for case in cases:
        case_rng = random.Random(f"{seed}:{case.visible.case_key}")
        outcome = run_case(case_rng, case, plan_fn)
        episodes.append(
            payment_episode_from_case(
                case=case,
                outcome=outcome,
                seed=seed,
                plan_fn=plan_fn,
                simulation_version=simulation_version,
            )
        )
    return episodes


def generate_episodes_for_seeds(
    seeds: Sequence[int],
    n: int,
    *,
    limit: Optional[int] = None,
    simulation_version: str = SIMULATION_VERSION,
) -> list[PaymentEpisode]:
    episodes: list[PaymentEpisode] = []
    for seed in seeds:
        batch = generate_episodes_for_seed(
            seed, n, simulation_version=simulation_version
        )
        episodes.extend(batch)
        if limit is not None and len(episodes) >= limit:
            return episodes[:limit]
    return episodes
