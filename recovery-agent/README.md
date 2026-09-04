# Recovery Agent

**Razorpay /buildathon — Track 03: AI Revenue Recovery**

When a subscription payment fails, blind retry ladders waste fees and spam payers.
This agent classifies the failure cause, lets **AI propose** a bounded action, lets
**policy and gates refuse** unsafe moves, executes via **sim (at scale)** or
**Razorpay test Payment Links (at the edge)**, and reports results in **net INR on
a seeded batch**.

> AI proposes. Policy disposes. The ledger remembers.

Project overview, headline numbers, and a guided tour of the code are in the
[root README](../README.md). **Read [docs/LIMITATIONS.md](docs/LIMITATIONS.md)
before trusting any number in this repo.**

## Setup

Python 3.12+. Sim mode needs no Razorpay keys, no LLM, and no Docker.
Full tiered instructions, including Ollama and Inherent, are in
**[docs/SETUP.md](docs/SETUP.md)**.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # Windows: copy .env.example .env
```

The venv above is the supported path on Windows, macOS, and Linux.

<details>
<summary>Windows note: local embeddable runtime</summary>

Development happened partly on a machine with a broken system Python, using an
embeddable runtime under `../tools/python312/` driven by `..\tools\python.cmd`.
That directory is **gitignored and not part of this repository** — if you see
`..\tools\python.cmd` in older docs, substitute `python` from the venv.

One quirk worth knowing if you ever reproduce that setup: the embeddable
runtime's `._pth` excludes the working directory, so `python -m eval.harness`
fails there and you need the script form `python eval/harness.py`. That quirk is
specific to the embeddable runtime — on a normal Python install, use `-m`. Full
story: [docs/WHAT_BROKE.md](docs/WHAT_BROKE.md) §1 and §10.
</details>

## Verify

```bash
pytest -q                                          # 154 tests, no external deps
python scripts/check_no_secrets.py                 # no live-looking keys in source
python -m eval.harness --benchmark --seed 42 --n 500
```

The benchmark is deterministic: same seed, same numbers, on any machine. CI runs
all three on every push.

## Run

```bash
uvicorn main:app --reload --port 8000
```

| URL | What it shows |
|---|---|
| `/ui` | Stats. **Empty until you run an evaluation** — no pre-filled numbers |
| `/ui/recover` | The agent reasoning over a single case |
| `/ui/batch` | Batch evaluation detail |
| `/cases/{id}` | Real ledger trail for one case |
| `/docs` | OpenAPI |
| `/health` | Liveness |

Screens under `/ui/cases` and `/ui/intelligence` (including
`/ui/intelligence/strategies` and `/ui/intelligence/historical`) are product
mock-ups and carry an "Illustrative data" banner. Measured values appear only on
`/ui` and in real case trails.

## Optional: live AI

```bash
ollama pull qwen3:8b
ollama serve
```

Check with `GET /agent/health`, then:

```bash
POST /agent/run
{"raw_error_reason": "card_expired", "amount_paise": 49900}
```

Without Ollama the agent returns `proposed_by: rules_fallback` and everything else
behaves identically. The LLM is not in the batch path — see
[docs/LIMITATIONS.md](docs/LIMITATIONS.md) §9 for why, and what that costs us.

## Optional: real Payment Link (test mode)

Put test-mode keys in `.env` and set `RAZORPAY_DRY_RUN=0`:

```bash
POST /execute/run
{"raw_error_reason": "card_expired", "verb": "send_payment_link", "mode": "razorpay"}
```

Placeholder keys (ending `xxx`) force dry-run automatically, so this cannot
accidentally hit the network with a half-filled `.env`.

## Optional: live webhook

Webhook verification **fails closed**: with the placeholder secret, every request
to `/webhooks/razorpay` is rejected. To exercise the real path, set a real
`RAZORPAY_WEBHOOK_SECRET` and point a tunnel at it:

```bash
ngrok http 8000     # then register {url}/webhooks/razorpay in the Razorpay dashboard
```

For a local demo with no tunnel, `ALLOW_UNSIGNED_WEBHOOKS=1` skips verification.
It is refused under `APP_ENV=production` and logs `webhook_signature_bypass` every
time it fires. `POST /demo/replay` is the fully offline alternative.

## Docs

| Doc | Contents |
|---|---|
| [docs/SETUP.md](docs/SETUP.md) | **Running it.** Tier 0 (nothing) → Ollama → Inherent, plus troubleshooting |
| [docs/LIMITATIONS.md](docs/LIMITATIONS.md) | **What this project does not prove.** Start here |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Pipeline diagrams and package map |
| [docs/METHODOLOGY.md](docs/METHODOLOGY.md) | Seeds, payer model, baselines, ablation |
| [docs/SCORING.md](docs/SCORING.md) | How net INR is computed and why |
| [docs/COMPLIANCE.md](docs/COMPLIANCE.md) | Gates, stops, webhook, PII rules |
| [docs/DEMO.md](docs/DEMO.md) | 5-minute script, backup path, live edge |
| [docs/WHAT_BROKE.md](docs/WHAT_BROKE.md) | Build failure journal |

## Mental model

Three kinds of truth, deliberately kept apart:

1. **Observed truth** — `RiskEvent` / `VisibleCase`. What the system actually knows.
2. **Decision truth** — `ledger_entries`. Append-only record of what we did and why.
3. **Hidden truth** — `HiddenPayerTruth`. The simulator's secret; eval only, never
   readable by the policy.

The third one is why the evaluation is meaningful at all, and also the source of
its main weakness ([LIMITATIONS.md](docs/LIMITATIONS.md) §1).

## Baselines

| Policy | Behaviour |
|---|---|
| B0 | Do nothing. Measures natural recovery |
| B1 | One immediate retry |
| **B2** | **Three fixed retries plus one generic nag — the headline comparator** |
| B3 | Aggressive ladder, up to 7 retries |
| Ours | Cause-aware: per-class verb, timing, retry cap, contact policy |

Every policy runs against the **same seeded cases**, so differences come from the
policy and not from luck.
