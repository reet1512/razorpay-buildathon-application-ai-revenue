"""
eval/report.py — human-readable benchmark output (Ours vs B2).
"""

from __future__ import annotations

from typing import Optional, Sequence

from eval.benchmark import (
    CaseCompareRow,
    MultiSeedReport,
    SeedPairResult,
    filter_sort_cases,
)


def _fmt_inr(x: float) -> str:
    return f"{x:,.2f}"


def _fmt_rate(x: float) -> str:
    return f"{x:.2%}"


def format_seed_pair(result: SeedPairResult) -> str:
    o, b = result.ours, result.b2
    lines = [
        "BENCHMARK (single seed)",
        "-----------------------",
        f"N: {result.n}",
        f"Seed: {result.seed}  (headline/reference seed is 42)",
        f"Winner (raw recovered_inr): {result.winner.upper()}",
        "",
        "Scoring: winner = higher recovered_inr. Contacts/retries do NOT change winner.",
        "",
        f"{'':22} {'OURS':>12} {'B2':>12} {'DELTA':>12}",
        f"{'At-risk INR':22} {_fmt_inr(o.at_risk_inr):>12} {_fmt_inr(b.at_risk_inr):>12} {'-':>12}",
        f"{'Recovered INR':22} {_fmt_inr(o.recovered_inr):>12} {_fmt_inr(b.recovered_inr):>12} {_fmt_inr(result.delta_recovered_inr):>12}",
        f"{'Recovery rate':22} {_fmt_rate(o.recovery_rate):>12} {_fmt_rate(b.recovery_rate):>12} {_fmt_rate(o.recovery_rate - b.recovery_rate):>12}",
        f"{'Recoveries':22} {o.recoveries:>12} {b.recoveries:>12} {o.recoveries - b.recoveries:>12}",
        f"{'Retries (total)':22} {o.retries:>12} {b.retries:>12} {o.retries - b.retries:>12}",
        f"{'Contacts (total)':22} {o.contacts:>12} {b.contacts:>12} {o.contacts - b.contacts:>12}",
        f"{'Avg retries/case':22} {o.retries / result.n:>12.3f} {b.retries / result.n:>12.3f} {(o.retries - b.retries) / result.n:>12.3f}",
        f"{'Contacts/recovery':22} {o.contacts_per_recovery:>12.3f} {b.contacts_per_recovery:>12.3f}",
        "",
        "Scenario breakdown (existing FailureReason taxonomy):",
    ]
    for s in result.scenarios:
        lines.append(
            f"  {s.failure_reason:22} n={s.n_cases:<4} "
            f"Ours INR {_fmt_inr(s.ours_recovered_inr)} ({_fmt_rate(s.ours_recovery_rate)})  "
            f"B2 INR {_fmt_inr(s.b2_recovered_inr)} ({_fmt_rate(s.b2_recovery_rate)})  "
            f"dINR {_fmt_inr(s.delta_inr)}"
        )
    return "\n".join(lines)


