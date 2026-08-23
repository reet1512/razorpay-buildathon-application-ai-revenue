# AI Architecture — Recovery Agent Intelligence Layer

Razorpay Track 03 · Payment Recovery Intelligence (planned extension).

This document describes the **current** Recovery Agent architecture, the **target** AI intelligence layer, and the **Phase 0–1** Inherent integration boundary. Functionality marked **(planned)** is not implemented yet.

See also: [ARCHITECTURE.md](ARCHITECTURE.md), [SCORING.md](SCORING.md), [COMPLIANCE.md](COMPLIANCE.md).

---

## 1. Current architecture (implemented)

```text
Razorpay webhook / simulator ingest
        ↓
Ledger (SQLAlchemy, append-only audit)
        ↓
AI classify + propose (Ollama qwen3:8b / rules fallback)
        ↓
PolicyEngine.validate_proposal
        ↓
Guard pipeline (gates — authoritative)
        ↓
Execute (sim adapter / Razorpay Payment Link)
        ↓
Evaluation harness (seeded batch, net scoreboard, multi-seed)
        ↓
FastAPI UI (Measure · Decide · Prove)
```

**Key packages today**

| Path | Role |
|---|---|
| `ai/` | `RecoveryAgent.run()` — diagnose, propose, message via Ollama |
| `policy/` | Taxonomy, closed verbs, rules fallback |
| `guard/` | Compliance gates + audit log |
| `ledger/` | Cases + ledger entries |
| `eval/` | Simulator, costing, metrics, benchmark |
| `execute/` | Sim + Razorpay adapters |
| `demo/` | Live UI flows, fraud gate demo |

**Current agent path** (`ai/agent.py`):

```text
CaseContext (de-PII)
      ↓
PolicyEngine.decide (rules baseline)
      ↓
Ollama available? ──no──→ rules fallback
      ↓ yes
LLM diagnose → LLM propose → validate_proposal → optional message
      ↓
AgentRunResult + ledger-shaped events
```

Gates run **after** the agent in product paths (`demo/live_flow.py`, `execute/service.py`). The LLM never bypasses gates.

---

## 2. Target architecture (planned)

```text
Payment failure
      ↓
Payment intelligence extraction          (planned)
      ↓
Failure classification                   (exists — policy + LLM)
      ↓
Historical payment memory (Inherent)     (Phase 1 adapter only — not wired)
      ↓
Inherent semantic retrieval              (planned — Phase 3)
      ↓
Historical recovery statistics           (planned — Phase 4)
      ↓
Economic decision engine                 (planned — Phase 5; uses eval/costing.py)
      ↓
Model routing (deterministic / RAG / LLM) (planned — Phase 6)
      ↓
Qwen3:8b when reasoning necessary        (exists — unchanged until Phase 5)
      ↓
Existing guard pipeline                  (unchanged — authoritative)
      ↓
Recovery action + execute
      ↓
Outcome → memory feedback loop           (planned — Phase 7)
```

**Engineering story (target):**

> Recovery Agent does not blindly ask an LLM what to do. It builds semantic memory from historical payment recovery episodes, retrieves similar cases, measures what actions worked, combines evidence with Razorpay economics and policy constraints, and invokes the reasoning agent only when necessary.

---

## 3. Invariants (must not break)

| Invariant | Meaning |
|---|---|
| **Guardrails authoritative** | AI proposes; gates dispose. Gate order unchanged. |
| **Single cost model** | All economics from `config/costs.json` via `config/costs.py` and `eval/costing.py`. No second fee table. |
| **Razorpay unchanged** | Webhook verify, Payment Link adapter, auth path untouched unless explicitly scoped. |
| **Ledger authoritative** | All product decisions auditable in ledger rows. |
| **RAG optional** | `INHERENT_ENABLED=false` → identical behavior to pre-RAG system. |
| **No hidden sim truth in product** | Policies/agent never read `HiddenPayerTruth`. |
| **No fabricated metrics** | UI and eval show computed values only. |

---

## 4. Inherent integration (Phase 1)

Recovery Agent uses **Inherent** as external semantic memory. Inherent manages its own vector store, embeddings, ingestion pipeline, and backing databases.

**Application endpoints (environment-configured):**

| Service | Default URL | Purpose |
|---|---|---|
| Public API | `http://localhost:18000` | Search / retrieval |
| Ingestion API | `http://localhost:18002` | Store episodes |

**Must NOT do:**

- Connect to Weaviate (`:18080`) from Recovery Agent code
- Connect to Inherent Postgres/Mongo/Valkey directly
- Add Chroma, FAISS, Pinecone, or a second vector DB

**Phase 1 boundary:** `memory/` package exposes `InherentMemoryService`. No other module calls Inherent HTTP directly. **Not wired** to `RecoveryAgent.run()` yet.

### API contract status

The exact Inherent search/ingestion request and response schemas are **not confirmed in this repository**. Unknown details are isolated in `memory/inherent_client.py` with env-configurable paths. See that module's docstring and §10 below.

---

## 5. PaymentEpisode schema (Phase 1)

