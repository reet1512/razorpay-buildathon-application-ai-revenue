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

## Funds availability (assumption)

For NSF-like failures, funds exist on `true_credit_day` and the next two days
in a 1..28 day-of-month circle. Transient rail failures can succeed outside that window.

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

## Phase 5 AI (Ollama qwen3:8b)

- Live model used on `/agent/run` for diagnosis, action proposal, message draft.
- Policy `validate_proposal` always bounds the verb.
- If Ollama is down: `rules_fallback` (exit check).
- Seeded batch INR numbers (`eval.harness --policy ours`) stay on **taxonomy rules**
  so the headline metric remains reproducible. Report AI contribution via demo cases
  + ablation notes, not by making n=500 non-deterministic.

## Gate blocks on the batch UI

`eval/gate_estimate.py` walks each policy plan through the same gate functions
(daytime IST clock) and counts refusals. This is a **compliance pressure**
counter for the Batch screen — money metrics still come only from `compute_metrics`.

## Ablation (what to say on stage)

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
