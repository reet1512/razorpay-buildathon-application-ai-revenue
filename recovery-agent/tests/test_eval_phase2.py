"""
tests/test_eval_phase2.py — Phase 2 exit checks.

1) Same seed => same batch => same B2 metrics twice
2) Compare path runs without crashing
3) ours policy is registered and runnable
"""

from __future__ import annotations

from eval.baselines import POLICIES, baseline_b2
from eval.batch import generate_batch
from eval.metrics import compute_metrics
from eval.simulate import run_batch


def test_batch_deterministic():
    a = generate_batch(seed=42, n=50)
    b = generate_batch(seed=42, n=50)
    assert [c.model_dump() for c in a] == [c.model_dump() for c in b]


def test_b2_metrics_reproducible():
    """Phase 2 golden exit: identical B2 number on repeat."""
    seed, n = 42, 100
    cases = generate_batch(seed=seed, n=n)

    o1 = run_batch(seed=seed, cases=cases, plan_fn=baseline_b2)
    o2 = run_batch(seed=seed, cases=cases, plan_fn=baseline_b2)

    m1 = compute_metrics(label="b2", seed=seed, cases=cases, outcomes=o1)
    m2 = compute_metrics(label="b2", seed=seed, cases=cases, outcomes=o2)

    assert m1.recovered_inr == m2.recovered_inr
    assert m1.contacts == m2.contacts
    assert m1.recovery_rate == m2.recovery_rate


def test_different_seed_changes_batch():
    a = generate_batch(seed=42, n=30)
    b = generate_batch(seed=43, n=30)
    assert [c.visible.case_key for c in a] != [c.visible.case_key for c in b]


def test_ours_and_baselines_registered():
    for name in ("b0", "b1", "b2", "b3", "ours"):
        assert name in POLICIES


def test_dead_instrument_b2_burns_retries_ours_prefers_link():
    """Sanity: cause-aware stub should not mirror blind ladder on expired cards."""
    cases = generate_batch(seed=7, n=200)
    expired = [c for c in cases if c.visible.failure_reason.value == "card_expired"]
    assert expired, "fixture mix should include card_expired"

    sample = expired[0]
    b2_plan = POLICIES["b2"](sample)
    ours_plan = POLICIES["ours"](sample)

    assert any(a.verb.value == "schedule_retry" for a in b2_plan)
    assert not any(a.verb.value == "schedule_retry" for a in ours_plan)
    assert any(a.verb.value == "send_payment_link" for a in ours_plan)