Thin Pydantic model in `memory/schemas.py`. Composes existing domain vocabulary; does not duplicate ledger/eval models.

| Field | Type / source | Notes |
|---|---|---|
| `episode_id` | `str` | Synthetic/anonymized, e.g. `sim_42_case_001` |
| `amount_paise` | `int` | Same units as `RiskEvent` / `CaseContext` |
| `currency` | `str` | Default `INR` |
| `rail` | `Rail` or string | From `ledger.schemas.Rail` |
| `failure_reason` | `FailureReason` or string | From `eval.types.FailureReason` |
| `recovery_class` | `RecoveryClass` or string | From `eval.recovery_class` |
| `attempt_number` | `int` | Observed attempt count |
| `action` | `ActionVerb` or string | Closed verb set from `policy.schemas` |
| `outcome` | `EpisodeOutcome` | `success` / `failed` / `pending` |
| `recovered_paise` | `int` | Gross recovered |
| `net_recovered_paise` | `int \| null` | After costs when computed |
| `data_source` | `DataSource` | See below |
| `delay_seconds` | `int \| null` | Optional action timing hint |
| `customer_type` | `str \| null` | Coarse label only, e.g. `returning` — no PII |

**`data_source` values**

| Value | Meaning |
|---|---|
| `synthetic_simulation` | From eval harness — never label as production |
| `razorpay_test` | Live test-mode Razorpay path |
| `demo` | UI demo / fixture |

Semantic text for embedding: `memory/episode_text.build_episode_text()`.

---

## 6. PII and security rules

**Never store or send to Inherent:**

- API keys, webhook secrets, Razorpay credentials
- Phone numbers, email addresses, card PAN, real names
- Raw webhook bodies

**Allowed in episodes:**

- Coarse amount buckets (via existing `amount_bucket_inr()`)
- Synthetic episode IDs and anonymized payer refs (`payer_sim_*`)
- Failure reason, recovery class, action verb, outcome
- `data_source` provenance tag

**Logging:** structured logs may include `episode_id`, `retrieval_count`, latencies — not API keys or document bodies with PII.

---

## 7. Future routing architecture (planned)

```text
Payment
   ↓
Classification (policy + optional LLM)
   ↓
Obvious decision? ──YES──→ deterministic action → gates
   ↓ NO
Inherent retrieval + statistics
   ↓
Strong evidence? ──YES──→ economic decision engine → gates
   ↓ NO
Qwen3:8b with retrieved evidence in prompt → gates
```

Metrics to track **(planned):** `deterministic_cases`, `rag_resolved_cases`, `llm_cases`, `llm_call_rate`, `retrieval_latency_ms`.

---

## 8. Failure behavior — Inherent unavailable

| Condition | Behavior |
|---|---|
| `INHERENT_ENABLED=false` | No-op: search → `[]`, store → no-op. **Zero network.** |
| Enabled + timeout / connection error | Search → `[]`; store → swallow error. Recovery path continues. |
| Enabled + malformed response | Parse safely → `[]` or skip store. Log structured warning. |
| Enabled + auth failure | Same as connection failure — never crash agent/gates. |

RAG must **never** be a single point of failure.

---

## 9. Phase rollout plan

| Phase | Scope | Status |
|---|---|---|
| **0** | This document | ✅ |
| **1** | `memory/` Inherent adapter, schemas, episode text, tests | ✅ |
| **2** | Seed Inherent from eval seeds 42–51 | planned |
| **3** | Retrieval on payment failure | planned |
| **4** | Historical statistics layer | planned |
| **5** | RAG evidence in Qwen prompts | planned |
| **6** | Model routing (deterministic / RAG / LLM) | planned |
| **7** | Outcome → memory feedback loop | planned |
| **8** | RAG vs baseline eval (same seeds) | planned |
| **9** | Case UI explainability | planned |
| **10** | AI engineering metrics dashboard + inference abstraction | planned |

After each phase: `python -m pytest -q` — existing tests must pass.

---

## 10. Unknown Inherent API details (Phase 1)

Until confirmed against running Inherent docs/OpenAPI:

| Item | Status |
|---|---|
| Search HTTP method + path | Env `INHERENT_SEARCH_PATH` (placeholder default documented in client) |
| Ingest HTTP method + path | Env `INHERENT_INGEST_PATH` |
| Request JSON shape | Provisional builder in `inherent_client.py` — **subject to change** |
| Response JSON shape | Flexible parser; maps to `RetrievalResult` when possible |
| Auth header format | `Authorization: Bearer <key>` when `INHERENT_API_KEY` set |
| Workspace scoping | `INHERENT_WORKSPACE_ID` included in payloads when set |

Update this section when the real contract is verified.

---

## 11. Package map (after Phase 1)

```text
memory/
  schemas.py       PaymentEpisode, RetrievalResult, enums
  episode_text.py  build_episode_text() — deterministic semantic text
  inherent_client.py  HTTP only — unknown API isolated here
  service.py       InherentMemoryService — app-facing async API
```

No imports from `memory/` exist yet in `ai/`, `guard/`, `ledger/`, or `eval/` product paths.
