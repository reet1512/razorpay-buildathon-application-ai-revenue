"""
harness.py — CLI scoreboard entrypoint.

Examples (from recovery-agent/):
  python -m eval.harness --baseline b2 --seed 42 --n 500
  python -m eval.harness --policy ours --seed 42 --n 500
  python -m eval.harness --compare --seed 42 --n 500
  python -m eval.harness --benchmark --seed 42 --n 1000
  python -m eval.harness --benchmark --multi-seed --n 200
  python -m eval.harness --benchmark --seeds 42-51 --n 1000

Teaching:
- This file should stay thin: parse args -> generate batch -> simulate -> metrics -> print.
- Rigorous Ours vs B2 lives in eval.benchmark + eval.report (scoring unchanged).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from eval.baselines import POLICIES
from eval.batch import generate_batch, summarize_mix
from eval.benchmark import (
    DEFAULT_MULTI_SEEDS,
    HEADLINE_SEED,
    compare_seed,
    parse_seeds_arg,
    run_multi_seed,
)
from eval.metrics import compute_metrics, format_metrics
from eval.report import cases_section, format_multi_seed, format_seed_pair
from eval.simulate import run_batch


def run_label(label: str, seed: int, n: int):
    if label not in POLICIES:
        raise SystemExit(f"Unknown policy/baseline '{label}'. Choose from: {sorted(POLICIES)}")
    cases = generate_batch(seed=seed, n=n)
    outcomes = run_batch(seed=seed, cases=cases, plan_fn=POLICIES[label])
    metrics = compute_metrics(
        label=label,
        seed=seed,
        cases=cases,
        outcomes=outcomes,
        plan_fn=POLICIES[label],
    )
    return cases, outcomes, metrics


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Recovery Agent eval harness — measured INR on a seeded batch"
    )
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument(
        "--baseline",
        choices=["b0", "b1", "b2", "b3"],
        help="Run a cause-blind baseline",
    )
    g.add_argument(
        "--policy",
        choices=["ours"],
        help="Run our cause-aware taxonomy policy (batch path; not live LLM)",
    )
    g.add_argument(
        "--compare",
        action="store_true",
        help="Run b0,b1,b2,ours side by side on the same seed (legacy)",
    )
    g.add_argument(
        "--benchmark",
        action="store_true",
        help="Rigorous Ours vs B2 report (same cases; optional multi-seed)",
    )
    p.add_argument(
        "--seed",
        type=int,
        default=HEADLINE_SEED,
        help=f"RNG seed (default {HEADLINE_SEED} = canonical headline)",
    )
    p.add_argument(
        "--n",
        type=int,
        default=500,
        help="Batch size (default 500). Supports 200 and 1000+. Larger N ≠ better policy.",
    )
    p.add_argument(
        "--multi-seed",
        action="store_true",
        help=f"With --benchmark: run seeds {DEFAULT_MULTI_SEEDS[0]}-{DEFAULT_MULTI_SEEDS[-1]}",
    )
    p.add_argument(
        "--seeds",
        type=str,
        default=None,
        help="With --benchmark: seed list '42,43' or range '42-51' (overrides --multi-seed)",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Print metrics/report as JSON",
    )
    p.add_argument(
        "--show-mix",
        action="store_true",
        help="Also print failure-reason mix counts",
    )
    p.add_argument(
        "--show-cases",
        type=int,
        default=0,
        metavar="K",
        help="With --benchmark: print top K per-case rows (0=skip)",
    )
    p.add_argument(
        "--sort-cases",
        choices=["b2_advantage", "ours_advantage", "failure_reason", "delta_inr"],
        default="b2_advantage",
        help="Sort key for --show-cases",
    )
    p.add_argument(
        "--failure-reason",
        type=str,
        default=None,
        help="Filter --show-cases to one FailureReason value",
    )
    return p


def _run_benchmark(args: argparse.Namespace) -> int:
    if args.n <= 0:
        raise SystemExit("--n must be positive")

    if args.seeds:
        seeds = parse_seeds_arg(args.seeds)
    elif args.multi_seed:
        seeds = list(DEFAULT_MULTI_SEEDS)
    else:
        seeds = [args.seed]

    if len(seeds) == 1:
        result = compare_seed(seeds[0], args.n)
        if args.show_mix:
            cases = generate_batch(seed=seeds[0], n=args.n)
            print("decline_mix:", summarize_mix(cases))
        if args.json:
            payload = result.model_dump(mode="json")
            if args.show_cases <= 0:
                payload.pop("cases", None)
            print(json.dumps(payload, indent=2))
        else:
            print(format_seed_pair(result))
            if args.show_cases > 0:
                print()
                print(
                    cases_section(
                        result,
                        sort_by=args.sort_cases,
                        failure_reason=args.failure_reason,
                        limit=args.show_cases,
                    )
                )
        return 0

    report = run_multi_seed(seeds, args.n)
    if args.json:
        payload = report.model_dump(mode="json")
        # Drop bulky per-case arrays unless requested
        if args.show_cases <= 0:
            for p in payload.get("per_seed", []):
                p.pop("cases", None)
        print(json.dumps(payload, indent=2))
    else:
        print(format_multi_seed(report))
        if args.show_cases > 0:
            print()
            print(
                cases_section(
                    report,
                    sort_by=args.sort_cases,
                    failure_reason=args.failure_reason,
                    limit=args.show_cases,
                )
            )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    seed, n = args.seed, args.n

    if args.benchmark:
        return _run_benchmark(args)

    if args.compare:
        labels = ["b0", "b1", "b2", "ours"]
        rows = []
        cases = generate_batch(seed=seed, n=n)
        if args.show_mix:
            print("decline_mix:", summarize_mix(cases))
        for label in labels:
            outcomes = run_batch(seed=seed, cases=cases, plan_fn=POLICIES[label])
            m = compute_metrics(
                label=label,
                seed=seed,
                cases=cases,
                outcomes=outcomes,
                plan_fn=POLICIES[label],
            )
            rows.append(m)
        if args.json:
            print(json.dumps([r.model_dump() for r in rows], indent=2))
        else:
            for m in rows:
                print("-" * 40)
                print(format_metrics(m))
            ours = next(r for r in rows if r.label == "ours")
            b2 = next(r for r in rows if r.label == "b2")
            print("-" * 40)
            print(f"ours gross delta vs b2 (INR): {ours.gross_delta_inr(b2):,.2f}")
            print(f"ours net delta vs b2 (INR): {ours.net_delta_inr(b2):,.2f}")
            print(
                f"ours contacts/recovery vs b2: "
                f"{ours.contacts_per_recovery} vs {b2.contacts_per_recovery}"
            )
            print(
                "Note: headline winner by net_recovered_inr; see docs/SCORING.md. "
                "Use --benchmark for multi-seed / scenario / per-case."
            )
        return 0

    label = args.baseline or args.policy
    cases, _outcomes, metrics = run_label(label, seed=seed, n=n)
    if args.show_mix:
        print("decline_mix:", summarize_mix(cases))
    if args.json:
        print(json.dumps(metrics.model_dump(), indent=2))
    else:
        print(format_metrics(metrics))
    return 0


if __name__ == "__main__":
    sys.exit(main())
