# Recovery Agent

**Razorpay /buildathon — Track 03: AI Revenue Recovery**

When a subscription payment fails, blind retry ladders waste fees and spam payers.
This agent classifies the failure, lets **AI propose** a bounded action, lets **policy/gates refuse** unsafe moves, executes via **sim (scale)** or **Razorpay test Payment Links (edge)**, and proves results in **INR on a seeded batch**.

> AI proposes. Policy/gates dispose. Ledger audits. Simulated at scale, real at the edges.

## Stranger setup (Windows)

Project-local Python (if system Python is broken):

```text
cd recovery-agent
..\tools\python.cmd -m pip install -r requirements.txt
copy .env.example .env
```

Edit `.env`: Razorpay **test** `KEY_ID` / `KEY_SECRET` (optional for sim-only), Ollama settings, never commit `.env`.

```text
..\tools\python.cmd -m pytest -q
..\tools\python.cmd scripts\check_no_secrets.py
..\tools\python.cmd eval\harness.py --compare --seed 42 --n 500
..\tools\python.cmd -m uvicorn main:app --reload --port 8000
```

Open:

- Batch UI: http://127.0.0.1:8000/ui/batch  
- Demo case (offline backup): **Open demo case trail** on that page  
- API docs: http://127.0.0.1:8000/docs  

### Optional: live AI

```text
ollama pull qwen3:8b
ollama serve
```

`GET /agent/health` → `POST /agent/run` with `{"raw_error_reason":"card_expired","amount_paise":49900}`.

### Optional: real Payment Link (test mode)

Set keys in `.env`, `RAZORPAY_DRY_RUN=0`, then:

```text
POST /execute/run
{"raw_error_reason":"card_expired","verb":"send_payment_link","mode":"razorpay"}
```

## Docs

| Doc | Contents |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Pipeline diagrams + package map |
| [docs/METHODOLOGY.md](docs/METHODOLOGY.md) | Seeds, assumptions, baselines, ablation |
| [docs/COMPLIANCE.md](docs/COMPLIANCE.md) | Gates, stops, webhook, PII rules |
| [docs/DEMO.md](docs/DEMO.md) | 5-min script, backup path, live edge |
| [docs/WHAT_BROKE.md](docs/WHAT_BROKE.md) | Failure journal for submission |

## Mental model

1. Observed truth = `RiskEvent` / `VisibleCase`  
2. Decision/audit truth = `ledger_entries`  
3. Hidden sim truth = `HiddenPayerTruth` (eval only)

## B2 in one sentence

Three fixed retries plus one generic nag — same ladder for every failure reason.

## Phase map (0–9)

| Phase | Status |
|---|---|
| 0–1 Ledger + RiskEvent | Done |
| 2 Eval harness / INR | Done |
| 3 Webhook ingest | Code done; wire ngrok for live |
| 4 Taxonomy + policy | Done |
| 5 AI agent (Ollama) | Done |
| 6 Gates + stops | Done |
| 7 Sim + Razorpay adapters | Done |
| 8 Batch + Case UI | Done |
| 9 Hardening + submission docs | Done |