def format_multi_seed(report: MultiSeedReport) -> str:
    seed_lo, seed_hi = report.seeds[0], report.seeds[-1]
    seed_label = (
        f"{seed_lo}-{seed_hi}"
        if report.seeds == list(range(seed_lo, seed_hi + 1))
        else ",".join(str(s) for s in report.seeds)
    )
    n_seeds = len(report.seeds)
    lines = [
        "BENCHMARK",
        "----------",
        f"N: {report.n}",
        f"Seeds: {seed_label}  (n_seeds={n_seeds}; headline seed={report.headline_seed})",
        "",
        "Scoring note:",
        f"  {report.scoring_winner}",
        f"  Efficiency: {report.efficiency.note}",
        "",
        "Aggregate (pooled across seeds):",
        f"{'':22} {'OURS':>14} {'B2':>14} {'DELTA':>14}",
        f"{'At-risk INR':22} {_fmt_inr(report.ours_total_at_risk_inr):>14} {_fmt_inr(report.b2_total_at_risk_inr):>14}",
        f"{'Recovered INR':22} {_fmt_inr(report.ours_total_recovered_inr):>14} {_fmt_inr(report.b2_total_recovered_inr):>14} {_fmt_inr(report.ours_total_recovered_inr - report.b2_total_recovered_inr):>14}",
        f"{'Recovery rate':22} {_fmt_rate(report.ours_pooled_recovery_rate):>14} {_fmt_rate(report.b2_pooled_recovery_rate):>14}",
        f"{'Cases':22} {report.total_cases:>14} {report.total_cases:>14}",
        f"{'Recoveries':22} {report.ours_total_recoveries:>14} {report.b2_total_recoveries:>14}",
        f"{'Avg recovered/case':22} {report.ours_avg_recovered_inr_per_case:>14.4f} {report.b2_avg_recovered_inr_per_case:>14.4f}",
        f"{'Total retries':22} {report.ours_total_retries:>14} {report.b2_total_retries:>14}",
        f"{'Avg retries/case':22} {report.efficiency.ours_avg_retries_per_case:>14.4f} {report.efficiency.b2_avg_retries_per_case:>14.4f}",
        f"{'Total contacts':22} {report.ours_total_contacts:>14} {report.b2_total_contacts:>14}",
        f"{'Contacts/recovery':22} {report.efficiency.ours_contacts_per_recovery:>14.4f} {report.efficiency.b2_contacts_per_recovery:>14.4f}",
        "",
        "Across-seed recovered INR:",
        f"  Ours  mean={report.ours_recovered_stats.mean:,.2f}  median={report.ours_recovered_stats.median:,.2f}  "
        f"stdev={report.ours_recovered_stats.stdev:,.2f}  min={report.ours_recovered_stats.min:,.2f}  max={report.ours_recovered_stats.max:,.2f}",
        f"  B2    mean={report.b2_recovered_stats.mean:,.2f}  median={report.b2_recovered_stats.median:,.2f}  "
        f"stdev={report.b2_recovered_stats.stdev:,.2f}  min={report.b2_recovered_stats.min:,.2f}  max={report.b2_recovered_stats.max:,.2f}",
        f"  Delta mean={report.delta_recovered_stats.mean:,.2f}  median={report.delta_recovered_stats.median:,.2f}  "
        f"stdev={report.delta_recovered_stats.stdev:,.2f}  min={report.delta_recovered_stats.min:,.2f}  max={report.delta_recovered_stats.max:,.2f}",
        "",
        "Seeds won (by recovered_inr):",
        f"  Ours: {report.seeds_won_ours}/{n_seeds}",
        f"  B2:   {report.seeds_won_b2}/{n_seeds}",
        f"  Ties: {report.seeds_tied}/{n_seeds}",
        "",
        "Per-seed:",
    ]
    for p in report.per_seed:
        lines.append(
            f"  seed {p.seed:<4}  Ours INR {_fmt_inr(p.ours.recovered_inr)}  "
            f"B2 INR {_fmt_inr(p.b2.recovered_inr)}  dINR {_fmt_inr(p.delta_recovered_inr)}  [{p.winner}]"
        )
    lines.append("")
    lines.append("Scenario breakdown (pooled; existing taxonomy):")
    for s in report.scenarios_pooled:
        lines.append(
            f"  {s.failure_reason:22} n={s.n_cases:<5} "
            f"Ours INR {_fmt_inr(s.ours_recovered_inr)} ({_fmt_rate(s.ours_recovery_rate)})  "
            f"B2 INR {_fmt_inr(s.b2_recovered_inr)} ({_fmt_rate(s.b2_recovery_rate)})  "
            f"dINR {_fmt_inr(s.delta_inr)}"
        )
    return "\n".join(lines)


def format_case_table(
    rows: Sequence[CaseCompareRow],
    *,
    title: str = "Per-case (sorted)",
) -> str:
    lines = [title, "-" * len(title)]
    if not rows:
        lines.append("(no cases)")
        return "\n".join(lines)
    for r in rows:
        lines.append(
            f"{r.case_key}  {r.failure_reason:20}  "
            f"Ours={'Y' if r.ours_recovered else 'N'}INR{r.ours_recovered_inr:.0f} "
            f"[{','.join(r.ours_plan.verbs) or '-'}]  "
            f"B2={'Y' if r.b2_recovered else 'N'}INR{r.b2_recovered_inr:.0f} "
            f"[{','.join(r.b2_plan.verbs) or '-'}]  "
            f"dINR{r.delta_inr:.0f}"
        )
    return "\n".join(lines)


def cases_section(
    result: SeedPairResult | MultiSeedReport,
    *,
    sort_by: str = "b2_advantage",
    failure_reason: Optional[str] = None,
    limit: int = 15,
) -> str:
    if isinstance(result, SeedPairResult):
        rows = result.cases
    else:
        rows = [c for p in result.per_seed for c in p.cases]
    top = filter_sort_cases(
        rows,
        sort_by=sort_by,  # type: ignore[arg-type]
        failure_reason=failure_reason,
        limit=limit,
    )
    return format_case_table(
        top,
        title=f"Top {limit} cases by {sort_by}"
        + (f" (failure={failure_reason})" if failure_reason else ""),
    )
