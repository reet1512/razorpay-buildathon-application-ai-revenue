"""
eval/service.py — run compare/single batch for API + UI (metrics from metrics.py only).
"""

from __future__ import annotations

from typing import Optional

from config.costs import clear_cost_overrides, set_cost_overrides
from eval.baselines import POLICIES
from eval.batch import generate_batch, summarize_mix
from eval.benchmark import DEFAULT_MULTI_SEEDS, MultiSeedReport, run_multi_seed
from eval.gate_estimate import count_gate_blocks
from eval.metrics import BatchMetrics, compute_metrics
from eval.run_store import EvalRunRecord, EvalRunStore, get_store, new_run_id, utc_now_iso
from eval.segments import compute_segment_compare
from eval.simulate import run_batch


def run_eval(
    *,
    seed: int = 42,
    n: int = 200,
    labels: Optional[list[str]] = None,
    store: Optional[EvalRunStore] = None,
    cost_overrides: Optional[dict[str, float]] = None,
) -> EvalRunRecord:
    """
    Generate one batch, score each label, estimate gate blocks, persist.
    Default labels: b2 + ours (Batch UI headline pair).
    """
    labels = labels or ["b2", "ours"]
    for lab in labels:
        if lab not in POLICIES:
            raise ValueError(f"unknown label {lab}; choose from {sorted(POLICIES)}")

    overrides = dict(cost_overrides or {})
    if overrides:
        set_cost_overrides(overrides)
    try:
        cases = generate_batch(seed=seed, n=n)
        mix = summarize_mix(cases)
        metrics: list[BatchMetrics] = []
        gate_blocks: dict[str, int] = {}
        ours_out = None
        b2_out = None

        for lab in labels:
            plan_fn = POLICIES[lab]
            outcomes = run_batch(seed=seed, cases=cases, plan_fn=plan_fn)
            if lab == "ours":
                ours_out = outcomes
            elif lab == "b2":
                b2_out = outcomes
            m = compute_metrics(
                label=lab,
                seed=seed,
                cases=cases,
                outcomes=outcomes,
                plan_fn=plan_fn,
            )
            metrics.append(m)
            gate_blocks[lab] = count_gate_blocks(cases, plan_fn)

        segments = []
        if ours_out is not None and b2_out is not None:
            segments = compute_segment_compare(
                cases=cases,
                ours_outcomes=ours_out,
                b2_outcomes=b2_out,
                seed=seed,
            )

        gross_delta = None
        net_delta = None
        by_label = {m.label: m for m in metrics}
        if "ours" in by_label and "b2" in by_label:
            gross_delta = round(by_label["ours"].gross_delta_inr(by_label["b2"]), 2)
            net_delta = round(by_label["ours"].net_delta_inr(by_label["b2"]), 2)

        record = EvalRunRecord(
            run_id=new_run_id(),
            created_at=utc_now_iso(),
            seed=seed,
            n=n,
            labels=labels,
            metrics=metrics,
            gate_blocks=gate_blocks,
            decline_mix=mix,
            delta_ours_vs_b2_inr=gross_delta,
            delta_net_ours_vs_b2_inr=net_delta,
            segments=segments,
            cost_overrides=overrides,
        )
        return (store or get_store()).save(record)
    finally:
        if overrides:
            clear_cost_overrides()


def run_multi_seed_report(
    *,
    seeds: Optional[list[int]] = None,
    n: int = 200,
) -> MultiSeedReport:
    """Multi-seed distribution for UI / CLI (Task 4)."""
    seed_list = list(seeds or DEFAULT_MULTI_SEEDS)
    return run_multi_seed(seed_list, n)
