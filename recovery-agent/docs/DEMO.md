# Demo + submission guide

## 5-minute video script (from BUILD_PLAN)

| Time | Beat | Show |
|---|---|---|
| 0:00–0:25 | Result | Beat / compare vs B2 on batch (`/ui/batch` or harness) |
| 0:25–1:05 | Idea | Dead vs time-shift vs transient |
| 1:05–1:50 | AI brain | `/agent/run` or case trail diagnosis JSON |
| 1:50–2:40 | Batch | Side-by-side Ours vs B2 INR |
| 2:40–3:20 | Refusal | Gate block row on case page |
| 3:20–3:55 | Trail | Ledger `actor=llm` + gates + outcome |
| 3:55–4:25 | Real edge | `plink_…` in ledger ↔ Razorpay dashboard |
| 4:25–5:00 | Honesty | Assumptions + what AI added |

## Backup if live demo dies

1. `POST /demo/replay` or UI **Open demo case trail** — offline fixture, no Ollama/ngrok.
2. Pre-saved eval run under `data/eval_runs/` or re-run:

```text
..\tools\python.cmd eval\harness.py --compare --seed 42 --n 500 --json > metrics_seed42.json
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

| Slice | What it proves |
|---|---|
| B2 vs `ours` (rules) | Cause-aware policy moves INR / contacts |
| `/agent/run` with Ollama | Diagnosis + structured Action + message |
| `force_fallback: true` | Product still works if LLM is down |
| Gate block demo | AI is bounded |

Batch n=500 INR stays on **rules** (`--policy ours`) so the headline is reproducible. AI is on the critical **demo** path.

## Public GitHub tidy

- [ ] No `.env` in repo
- [ ] README stranger-runnable
- [ ] Link `docs/ARCHITECTURE.md`, `METHODOLOGY.md`, `COMPLIANCE.md`, `WHAT_BROKE.md`
- [ ] Test mode only; no live keys in screenshots if avoidable
