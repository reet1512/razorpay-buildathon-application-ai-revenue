# Setup

Three tiers. **Tier 0 is enough to review everything that matters** — the full test
suite, the headline benchmark, the whole API, and every UI screen. Tiers 1 and 2
turn on the live LLM and semantic memory, and neither is required.

| Tier | You install | You get | Time |
|---|---|---|---|
| **0** | Python + `pip install` | Everything: 154 tests, benchmark, API, UI, gates, ledger | ~2 min |
| **1** | + Ollama | Live LLM diagnosis instead of `rules_fallback` | +10 min (5 GB model) |
| **2** | + Inherent (Docker) | RAG over past recovery episodes | +20 min |

The system degrades cleanly at every tier. Nothing hangs, nothing crashes, and the
UI states which components are actually live rather than pretending.

---

## Tier 0 — zero services (start here)

Requires Python 3.12 or newer. No Docker, no LLM, no Razorpay account.

```bash
git clone https://github.com/reet1512/razorpay-buildathon-application-ai-revenue.git
cd razorpay-buildathon-application-ai-revenue/recovery-agent

python -m venv .venv
source .venv/bin/activate          # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env               # Windows: copy .env.example .env
```

Verify — all three should pass with no external services running:

```bash
pytest -q                                            # expect: 154 passed
python scripts/check_no_secrets.py                   # expect: secret check ok
python -m eval.harness --benchmark --seed 42 --n 500
```

The benchmark prints the headline comparison. It is deterministic: seed 42 gives
the same numbers on any machine, every time.

Run the app:

```bash
uvicorn main:app --reload --port 8000
```

**Before opening the UI, store one evaluation run**, or the Stats screen will be
empty. That emptiness is deliberate — the UI refuses to display numbers it did not
compute — but it looks like a bug if you are not expecting it:

```bash
curl -X POST http://127.0.0.1:8000/eval/run \
  -H "Content-Type: application/json" \
  -d '{"seed":42,"n":500}'
```

PowerShell equivalent:

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8000/eval/run -Method POST `
  -Body '{"seed":42,"n":500}' -ContentType "application/json"
```

Or just click **Run evaluation** on the Stats page.

### What you can see at Tier 0

| URL | What it shows |
|---|---|
| `/ui` | Stats: Ours vs B2 in net INR, from the stored run |
| `/ui/recover` | The agent reasoning over a single case, step by step |
| `/ui/batch` | Batch evaluation detail and per-class breakdown |
| `/cases/{id}` | Real append-only ledger trail for one case |
| `/docs` | OpenAPI, every endpoint |
| `/health` | Liveness |

At this tier the LLM badge reads **Offline** and the RAG badge reads
**RAG DISABLED**. Both are truthful status, not failures.

### Prove the safety properties without any services

```bash
# 1. Duplicate execution is refused (idempotency, rebuilt from the ledger)
curl -X POST http://127.0.0.1:8000/execute/run -H "Content-Type: application/json" \
  -d '{"raw_error_reason":"insufficient_funds","verb":"schedule_retry","mode":"sim"}'
# → note the case_id, then repeat with "case_id":"<that id>"
# → second call returns "blocked_by": "idempotency", "executed": false

# 2. Unsigned webhooks are rejected (fail-closed)
curl -i -X POST http://127.0.0.1:8000/webhooks/razorpay \
  -H "Content-Type: application/json" -d '{"event":"payment_link.paid"}'
# → 401 invalid webhook signature

# 3. Offline demo replay, no Razorpay needed
curl -X POST http://127.0.0.1:8000/demo/replay
```

---

## Tier 1 — add Ollama (live LLM)

Optional. Enables real LLM diagnosis, action proposal, and message drafting on the
case path. It does **not** change the benchmark: the batch deliberately uses
taxonomy rules so the headline stays reproducible (see
[LIMITATIONS.md](LIMITATIONS.md) §3.1).

