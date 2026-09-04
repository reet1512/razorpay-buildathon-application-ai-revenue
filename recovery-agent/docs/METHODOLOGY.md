# Phase 2 methodology — how we measure (be honest on stage)

## What this document is

The eval harness prints rupee numbers from a **seeded simulator**.
Those numbers are for **ranking policies**, not claiming live merchant A/B lift.

Line for judges:

> Simulated at scale, real at the edges. Same seed, same batch, stated assumptions.

## Batch generation

- Command: `python -m eval.harness --baseline b2 --seed 42 --n 500`
- Same `seed` + `n` => identical batch (determinism contract).
- Decline mix weights live in `eval/batch.py` (`DECLINE_WEIGHTS`).
- Mix is **estimated** for the hackathon from public industry commentary patterns,
  **not** from Razorpay private data.

## Hidden payer model (not visible to policies)

For each payer we store latent fields in `HiddenPayerTruth`:

| Field | Meaning |
|---|---|
| `instrument_valid` | Can silent retries ever work? Dead cards/mandates => false |
| `true_credit_day` | Salary-like credit clustering (days 1-7 drawn) |
| `natural_recovery_prob` | Chance B0 recovers with no merchant action |
| `base_contact_response_prob` | Chance a message/link works before fatigue |
| `retry_success_if_funded` | Chance a retry works when funds+instrument OK |

Policies only see `VisibleCase` (failure reason, amount, rail, noisy observed credit day).

## Fatigue curve (assumption)

Each prior contact multiplies response probability by **0.55**:

```text
p(contact k) = base * (0.55 ** (k-1))
```

This is the most consequential assumption. If challenged: say so, offer to re-run
with a different factor.

## Contact / retry success priors (updated 2026-08-26)

`eval/payer_model.py` draws `HiddenPayerTruth` by failure reason. Headline knobs:

| Reason family | `base_contact_response_prob` | `retry_success_if_funded` |
|---|---|---|
| Dead instrument (expired/token/mandate) | 0.58 | 0.0 |
| NSF | 0.22 | 0.92 |
| Transient issuer/gateway | 0.12 | 0.86 |
| Fraud | 0.05 | 0.05 |
| Ambiguous / DNH | 0.28 | 0.48 |

Dead-instrument recovery is **contact-only** (pay link / mandate update). NSF/transient
recovery is **silent-retry-only** inside the funds window (except ambiguous link path).

## Funds availability (assumption)

For NSF-like failures, funds exist on `true_credit_day` and the next two days
in a 1..28 day-of-month circle. Transient rail failures can succeed outside that window.

## Salary-window timing (Ours)

`policy/timing.py` expands NSF offsets when `observed_credit_day` is missing or noisy,
and covers credit-day +2. Transient uses day 0 and day 1. Dead instruments get an
immediate link plus a day-3 follow-up link (zero retries).
## Baselines

| Id | Behavior |
|---|---|
| B0 | No action (natural recovery only) |
| B1 | One immediate retry |
| B2 | Retries on day 0/2/5 + generic nag on day 1 (cause-blind) |
| B3 | Aggressive retries + multiple contacts (optional) |
| ours | Cause-aware taxonomy policy (YAML); AI agent is separate demo path |

**B2 in one sentence:** three fixed retries plus one generic nag, same ladder for every failure reason.

## Metrics (only computed in `eval/metrics.py`)

- `at_risk_inr` / `recovered_inr`
- `recovery_rate = recovered / at_risk`
- `contacts_per_recovery`
- retries, recoveries, natural_recoveries

**Winner definition (frozen):** higher `recovered_inr`. Contacts/retries do not
change the winner. Full write-up: [`docs/SCORING.md`](SCORING.md).

### Rigorous Ours vs B2 CLI

```bash
# Canonical headline (seed 42)
python -m eval.harness --benchmark --seed 42 --n 500

# Larger N (less sampling noise — does NOT improve the policy)
python -m eval.harness --benchmark --seed 42 --n 1000

# Multi-seed (avoid cherry-picking) — SUPPORTED BUT NOT PUBLISHED
python -m eval.harness --benchmark --multi-seed --n 200
python -m eval.harness --benchmark --seeds 42-51 --n 1000 --show-cases 20
```

> **Honest status of the multi-seed commands above:** they work, but **we never
> published the sweep.** Every result in this repository is seed 42, at
> n=200/500/1000. Single-seed reporting cannot distinguish a real effect from a
> favourable draw, and this is the cheapest outstanding fix to our credibility.
> Tracked in [LIMITATIONS.md](LIMITATIONS.md) §2.8.

## Phase 5 AI (Ollama qwen3:8b)

- Live model used on `/agent/run` for diagnosis, action proposal, message draft.
- Policy `validate_proposal` always bounds the verb.
- If Ollama is down: `rules_fallback` (exit check).
- Seeded batch INR numbers (`eval.harness --policy ours`) stay on **taxonomy rules**
  so the headline metric remains reproducible. The AI contribution is therefore
  shown qualitatively through demo cases, **not** as a rupee figure — no AI-vs-rules
  ablation was run ([LIMITATIONS.md](LIMITATIONS.md) §3.3).

## Gate blocks on the batch UI

`eval/gate_estimate.py` walks each policy plan through the same gate functions
(daytime IST clock) and counts refusals. This is a **safety-pressure** counter for
the Batch screen — how often each policy would be refused — and money metrics
still come only from `compute_metrics`.

It is not a regulatory measure: no RBI or card-network rule is enforced anywhere
in this codebase ([LIMITATIONS.md](LIMITATIONS.md) §4.4–§4.5).

## Ablation (what to say on stage)

> These are **demonstrations, not measurements.** None of the rows below isolates
> the LLM's causal contribution, and no such experiment exists in this repo. The
> only quantified comparison is policy-vs-policy on the deterministic batch.

| Comparison | Command / surface | Claim |
|---|---|---|
| Fixed ladder vs cause-aware | `eval.harness --compare --seed 42 --n 500` | Ranking under stated assumptions |
| Rules-only batch | `--policy ours` | Reproducible INR |
| Live AI | `POST /agent/run` | Diagnosis + Action JSON + message |
| LLM down | `"force_fallback": true` | Product still works |
| Refusal | Case trail / `/guard/check` | Gates can veto AI |

Honest line: *AI is significant on the case path; batch money ranking is rules + seed so judges can re-run it.*

## Seeds we care about

| Seed | n | Use |
|---|---|---|
| 42 | 500 | Headline compare (video / README) |
| 42 | 200 | Faster UI `/eval/run` default |
| 7 | small | Ad-hoc policy sanity tests |
