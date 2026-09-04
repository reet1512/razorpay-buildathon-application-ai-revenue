# Demo + submission guide

## 5-minute video script

| Time | Beat | Show |
|---|---|---|
| 0:00–0:25 | Thesis | "AI proposes, policy disposes." The LLM cannot authorise money movement |
| 0:25–1:05 | Idea | Dead vs time-shiftable vs transient vs prohibited — why blind retry loses both ways |
| 1:05–1:50 | AI brain | `/agent/run` or case trail: diagnosis + structured Action JSON |
| 1:50–2:25 | **Repair** | LLM proposes `schedule_retry` on `card_expired` → validator rewrites to `send_payment_link` |
| 2:25–3:00 | **Refusal** | Fraud demo: `prohibited_recovery` blocks *before* execution; gate row in the ledger |
| 3:00–3:30 | Trail | `/cases/{id}`: all six gate verdicts + outcome, from the database |
| 3:30–4:00 | Batch | Ours vs B2 net INR — **say "in simulation"** |
| 4:00–4:25 | Real edge | `plink_…` in ledger ↔ Razorpay dashboard |
| 4:25–5:00 | Honesty | What we measured, what we did not |

### Wording that keeps the video honest

Two sentences worth scripting verbatim, because getting them wrong is the easiest
way to lose credibility with a payments reviewer:

> "This rupee figure comes from the **deterministic policy** on a seeded
> simulation — not from the LLM, and not from production traffic."

> "The LLM's contribution here is diagnosis and proposal. We have **not** measured
> its incremental value in rupees, and we don't claim to."

For the closing honesty beat, the strongest 20 seconds available:

- ~99% of the gross edge comes from one failure reason, `insufficient_funds`.
- Our retry window is days 1–7; the simulator hides payday in days 1–7. That
  overlap inflates the result.
- We *lose* to the baseline on the ambiguous class.
- Everything published is a single seed.

That is a better closing note than a bigger number, and it is all in
[LIMITATIONS.md](LIMITATIONS.md).

### Optional strong additions if time allows

Both are quick, visual, and hard to fake:

```text
# Duplicate execution is refused (idempotency, rebuilt from the ledger)
POST /execute/run  ×2 with the same operation → "blocked_by": "idempotency"

# Unsigned webhooks are rejected (fail-closed)
POST /webhooks/razorpay with no signature → 401
```

## Backup if live demo dies

1. `POST /demo/replay` or UI **Open demo case trail** — offline fixture, no Ollama/ngrok.
2. Pre-saved eval run under `data/eval_runs/` or re-run:

```text
python -m eval.harness --compare --seed 42 --n 500 --json > metrics_seed42.json
```

3. Record a backup take of `/ui/batch` + `/ui/cases/...` before the event.

Fixture source: `fixtures/demo_replay.json`.

## Live Razorpay edge (test mode)

1. Copy `.env.example` → `.env`; set real `rzp_test_…` keys; `RAZORPAY_DRY_RUN=0`.
2. Start API; create link:

```text
POST /execute/run
{"raw_error_reason":"card_expired","verb":"send_payment_link","mode":"razorpay"}
```

3. Confirm `external_id` (`plink_…`) in response and Razorpay dashboard.
4. Optional: ngrok → dashboard webhook → `POST /webhooks/razorpay` with secret.

## Ablation (say this honestly)

| Slice | What it proves | What it does **not** prove |
|---|---|---|
| B2 vs `ours` (rules) | Cause-aware policy moves net INR under our simulator's assumptions | Merchant lift; production recovery |
| `/agent/run` with Ollama | Diagnosis + structured Action + message | That the LLM improves recovery |
| `force_fallback: true` | Product still works if the LLM is down | — |
| Gate block demo | AI is bounded and refusal is auditable | Blanket compliance coverage |

Batch n=500 INR stays on **rules** (`--policy ours`) so the headline is
reproducible. AI is on the **case/demo** path only.

None of these rows isolates the LLM's causal contribution — no such experiment
exists in this repo ([LIMITATIONS.md](LIMITATIONS.md) §3.3). Present them as
demonstrations, not measurements.

## Public GitHub tidy

- [ ] No `.env` in repo
- [ ] README stranger-runnable
- [ ] Link `docs/ARCHITECTURE.md`, `METHODOLOGY.md`, `COMPLIANCE.md`, `WHAT_BROKE.md`
- [ ] Test mode only; no live keys in screenshots if avoidable