Install from [ollama.com/download](https://ollama.com/download), then:

```bash
ollama pull qwen3:8b     # ~5 GB
ollama serve             # serves on http://localhost:11434
```

Confirm the app sees it:

```bash
curl http://127.0.0.1:8000/agent/health
curl -X POST http://127.0.0.1:8000/agent/run -H "Content-Type: application/json" \
  -d '{"raw_error_reason":"card_expired","amount_paise":49900}'
```

The response carries `proposed_by: llm` when Ollama is up and
`proposed_by: rules_fallback` when it is not. Relevant `.env` keys:

```bash
LLM_PROVIDER=ollama
LLM_BASE_URL=http://localhost:11434/v1
LLM_MODEL=qwen3:8b
```

**Smaller machine?** Any Ollama model works — `ollama pull qwen3:1.7b` and set
`LLM_MODEL=qwen3:1.7b`. Quality drops; the guardrails do not, because
`validate_proposal` repairs or rejects anything outside the taxonomy regardless of
which model produced it. That is arguably a better demonstration of the thesis.

---

## Tier 2 — add Inherent (RAG over past episodes)

Optional, and the heaviest step.

**Inherent is a separate product with its own Docker stack — it is not vendored in
this repository and there is no `docker-compose.yml` here.** This project only ever
talks to it over HTTP through `memory/inherent_client.py`, which is why it can be
switched off entirely.

You need Docker Desktop running, plus an Inherent instance exposing:

| Service | Default URL | Used for |
|---|---|---|
| Public API | `http://localhost:18000` | Search / retrieval |
| Ingestion API | `http://localhost:18002` | Storing episodes |

The app deliberately never touches Inherent's internals — not Weaviate on `:18080`,
not its Postgres/Mongo/Valkey. That boundary is an explicit invariant in
[ai_architecture.md](ai_architecture.md) §3.

Once Inherent is up, set in `.env`:

```bash
INHERENT_ENABLED=true
INHERENT_BASE_URL=http://localhost:18000
INHERENT_API_KEY=<your key>
INHERENT_WORKSPACE_ID=<optional workspace id>
```

Both `INHERENT_ENABLED=true` **and** a non-empty `INHERENT_API_KEY` are required;
with either missing the app short-circuits to "RAG DISABLED" without opening a
socket.

Seed the episode corpus (generates episodes from eval seeds and uploads them):

```bash
python -m memory.seed --dry-run              # inspect what would be uploaded
python -m memory.seed --seeds 42-51 --n 200  # real upload
python -m memory.seed --seeds 42-51 --n 200 --resume --validate
```

Check status:

```bash
curl "http://127.0.0.1:8000/ui/rag-status?force=1"
```

The Stats page badge moves to **RAG ACTIVE** with a live retrieval latency.

### If you skip Tier 2

Nothing breaks. `INHERENT_ENABLED=false` is an explicit invariant: *"RAG optional —
identical behavior to pre-RAG system."* The UI says "RAG DISABLED" and the case
screen simply shows no retrieved episodes.

---

## Optional: real Razorpay Payment Links

Test mode only. Put test keys in `.env` and set `RAZORPAY_DRY_RUN=0`:

```bash
RAZORPAY_KEY_ID=rzp_test_...
RAZORPAY_KEY_SECRET=...
RAZORPAY_DRY_RUN=0
```

```bash
curl -X POST http://127.0.0.1:8000/execute/run -H "Content-Type: application/json" \
  -d '{"raw_error_reason":"card_expired","verb":"send_payment_link","mode":"razorpay"}'
```

Placeholder keys (anything ending `xxx`) force dry-run automatically, so a
half-filled `.env` cannot accidentally hit the network.

### Live webhooks

Verification **fails closed**: with the placeholder secret, every request to
`/webhooks/razorpay` is rejected with 401. To exercise the real path, set a real
`RAZORPAY_WEBHOOK_SECRET` and expose the app:

```bash
ngrok http 8000
# register {public-url}/webhooks/razorpay in the Razorpay dashboard
```

For a local demo with no tunnel, `ALLOW_UNSIGNED_WEBHOOKS=1` skips verification.
It is refused outright when `APP_ENV=production` and logs
`webhook_signature_bypass` every time it fires. `POST /demo/replay` is the fully
offline alternative.

---

## Troubleshooting

**Stats page shows an em dash instead of money.** No evaluation run is stored yet.
Run one (see Tier 0). This is intended behaviour, not a failure.

**Benchmark commands.** Run them from `recovery-agent/` with `-m`:
`python -m eval.harness --benchmark --seed 42 --n 500`. The script form
(`python eval/harness.py`) also works, but only because the file repairs
`sys.path` on the way in — `eval/types.py` otherwise shadows the stdlib `types`
module and stdlib `enum` fails to import. Prefer `-m`.

**`ModuleNotFoundError: No module named 'eval'`.** You are not in the
`recovery-agent/` directory, or you are on a Python whose `._pth` excludes the
working directory (the Windows embeddable build does this; a normal install and a
venv do not).

**`pytest` fails on a fresh clone.** It should not — the suite passes in default
and reverse order with no external services. If it does, please note the ordering;
an earlier revision had exactly this bug and it is documented in
[WHAT_BROKE.md](WHAT_BROKE.md) §8.

**Webhook returns 401.** Correct by default. See "Live webhooks" above.

**LLM badge says Offline with Ollama running.** Check `ollama serve` is on 11434
and that `LLM_BASE_URL` ends in `/v1`. The health probe hits
`{base}/api/tags` with a 3-second timeout and fails closed to `rules_fallback`.

**Port 8000 in use.** `uvicorn main:app --reload --port 8001`.

**Windows: `.venv\Scripts\Activate.ps1` blocked.** Run
`Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` in that shell first.
