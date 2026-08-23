"""
eval/benchmark.py — rigorous Ours vs B2 evaluation (no policy changes).

Contracts:
- seed=42 remains the canonical single-seed headline.
- For a given (seed, n), cases are generated ONCE and shared by Ours and B2.
- Winner definition is documented in docs/SCORING.md (net recovered_inr).
- Larger N reduces sampling noise; it does not improve the policy.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from typing import Literal, Optional, Sequence

from pydantic import BaseModel, Field

from eval.baselines import POLICIES
from eval.batch import generate_batch
from eval.metrics import BatchMetrics, compute_metrics, paise_to_inr
from eval.simulate import run_batch
from eval.types import CaseOutcome, PlannedAction, SimCase

HEADLINE_SEED = 42
DEFAULT_MULTI_SEEDS: tuple[int, ...] = tuple(range(42, 52))  # 42..51 inclusive

SortKey = Literal[
    "b2_advantage",
    "ours_advantage",
    "failure_reason",
    "delta_inr",
]


class PlanSummary(BaseModel):
    verbs: list[str]
    notes: list[str] = Field(default_factory=list)


class CaseCompareRow(BaseModel):
    """Aligned Ours vs B2 result for one simulated case."""

    seed: int
    case_key: str
    failure_reason: str
    amount_paise: int
    amount_inr: float
    ours_plan: PlanSummary
    b2_plan: PlanSummary
    ours_recovered: bool
    b2_recovered: bool
    ours_recovered_paise: int
    b2_recovered_paise: int
    ours_recovered_inr: float
    b2_recovered_inr: float
    delta_inr: float  # Ours - B2
    ours_retries: int
    b2_retries: int
    ours_contacts: int
    b2_contacts: int
    ours_notes: list[str] = Field(default_factory=list)
    b2_notes: list[str] = Field(default_factory=list)


class ScenarioBreakdownRow(BaseModel):
    failure_reason: str
    n_cases: int
    ours_recovered_inr: float
    b2_recovered_inr: float
    delta_inr: float
    ours_recoveries: int
    b2_recoveries: int
    ours_recovery_rate: float  # by case count
    b2_recovery_rate: float
    ours_at_risk_inr: float
    b2_at_risk_inr: float


class ScalarStats(BaseModel):
    mean: float
    median: float
    p10: float = 0.0
    p90: float = 0.0
    stdev: float
    min: float
    max: float
    n: int


class SeedPairResult(BaseModel):
    seed: int
    n: int
    ours: BatchMetrics
    b2: BatchMetrics
    delta_recovered_inr: float
    delta_net_recovered_inr: float
    winner: Literal["ours", "b2", "tie"]
    cases: list[CaseCompareRow]
    scenarios: list[ScenarioBreakdownRow]


class EfficiencyView(BaseModel):
    """Friction proxies alongside priced net scoreboard."""

    ours_avg_retries_per_case: float
    b2_avg_retries_per_case: float
    ours_avg_contacts_per_case: float
    b2_avg_contacts_per_case: float
    ours_contacts_per_recovery: float
    b2_contacts_per_recovery: float
    ours_wasted_attempts: int = 0
    b2_wasted_attempts: int = 0
    note: str = (
        "Headline winner = higher net_recovered_inr (gross minus costs from config/costs.json). "
        "Gross recovered_inr reported separately."
    )


class MultiSeedReport(BaseModel):
    n: int
    seeds: list[int]
    headline_seed: int = HEADLINE_SEED
    scoring_winner: str = (
        "net_recovered_inr (Ours - B2). See docs/SCORING.md. "
        "Gross recovered_inr reported separately."
    )
    per_seed: list[SeedPairResult]
    # Totals pooled across all seeds (sum of at-risk / recovered)
    ours_total_at_risk_inr: float
    b2_total_at_risk_inr: float
    ours_total_recovered_inr: float
    b2_total_recovered_inr: float
    ours_total_recoveries: int
    b2_total_recoveries: int
    ours_total_retries: int
    b2_total_retries: int
    ours_total_contacts: int
    b2_total_contacts: int
    total_cases: int
    ours_pooled_recovery_rate: float
    b2_pooled_recovery_rate: float
    ours_avg_recovered_inr_per_case: float
    b2_avg_recovered_inr_per_case: float
    # Across seeds (on recovered_inr)
    ours_recovered_stats: ScalarStats
    b2_recovered_stats: ScalarStats
    delta_recovered_stats: ScalarStats
    delta_net_recovered_stats: ScalarStats
    ours_rate_stats: ScalarStats
    b2_rate_stats: ScalarStats
    seeds_won_ours: int
    seeds_won_b2: int
    seeds_tied: int
    win_rate_ours: float = 0.0
    worst_seed_for_ours: Optional[int] = None
    worst_seed_delta_net_inr: float = 0.0
    best_seed_for_ours: Optional[int] = None
    best_seed_delta_net_inr: float = 0.0
    efficiency: EfficiencyView
    scenarios_pooled: list[ScenarioBreakdownRow]


def _plan_summary(actions: Sequence[PlannedAction]) -> PlanSummary:
    return PlanSummary(
        verbs=[a.verb.value for a in actions],
        notes=[a.note for a in actions if a.note],
    )


def _outcome_by_key(outcomes: Sequence[CaseOutcome]) -> dict[str, CaseOutcome]:
    return {o.case_key: o for o in outcomes}


def _winner(delta_inr: float, *, tol: float = 0.005) -> Literal["ours", "b2", "tie"]:
    if abs(delta_inr) <= tol:
        return "tie"
    return "ours" if delta_inr > 0 else "b2"


def _percentile(values: Sequence[float], pct: float) -> float:
    vals = sorted(values)
    if not vals:
        return 0.0
    if len(vals) == 1:
        return round(vals[0], 4)
    k = (len(vals) - 1) * pct / 100.0
    f = int(k)
    c = min(f + 1, len(vals) - 1)
    if f == c:
        return round(vals[f], 4)
    return round(vals[f] + (k - f) * (vals[c] - vals[f]), 4)


def _scalar_stats(values: Sequence[float]) -> ScalarStats:
    vals = list(values)
    if not vals:
        return ScalarStats(
            mean=0.0, median=0.0, p10=0.0, p90=0.0,
            stdev=0.0, min=0.0, max=0.0, n=0,
        )
    return ScalarStats(
        mean=round(statistics.fmean(vals), 4),
        median=round(statistics.median(vals), 4),
        p10=_percentile(vals, 10),
        p90=_percentile(vals, 90),
        stdev=round(statistics.stdev(vals), 4) if len(vals) > 1 else 0.0,
        min=round(min(vals), 4),
        max=round(max(vals), 4),
        n=len(vals),
    )


def worst_seed_for_ours(per_seed: Sequence[SeedPairResult]) -> tuple[Optional[int], float]:
    """Seed with minimum net delta (ours - b2); most painful for us."""
    if not per_seed:
        return None, 0.0
    worst = min(per_seed, key=lambda p: p.delta_net_recovered_inr)
    return worst.seed, round(worst.delta_net_recovered_inr, 2)


def best_seed_for_ours(per_seed: Sequence[SeedPairResult]) -> tuple[Optional[int], float]:
    if not per_seed:
        return None, 0.0
    best = max(per_seed, key=lambda p: p.delta_net_recovered_inr)
    return best.seed, round(best.delta_net_recovered_inr, 2)


def build_case_rows(
    *,
    seed: int,
    cases: Sequence[SimCase],
    ours_outcomes: Sequence[CaseOutcome],
    b2_outcomes: Sequence[CaseOutcome],
) -> list[CaseCompareRow]:
    ours_map = _outcome_by_key(ours_outcomes)
    b2_map = _outcome_by_key(b2_outcomes)
    plan_ours = POLICIES["ours"]
    plan_b2 = POLICIES["b2"]
    rows: list[CaseCompareRow] = []
    for case in cases:
        key = case.visible.case_key
        o = ours_map[key]
        b = b2_map[key]
        o_inr = paise_to_inr(o.recovered_paise)
        b_inr = paise_to_inr(b.recovered_paise)
        rows.append(
            CaseCompareRow(
                seed=seed,
                case_key=key,
                failure_reason=case.visible.failure_reason.value,
                amount_paise=case.visible.amount_paise,
                amount_inr=round(paise_to_inr(case.visible.amount_paise), 2),
                ours_plan=_plan_summary(plan_ours(case)),
                b2_plan=_plan_summary(plan_b2(case)),
                ours_recovered=o.recovered,
                b2_recovered=b.recovered,
                ours_recovered_paise=o.recovered_paise,
                b2_recovered_paise=b.recovered_paise,
                ours_recovered_inr=round(o_inr, 2),
                b2_recovered_inr=round(b_inr, 2),
                delta_inr=round(o_inr - b_inr, 2),
                ours_retries=o.retries,
                b2_retries=b.retries,
                ours_contacts=o.contacts,
                b2_contacts=b.contacts,
                ours_notes=list(o.notes),
                b2_notes=list(b.notes),
            )
        )
    return rows


def scenario_breakdown(rows: Sequence[CaseCompareRow]) -> list[ScenarioBreakdownRow]:
    buckets: dict[str, list[CaseCompareRow]] = defaultdict(list)
    for r in rows:
        buckets[r.failure_reason].append(r)

    out: list[ScenarioBreakdownRow] = []
    for reason in sorted(buckets):
        group = buckets[reason]
        n = len(group)
        at_risk = sum(x.amount_inr for x in group)
        ours_rec = sum(x.ours_recovered_inr for x in group)
        b2_rec = sum(x.b2_recovered_inr for x in group)
        ours_wins = sum(1 for x in group if x.ours_recovered)
        b2_wins = sum(1 for x in group if x.b2_recovered)
        out.append(
            ScenarioBreakdownRow(
                failure_reason=reason,
                n_cases=n,
                ours_recovered_inr=round(ours_rec, 2),
                b2_recovered_inr=round(b2_rec, 2),
                delta_inr=round(ours_rec - b2_rec, 2),
                ours_recoveries=ours_wins,
                b2_recoveries=b2_wins,
                ours_recovery_rate=round(ours_wins / n, 6) if n else 0.0,
                b2_recovery_rate=round(b2_wins / n, 6) if n else 0.0,
                ours_at_risk_inr=round(at_risk, 2),
                b2_at_risk_inr=round(at_risk, 2),
            )
        )
    return out


def filter_sort_cases(
    rows: Sequence[CaseCompareRow],
    *,
    sort_by: SortKey = "b2_advantage",
    failure_reason: Optional[str] = None,
    recovered: Optional[Literal["ours", "b2", "either", "neither", "both"]] = None,
    limit: Optional[int] = None,
) -> list[CaseCompareRow]:
    filtered = list(rows)
    if failure_reason:
        filtered = [r for r in filtered if r.failure_reason == failure_reason]
    if recovered == "ours":
        filtered = [r for r in filtered if r.ours_recovered and not r.b2_recovered]
    elif recovered == "b2":
        filtered = [r for r in filtered if r.b2_recovered and not r.ours_recovered]
    elif recovered == "both":
        filtered = [r for r in filtered if r.ours_recovered and r.b2_recovered]
    elif recovered == "neither":
        filtered = [r for r in filtered if not r.ours_recovered and not r.b2_recovered]
    elif recovered == "either":
        filtered = [r for r in filtered if r.ours_recovered or r.b2_recovered]

    if sort_by == "b2_advantage":
        filtered.sort(key=lambda r: r.delta_inr)  # most negative first
    elif sort_by == "ours_advantage":
        filtered.sort(key=lambda r: r.delta_inr, reverse=True)
    elif sort_by == "failure_reason":
        filtered.sort(key=lambda r: (r.failure_reason, r.case_key))
    else:  # delta_inr ascending
        filtered.sort(key=lambda r: r.delta_inr)

    if limit is not None:
        filtered = filtered[:limit]
    return filtered


def compare_seed(seed: int, n: int) -> SeedPairResult:
    """
    Generate one batch; score Ours and B2 on the identical cases.
    """
    if n <= 0:
        raise ValueError("n must be positive")
    cases = generate_batch(seed=seed, n=n)
    ours_out = run_batch(seed=seed, cases=cases, plan_fn=POLICIES["ours"])
    b2_out = run_batch(seed=seed, cases=cases, plan_fn=POLICIES["b2"])
    ours_m = compute_metrics(
        label="ours",
        seed=seed,
        cases=cases,
        outcomes=ours_out,
        plan_fn=POLICIES["ours"],
    )
    b2_m = compute_metrics(
        label="b2",
        seed=seed,
        cases=cases,
        outcomes=b2_out,
        plan_fn=POLICIES["b2"],
    )
    gross_delta = round(ours_m.gross_delta_inr(b2_m), 2)
    net_delta = round(ours_m.net_delta_inr(b2_m), 2)
    rows = build_case_rows(
        seed=seed, cases=cases, ours_outcomes=ours_out, b2_outcomes=b2_out
    )
    return SeedPairResult(
        seed=seed,
        n=n,
        ours=ours_m,
        b2=b2_m,
        delta_recovered_inr=gross_delta,
        delta_net_recovered_inr=net_delta,
        winner=_winner(net_delta),
        cases=rows,
        scenarios=scenario_breakdown(rows),
    )


def run_multi_seed(
    seeds: Sequence[int],
    n: int,
) -> MultiSeedReport:
    seeds_list = list(seeds)
    if not seeds_list:
        raise ValueError("seeds must be non-empty")
    per_seed = [compare_seed(s, n) for s in seeds_list]

    ours_rec = [p.ours.recovered_inr for p in per_seed]
    b2_rec = [p.b2.recovered_inr for p in per_seed]
    deltas = [p.delta_net_recovered_inr for p in per_seed]
    gross_deltas = [p.delta_recovered_inr for p in per_seed]
    ours_rates = [p.ours.recovery_rate for p in per_seed]
    b2_rates = [p.b2.recovery_rate for p in per_seed]

    ours_at_risk = sum(p.ours.at_risk_inr for p in per_seed)
    b2_at_risk = sum(p.b2.at_risk_inr for p in per_seed)
    ours_recovered = sum(ours_rec)
    b2_recovered = sum(b2_rec)
    total_cases = sum(p.n for p in per_seed)
    ours_recoveries = sum(p.ours.recoveries for p in per_seed)
    b2_recoveries = sum(p.b2.recoveries for p in per_seed)
    ours_retries = sum(p.ours.retries for p in per_seed)
    b2_retries = sum(p.b2.retries for p in per_seed)
    ours_contacts = sum(p.ours.contacts for p in per_seed)
    b2_contacts = sum(p.b2.contacts for p in per_seed)

    all_cases: list[CaseCompareRow] = []
    for p in per_seed:
        all_cases.extend(p.cases)

    n_seeds = len(seeds_list)
    worst_seed, worst_delta = worst_seed_for_ours(per_seed)
    best_seed, best_delta = best_seed_for_ours(per_seed)

    return MultiSeedReport(
        n=n,
        seeds=seeds_list,
        per_seed=per_seed,
        ours_total_at_risk_inr=round(ours_at_risk, 2),
        b2_total_at_risk_inr=round(b2_at_risk, 2),
        ours_total_recovered_inr=round(ours_recovered, 2),
        b2_total_recovered_inr=round(b2_recovered, 2),
        ours_total_recoveries=ours_recoveries,
        b2_total_recoveries=b2_recoveries,
        ours_total_retries=ours_retries,
        b2_total_retries=b2_retries,
        ours_total_contacts=ours_contacts,
        b2_total_contacts=b2_contacts,
        total_cases=total_cases,
        ours_pooled_recovery_rate=round(ours_recovered / ours_at_risk, 6)
        if ours_at_risk
        else 0.0,
        b2_pooled_recovery_rate=round(b2_recovered / b2_at_risk, 6)
        if b2_at_risk
        else 0.0,
        ours_avg_recovered_inr_per_case=round(ours_recovered / total_cases, 4)
        if total_cases
        else 0.0,
        b2_avg_recovered_inr_per_case=round(b2_recovered / total_cases, 4)
        if total_cases
        else 0.0,
        ours_recovered_stats=_scalar_stats(ours_rec),
        b2_recovered_stats=_scalar_stats(b2_rec),
        delta_recovered_stats=_scalar_stats(gross_deltas),
        delta_net_recovered_stats=_scalar_stats(deltas),
        ours_rate_stats=_scalar_stats(ours_rates),
        b2_rate_stats=_scalar_stats(b2_rates),
        seeds_won_ours=sum(1 for p in per_seed if p.winner == "ours"),
        seeds_won_b2=sum(1 for p in per_seed if p.winner == "b2"),
        seeds_tied=sum(1 for p in per_seed if p.winner == "tie"),
        win_rate_ours=round(
            sum(1 for p in per_seed if p.winner == "ours") / n_seeds, 4
        )
        if n_seeds
        else 0.0,
        worst_seed_for_ours=worst_seed,
        worst_seed_delta_net_inr=worst_delta,
        best_seed_for_ours=best_seed,
        best_seed_delta_net_inr=best_delta,
        efficiency=EfficiencyView(
            ours_avg_retries_per_case=round(ours_retries / total_cases, 4)
            if total_cases
            else 0.0,
            b2_avg_retries_per_case=round(b2_retries / total_cases, 4)
            if total_cases
            else 0.0,
            ours_avg_contacts_per_case=round(ours_contacts / total_cases, 4)
            if total_cases
            else 0.0,
            b2_avg_contacts_per_case=round(b2_contacts / total_cases, 4)
            if total_cases
            else 0.0,
            ours_contacts_per_recovery=round(ours_contacts / ours_recoveries, 4)
            if ours_recoveries
            else -1.0,
            b2_contacts_per_recovery=round(b2_contacts / b2_recoveries, 4)
            if b2_recoveries
            else -1.0,
            ours_wasted_attempts=sum(p.ours.wasted_attempts for p in per_seed),
            b2_wasted_attempts=sum(p.b2.wasted_attempts for p in per_seed),
        ),
        scenarios_pooled=scenario_breakdown(all_cases),
    )


def parse_seeds_arg(raw: str) -> list[int]:
    """
    Accept:
      "42,43,44"
      "42-51"
      "42"
    """
    raw = raw.strip()
    if not raw:
        return list(DEFAULT_MULTI_SEEDS)
    if "-" in raw and "," not in raw:
        a, b = raw.split("-", 1)
        start, end = int(a.strip()), int(b.strip())
        if end < start:
            raise ValueError(f"invalid seed range: {raw}")
        return list(range(start, end + 1))
    return [int(x.strip()) for x in raw.split(",") if x.strip()]
