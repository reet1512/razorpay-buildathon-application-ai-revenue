# Architecture — Recovery Agent

Razorpay /buildathon Track 03 · AI Revenue Recovery.

## One-line design

**AI proposes → policy/gates dispose → ledger records → sim measures at scale, Razorpay proves at the edge.**

## End-to-end map

```mermaid
flowchart TB
  subgraph DayN[One real failure]
    A[Razorpay test payment fails] --> B[Webhook]
    B --> C[Pipeline]
    C --> D[Payment Link created]
    D --> E[Ledger has plink_id]
  end

  subgraph Batch[One measured claim]
    F[seed 42 batch 500] --> G[B2 vs Ours]
    G --> H[metrics.json]
    H --> I[Batch UI + video]
  end
```

Submission needs **both** subgraphs.

## Pipeline (product path)

```mermaid
flowchart LR
  WH[Webhook / demo] --> RE[RiskEvent]
  RE --> AI[AI diagnose + propose]
  AI --> POL[Policy validate]
  POL --> G[Gates]
  G -->|pass| EX[Executor sim or Razorpay]
  G -->|block| LED[Ledger only]
  EX --> LED
  LED --> UI[Case trail UI]
```

## Truth model (three layers)

| Layer | Object | Who may read it |
|---|---|---|
| Observed | `RiskEvent` / `VisibleCase` | Agent, policy, UI |
| Decision / audit | `ledger_entries` | Ops, judges, demos |
| Hidden sim | `HiddenPayerTruth` | Eval simulator **only** |

Policies that peek at hidden truth cheat the metric.

## Package map

| Path | Role |
|---|---|
| `ledger/` | Persist cases + append-only audit |
| `ingest/` | Signature verify + normalise → `RiskEvent` |
| `diagnose/` + `policy/` | Taxonomy, scoring, rules fallback / validator |
| `ai/` | Ollama `qwen3:8b` diagnose / propose / message |
| `guard/` | Gates + stops (can refuse AI) |
| `execute/` | Sim adapter + Razorpay Payment Links |
| `eval/` | Seeded batch, baselines, metrics (INR) |
| `demo/` | Offline fixture replay for video backup |
| `api/` + `templates/` | HTTP + Batch/Case UI |

## Closed Action verbs

```text
schedule_retry | send_payment_link | request_mandate_update | escalate_human
```

The LLM cannot invent channels or verbs outside this set. `PolicyEngine.validate_proposal` is the hard bound.

## Dual execution

| Mode | Use |
|---|---|
| `sim` | n=500 scoreboard, CI, reproducible INR |
| `razorpay` | Test-mode Payment Link; store `plink_…` in ledger |

Never call an adapter when a gate blocks (`execute/service.py` → `guard_and_maybe_execute`).

## Key HTTP surface

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Ops |
| POST | `/webhooks/razorpay` | Signed ingest |
| POST | `/agent/run` | Live AI path |
| POST | `/guard/check` | Gate refusal demo |
| POST | `/execute/run` | Guard + adapter |
| POST | `/eval/run` | Batch metrics |
| GET | `/cases/{id}` | Case + ledger JSON |
| POST | `/demo/replay` | Offline trail |
| GET | `/ui/batch` | Scoreboard screen |
| GET | `/ui/cases/{id}` | Timeline screen |

See also: [COMPLIANCE.md](COMPLIANCE.md), [METHODOLOGY.md](METHODOLOGY.md).
