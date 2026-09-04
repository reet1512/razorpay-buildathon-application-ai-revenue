# AI Revenue Recovery Agent

[![CI](https://github.com/reet1512/razorpay-buildathon-application-ai-revenue/actions/workflows/ci.yml/badge.svg)](https://github.com/reet1512/razorpay-buildathon-application-ai-revenue/actions/workflows/ci.yml)

**Razorpay /buildathon — Track 03.** Recovering failed subscription payments without
spamming payers or burning fees on retries that cannot succeed.

> **AI proposes. Policy disposes. The ledger remembers.**
> An LLM never moves money. It proposes a bounded action; deterministic policy and
> compliance gates validate, repair, or block it; execution is idempotent; every
> gate decision is written to an append-only ledger.

---

## The problem

A subscription payment fails. Most dunning systems respond with the same fixed
retry ladder regardless of *why* it failed. That is expensive in two directions:

- Retrying an **expired card** or a **revoked mandate** cannot succeed. Every
  attempt costs a gateway fee and erodes issuer trust.
- Retrying **insufficient funds** at the wrong moment fails, while retrying near
  the payer's salary credit often works.
- Messaging the payer repeatedly causes churn, and contacting a **suspected fraud**
  case is a compliance problem, not an optimisation.

Cause-blind recovery therefore loses money on both sides: it wastes attempts where
recovery is impossible and mistimes them where recovery is possible.

## The approach

```
RiskEvent ──▶ Classify ──▶ [ LLM proposes action ] ──▶ validate_proposal
  (webhook)     (cause)      (Ollama, bounded)          (repair illegal)
                                                              │
                                                              ▼
                                                    ┌──────────────────┐
                                                    │  Policy gates    │  fraud · contact window
                                                    │  ALLOW/BLOCK/    │  frequency cap · mandate
                                                    │  REPAIR          │  attempt cap · idempotency
                                                    └──────────────────┘
                                                              │ allowed
                                                              ▼
                                              Execute (sim at scale │ Razorpay at the edge)
                                                              │
                                                              ▼
                                              Append-only ledger  ──▶  Case trail UI
```

The LLM's output is a **proposal**, not a command. `policy/engine.py::validate_proposal`
repairs or rejects anything outside the taxonomy, and the gates in `guard/gates.py`
get the final say. If Ollama is unavailable the system degrades to `rules_fallback`
and keeps working.

## Results

Seeded simulation, **seed 42, n=500**, identical cases for both policies.
`B2` is the baseline: three fixed retries plus one generic nag, for every failure reason.

| | Ours | B2 baseline | Δ |
|---|---:|---:|---:|
| Net recovered | ₹489,604 | ₹382,467 | **+₹107,137** |
| Gross recovered | ₹499,628 | ₹399,796 | +₹99,832 |
| Recovery rate | 74.7% | 59.8% | +14.9 pts |
| Retry attempts | 558 | 959 | −401 |
| Payer contacts | 265 | 386 | −121 |
| Cost of recovery | ₹10,024 | ₹17,329 | −₹7,305 |
| Cost per ₹ recovered | ₹0.020 | ₹0.043 | −53% |

Reproduce exactly:

```bash
python eval/harness.py --benchmark --seed 42 --n 500
```

**Read this before trusting those numbers.** They rank two policies inside our own
simulator under stated assumptions; they are **not** a measurement of merchant
lift. At seed 42 roughly 99% of the gross advantage comes from a single failure
reason (`insufficient_funds`), and the policy's retry timing searches days 1–7 —
which is exactly where the simulator hides the payer's payday. That overlap
inflates the result. We also *lose* on four of eight failure reasons, including
`do_not_honour`.

All of it is written up, with the per-reason table and the offending lines of code,
in **[docs/LIMITATIONS.md](recovery-agent/docs/LIMITATIONS.md)**. It is the most
useful file in this repo for judging whether the engineering is honest.

## Quick start

**Python 3.12+ and one `pip install` is the whole requirement.** No Docker, no LLM,
no Razorpay account, no 5 GB model download. Ollama and Inherent are optional
add-ons — full tiered instructions in **[docs/SETUP.md](recovery-agent/docs/SETUP.md)**.

```bash
git clone https://github.com/reet1512/razorpay-buildathon-application-ai-revenue.git
cd razorpay-buildathon-application-ai-revenue/recovery-agent

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # Windows: copy .env.example .env

pytest -q                        # 154 tests, no external services needed
python -m eval.harness --benchmark --seed 42 --n 500
uvicorn main:app --reload --port 8000
```

Then open http://127.0.0.1:8000/ui and click **Run evaluation** (seed 42, n=500).

> **The Stats screen is empty until you do this.** That is deliberate — the UI
> refuses to render a rupee figure it did not compute — but it looks like a bug if
> you are not expecting it. One click, or one `POST /eval/run`, fills it in.

| URL | What it shows |
|---|---|
| `/ui` | Stats: Ours vs B2 in net INR, from the stored run |
| `/ui/recover` | The agent reasoning over a single case |
| `/cases/{id}` | Real append-only ledger trail for one case |
| `/docs` | OpenAPI |

### Optional add-ons

Both are genuinely optional and independently skippable. The system degrades
cleanly and the UI reports which components are actually live rather than
pretending — see [docs/SETUP.md](recovery-agent/docs/SETUP.md) for full steps.

| Add-on | Gives you | Without it |
|---|---|---|
| **Ollama** (`ollama pull qwen3:8b`) | Live LLM diagnosis and drafting | `rules_fallback`; badge reads "Offline" |
| **Inherent** (separate Docker stack) | RAG over past recovery episodes | Badge reads "RAG DISABLED" |
| **Razorpay test keys** | Real Payment Links | Sim executor; placeholder keys force dry-run |

Neither affects the benchmark or the tests: the batch path uses taxonomy rules on
purpose, so the headline number stays reproducible whether or not a model is
running ([LIMITATIONS.md](recovery-agent/docs/LIMITATIONS.md) §9).

The venv above is the supported path on every platform. A gitignored local
embeddable Python under `tools/` was a development workaround for a broken Windows
install; it is **not** part of the repo, so ignore any `..\tools\python.cmd`
references in older notes.

## Guided tour of the code

The fastest way to review the actual thesis, in reading order:

| # | File | Why it matters |
|---|---|---|
| 1 | [`policy/taxonomy.yaml`](recovery-agent/policy/taxonomy.yaml) | The domain model. Per-cause verbs, retry caps, timing, contact rules |
| 2 | [`policy/engine.py`](recovery-agent/policy/engine.py) | `validate_proposal` — where an illegal LLM action gets repaired or refused |
| 3 | [`guard/gates.py`](recovery-agent/guard/gates.py) | The six gates. Fraud, contact window, frequency, mandate, attempt cap, idempotency |
| 4 | [`guard/pipeline.py`](recovery-agent/guard/pipeline.py) | Gate → execute → ledger, with idempotency rehydrated from the ledger |
| 5 | [`execute/reconcile.py`](recovery-agent/execute/reconcile.py) | Gateway timeout handling: check status before retrying, never double-charge |
| 6 | [`ingest/verify.py`](recovery-agent/ingest/verify.py) | Webhook HMAC, fail-closed by default |
| 7 | [`eval/payer_model.py`](recovery-agent/eval/payer_model.py) | The hidden simulator truth — and the assumptions LIMITATIONS.md attacks |
| 8 | [`eval/costing.py`](recovery-agent/eval/costing.py) | Why the headline is *net* INR, not recovery rate |

## Documentation

| Doc | Contents |
|---|---|
| [SETUP.md](recovery-agent/docs/SETUP.md) | **Running it.** Tier 0 (nothing) → Ollama → Inherent, plus troubleshooting |
| [LIMITATIONS.md](recovery-agent/docs/LIMITATIONS.md) | **What this project does not prove.** Start here |
| [ARCHITECTURE.md](recovery-agent/docs/ARCHITECTURE.md) | Pipeline diagrams and package map |
| [METHODOLOGY.md](recovery-agent/docs/METHODOLOGY.md) | Seeds, payer model, baselines, scoring |
| [COMPLIANCE.md](recovery-agent/docs/COMPLIANCE.md) | Gates, stops, webhook verification, PII rules |
| [SCORING.md](recovery-agent/docs/SCORING.md) | How net INR is computed and why |
| [WHAT_BROKE.md](recovery-agent/docs/WHAT_BROKE.md) | Build failures and what they taught us |
| [DEMO.md](recovery-agent/docs/DEMO.md) | 5-minute walkthrough script |

## What is deliberately not built

Hackathon scope, stated plainly so nobody has to guess whether we missed it or
chose it: no API authentication, no rate limiting, no Alembic migrations
(`create_all` at startup), SQLite instead of Postgres, no metrics or tracing, and
an idempotency check that is check-then-act rather than constraint-backed. The
reasoning and the production fix for each is in
[LIMITATIONS.md](recovery-agent/docs/LIMITATIONS.md) §11–§12.

## Repo layout

| Path | Contents |
|---|---|
| `recovery-agent/` | The application: API, AI, eval, gates, ledger, UI |
| `recovery-agent/docs/` | Architecture, methodology, limitations, compliance |
| `.github/workflows/ci.yml` | Lint, tests, secret scan, benchmark reproducibility |
| `BUILD_PLAN.md` · `BUILD_TECH.md` | Original plan and phase-by-phase tech notes |

**Never commit `.env`.** Test-mode Razorpay keys only; `scripts/check_no_secrets.py`
runs in CI to enforce it.
