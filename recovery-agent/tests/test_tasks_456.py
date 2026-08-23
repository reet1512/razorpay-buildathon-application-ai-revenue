"""Tests for Task 4/5/6: segments, break-even, distribution stats."""

from __future__ import annotations

from config.costs import clear_cost_overrides, get_cost_value
from eval.benchmark import run_multi_seed, worst_seed_for_ours
from eval.break_even import solve_break_even
from eval.segments import compute_segment_compare
from eval.service import run_eval
from eval.benchmark import compare_seed


def test_multi_seed_has_percentiles_and_worst_seed():
    report = run_multi_seed([42, 43, 44, 45], n=80)
    stats = report.delta_net_recovered_stats
    assert stats.n == 4
    assert stats.p10 <= stats.median <= stats.p90 or stats.min == stats.max
    assert report.win_rate_ours >= 0
    assert report.worst_seed_for_ours is not None
    worst, delta = worst_seed_for_ours(report.per_seed)
    assert worst == report.worst_seed_for_ours
    assert delta == report.worst_seed_delta_net_inr


def test_segment_compare_covers_classes():
    pair = compare_seed(42, 200)
    from eval.batch import generate_batch
    from eval.baselines import POLICIES
    from eval.simulate import run_batch

    cases = generate_batch(seed=42, n=200)
    ours = run_batch(seed=42, cases=cases, plan_fn=POLICIES["ours"])
    b2 = run_batch(seed=42, cases=cases, plan_fn=POLICIES["b2"])
    segments = compute_segment_compare(
        cases=cases, ours_outcomes=ours, b2_outcomes=b2, seed=42
    )
    assert segments
    classes = {s.recovery_class for s in segments}
    assert "RETRY_FIXABLE" in classes
    assert "CUSTOMER_ACTION" in classes
    total_n = sum(s.n_cases for s in segments)
    assert total_n == 200

    ca = next(s for s in segments if s.recovery_class == "CUSTOMER_ACTION")
    assert ca.b2.wasted_attempts >= 0
    if ca.b2.retries + ca.b2.contacts > 0 and ca.b2.recoveries == 0:
        assert ca.b2_zero_recovery_with_spend is True


def test_run_eval_persists_segments():
    record = run_eval(seed=42, n=100, labels=["b2", "ours"])
    assert record.segments
    assert record.delta_net_ours_vs_b2_inr is not None


def test_break_even_sms_runs():
    clear_cost_overrides()
    result = solve_break_even(seed=42, n=100, param_key="attempt.sms_dlt", hi=100.0)
    assert result.param_key == "attempt.sms_dlt"
    assert result.default_value == get_cost_value("attempt.sms_dlt")
    clear_cost_overrides()
