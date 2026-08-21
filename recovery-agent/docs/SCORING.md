# Scoring / reward definition (evaluation)

This document freezes what “winning” means in the Recovery Agent eval harness.
**Do not silently change these formulas** without updating this file and calling
it out in the PR.

## Winner (primary)

**Winner = higher `recovered_inr`.**

```text
delta = ours.recovered_inr - b2.recovered_inr
winner = ours if delta > 0 else b2 if delta < 0 else tie
```

Computed in `eval/metrics.py` (`BatchMetrics.net_vs`) and used by
`eval/benchmark.py`.

### What counts as recovered

- Simulator plays each policy’s planned actions against hidden payer truth
  (`eval/simulate.py` + `eval/payer_model.py`).
- On first successful retry/contact (or natural recovery for empty plans),
  the case contributes `amount_paise` to recovered.
- `recovered_inr = sum(recovered_paise) / 100`
- `recovery_rate = recovered_inr / at_risk_inr`

## What does **not** change the winner

These are reported for diagnosis / efficiency, **not** folded into a net score:

| Field | Meaning |
|---|---|
| `retries` | Silent retry attempts used |
| `contacts` | Nags / payment links / mandate updates |
| `contacts_per_recovery` | Friction proxy |
| Gate block estimates | Compliance pressure (`eval/gate_estimate.py`) |

There is **no** monetary retry cost, spam penalty, or churn cost in the
simulator today. An “economic/efficiency” view may show contacts/retries, but
must **not** invent penalty weights to make Ours beat B2.

## Headline benchmark

| Knob | Canonical value | Notes |
|---|---|---|
| Seed | **42** | Fixed reference; changing seed ≠ better model |
| N | 200 (UI) / 500–1000 (CLI) | Larger N = less sampling noise, not a better policy |

Multi-seed reports (e.g. 42–51) exist to **avoid cherry-picking** a lucky seed.
Seed 42 remains the single-seed headline.

## Why raw INR can favor B2

B2 schedules three retries + one generic nag on **every** failure reason.
Ours is cause-aware and often refuses retries on dead instruments / risk.
Under a reward that only counts recovered rupees and ignores contact friction,
the spray ladder can win raw INR. Scenario + per-case breakdowns exist to show
**where** that happens — not to retune the agent in this eval task.
