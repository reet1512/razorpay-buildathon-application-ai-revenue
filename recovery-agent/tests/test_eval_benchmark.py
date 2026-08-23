"""
tests/test_eval_benchmark.py — rigorous Ours vs B2 eval contracts.

Does not change policy logic; only checks measurement integrity.
"""

from __future__ import annotations

from eval.baselines import POLICIES
from eval.batch import generate_batch
from eval.benchmark import (
    HEADLINE_SEED,
    compare_seed,
    filter_sort_cases,
    parse_seeds_arg,
    run_multi_seed,
)
from eval.metrics import paise_to_inr
from eval.simulate import run_batch


def test_same_seed_n_identical_cases():
    a = generate_batch(seed=HEADLINE_SEED, n=80)
    b = generate_batch(seed=HEADLINE_SEED, n=80)
    assert [c.model_dump() for c in a] == [c.model_dump() for c in b]


def test_ours_and_b2_receive_identical_cases():
    seed, n = HEADLINE_SEED, 60
    cases = generate_batch(seed=seed, n=n)
    keys = [c.visible.case_key for c in cases]
    # Policies only read VisibleCase; both see the same ordered batch.
    ours = run_batch(seed=seed, cases=cases, plan_fn=POLICIES["ours"])
    b2 = run_batch(seed=seed, cases=cases, plan_fn=POLICIES["b2"])
    assert [o.case_key for o in ours] == keys
    assert [o.case_key for o in b2] == keys


def test_changing_seed_changes_batch_keeps_n():
    n = 40
    a = generate_batch(seed=42, n=n)
    b = generate_batch(seed=43, n=n)
    assert len(a) == len(b) == n
    assert [c.visible.case_key for c in a] != [c.visible.case_key for c in b]


def test_increasing_n_increases_count_not_policy():
    small = generate_batch(seed=42, n=25)
    large = generate_batch(seed=42, n=100)
    assert len(small) == 25
    assert len(large) == 100
    # Prefix of larger batch matches smaller when same seed (same RNG stream start)
    assert [c.model_dump() for c in large[:25]] == [c.model_dump() for c in small]
    # Policy callable identity unchanged
    assert POLICIES["ours"] is POLICIES["ours"]
    sample = large[0]
    assert POLICIES["ours"](sample) == POLICIES["ours"](sample)


def test_seed_42_deterministic_metrics():
    r1 = compare_seed(HEADLINE_SEED, 100)
    r2 = compare_seed(HEADLINE_SEED, 100)
    assert r1.ours.recovered_inr == r2.ours.recovered_inr
    assert r1.b2.recovered_inr == r2.b2.recovered_inr
    assert r1.delta_recovered_inr == r2.delta_recovered_inr
    assert r1.delta_net_recovered_inr == r2.delta_net_recovered_inr
    assert r1.winner == r2.winner


def test_per_case_aligned_and_sums_to_batch():
    seed, n = 42, 75
    result = compare_seed(seed, n)
    assert len(result.cases) == n
    assert {r.case_key for r in result.cases} == {
        c.visible.case_key for c in generate_batch(seed=seed, n=n)
    }
    ours_paise = sum(r.ours_recovered_paise for r in result.cases)
    b2_paise = sum(r.b2_recovered_paise for r in result.cases)
    assert abs(paise_to_inr(ours_paise) - result.ours.recovered_inr) < 0.02
    assert abs(paise_to_inr(b2_paise) - result.b2.recovered_inr) < 0.02
    assert result.ours.recoveries == sum(1 for r in result.cases if r.ours_recovered)
    assert result.b2.recoveries == sum(1 for r in result.cases if r.b2_recovered)
    assert result.ours.retries == sum(r.ours_retries for r in result.cases)
    assert result.b2.retries == sum(r.b2_retries for r in result.cases)


def test_filter_sort_cases():
    result = compare_seed(42, 80)
    b2_adv = filter_sort_cases(result.cases, sort_by="b2_advantage", limit=5)
    ours_adv = filter_sort_cases(result.cases, sort_by="ours_advantage", limit=5)
    assert len(b2_adv) == 5
    assert b2_adv[0].delta_inr <= b2_adv[-1].delta_inr
    assert ours_adv[0].delta_inr >= ours_adv[-1].delta_inr
    expired = filter_sort_cases(
        result.cases, sort_by="failure_reason", failure_reason="card_expired"
    )
    assert all(r.failure_reason == "card_expired" for r in expired)


def test_scenario_breakdown_uses_existing_taxonomy():
    result = compare_seed(42, 100)
    reasons = {s.failure_reason for s in result.scenarios}
    # Must be subset of FailureReason values — no invented labels
    allowed = {
        "insufficient_funds",
        "issuer_transient",
        "gateway_timeout",
        "card_expired",
        "token_invalid",
        "mandate_revoked",
        "risk_fraud",
        "do_not_honour",
    }
    assert reasons <= allowed
    assert sum(s.n_cases for s in result.scenarios) == 100


def test_multi_seed_aggregates():
    report = run_multi_seed([42, 43, 44], n=50)
    assert report.n == 50
    assert report.seeds == [42, 43, 44]
    assert report.total_cases == 150
    assert report.seeds_won_ours + report.seeds_won_b2 + report.seeds_tied == 3
    assert report.headline_seed == 42
    # Pooled recovered matches sum of seeds
    assert abs(
        report.ours_total_recovered_inr
        - sum(p.ours.recovered_inr for p in report.per_seed)
    ) < 0.02
    assert "net_recovered_inr" in report.scoring_winner
    assert "config/costs.json" in report.efficiency.note or "net_recovered_inr" in report.efficiency.note


def test_parse_seeds_arg():
    assert parse_seeds_arg("42-45") == [42, 43, 44, 45]
    assert parse_seeds_arg("42, 44") == [42, 44]
    assert parse_seeds_arg("7") == [7]


def test_n_200_and_1000_supported():
    for n in (200, 1000):
        cases = generate_batch(seed=42, n=n)
        assert len(cases) == n
    # Spot-check compare at n=200 (full 1000 left to CLI)
    r = compare_seed(42, 200)
    assert r.n == 200
    assert r.ours.n == 200 and r.b2.n == 200
