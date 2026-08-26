# Metrics Execution Plan — Sprint by Sprint

**Product:** Recovery Agent (Razorpay /buildathon · Track 03)  
**Doc type:** Execution plan (metrics + AI/RAG stack)  
**Owner:** Solo builder + Cursor  
**Last updated:** 2026-08-26  

---

## 0. North-star metrics (what “done” means)

### 0.1 Primary scoreboard (batch eval — rules, reproducible)

| Metric | Definition | Baseline (today) | Target |
|---|---|---|---|
| **Recovery rate (Ours)** | `gross_recovered_inr / at_risk_inr` | ~52.6% | **70–78%** |
| **Net advantage** | `ours.net_recovered_inr − b2.net_recovered_inr` | ~₹1k @ n=200 | **₹25k+ @ n=1000**; stretch **₹50k–100k+** via larger n / ticket mix |
| **Wasted attempts (Ours)** | Retries on `CUSTOMER_ACTION` | High gap vs B2 already | Keep **near-zero** |
| **Cost / ₹ recovered** | `total_cost / gross` | Slightly better than B2 | Clear win vs B2 |

**Hard constraint:** Recovery rate **cannot** be 780%. It is a fraction of at-risk INR (ceiling ≈ 100%). Industry best-in-class failed-payment recovery is ~70–85%. The plan targets **~78%**, not 780%.

**Winner definition (frozen):** higher `net_recovered_inr` — see [`SCORING.md`](SCORING.md).

### 0.2 Secondary scoreboard (case path — AI + RAG)

| Metric | Definition | Target |
|---|---|---|
| **RAG online** | Inherent Public API healthy + search OK | Live badge on Stats |
| **Corpus size** | Manifest `completed` episodes | ≥ **2,000** (done); stretch 5k+ |
| **Retrieval hit quality** | Top-k similar episodes share failure class | ≥ 60% class match on validate queries |
| **LLM with evidence** | Diagnose/propose prompts include `historical_similar_episodes` | Always when RAG available |
| **Fallback integrity** | Ollama down → `rules_fallback` | 100% of demos |

### 0.3 What moves which number

```text
Recovery % / ₹ advantage  ←  taxonomy.yaml + payer_model + simulate + costs
                           (batch harness — NOT Ollama, NOT Inherent alone)

Demo “AI feels smart”     ←  RAG retrieval + prompt evidence + gates + Razorpay edge
Judge trust               ←  seed 42, methodology, multi-seed, ledger audit
```

**Do not** claim batch INR lift from RAG until Sprint 6 ships a controlled ablation.

### 0.4 Canonical measurement commands

```text
cd recovery-agent

# Headline (rules batch)
..\tools\python.cmd eval\harness.py --benchmark --seed 42 --n 500
..\tools\python.cmd eval\harness.py --benchmark --seed 42 --n 1000

# Multi-seed (anti cherry-pick)
..\tools\python.cmd eval\harness.py --benchmark --seeds 42-51 --n 200

# UI
# Stats → seed 42, N=500 or 1000 → Run evaluation

# RAG seed (corpus)
..\tools\python.cmd -c "import sys; sys.path.insert(0,'.'); from memory.seed import main; raise SystemExit(main(['--seeds','42-51','--n','200','--force','--validate']))"
```

---

## 1. Current state snapshot (start of plan)

| Area | Status |
|---|---|
| Eval harness B0–B2 vs Ours | ✅ |
| Taxonomy policy (`policy/taxonomy.yaml`) | ✅ cause-aware v0 |
| Gates + ledger | ✅ |
| Inherent client + seeder | ✅ |
| Corpus seeded | ✅ **2,000** episodes (seeds 42–51 × 200) |
| Pipeline retrieval → UI chunks | ✅ |
| RAG episodes in LLM prompts | ✅ (Phase 5 evidence wiring) |
| Stats live RAG badge + corpus count | ✅ |
| Batch INR driven by LLM/RAG | ❌ by design (reproducibility) |
| Recovery rate ~70%+ | ❌ ~52–55% typical |
| Net advantage ₹100k @ small n | ❌ needs scale + stronger edge |

---

## Sprint overview

| Sprint | Theme | Duration | Exit metric |
|---|---|---|---|
| **S0** | Instrument & freeze baselines | 0.5 day | Logged seed-42 rates @ n=200/500/1000 |
| **S1** | Cause-aware policy sharpening | 1–1.5 days | Ours recovery **≥ 60%** @ seed 42, n=500 |
| **S2** | Sim economics & fatigue honesty | 1 day | Net advantage **≥ ₹10k** @ n=500 |
| **S3** | Segment scoreboard (judge story) | 0.5–1 day | UI shows class-level wins |
| **S4** | RAG quality & retrieval routing | 1 day | Validate queries class-match ≥ 60% |
| **S5** | LLM + RAG decision loop | 1–1.5 days | Demo path uses evidence; ablation note |
| **S6** | Optional: RAG-influenced batch ablation | 1 day | Documented Δ vs rules-only |
| **S7** | Scale headline to ₹25k–100k band | 0.5 day | Seed 42 n=1000+ advantage logged |
| **S8** | Hardening, docs, demo script | 1 day | Submission-ready |

Suggested calendar: **~7–9 working days**. Compress S3+S4 or skip S6 if timeboxed.

---

## Sprint 0 — Instrument & freeze baselines

**Goal:** Know exactly where 52.6% comes from before changing anything.

### Work

1. Run and archive three fixed benches (JSON + screenshots of Stats):
   - seed **42**, n=**200**
   - seed **42**, n=**500**
   - seed **42**, n=**1000**
2. Record for Ours and B2: recovery rate, net INR, gross INR, wasted attempts, cost/₹.
3. Break down by `recovery_class` / failure reason (`eval` segments / harness `--show-cases`).
4. Freeze “do not change without calling out” list:
   - Winner = net (SCORING.md)
   - Fatigue factor 0.55
   - `DECLINE_WEIGHTS` + `AMOUNTS_PAISE` in `eval/batch.py`

### Deliverables

- `artifacts/metrics_baseline_seed42_n{200,500,1000}.json`
- One table in this doc’s Appendix A filled with real numbers

### Exit criteria

- [ ] Baseline recovery rate documented (±0.5% on re-run)
- [ ] Team agrees target is **~78% recovery**, not 780%
- [ ] Team agrees ₹100k is a **scale/edge** target, not a UI default at n=200

---

## Sprint 1 — Cause-aware policy sharpening (biggest recovery-% lever)

**Goal:** Move overall recovery toward **≥ 60%**, then stretch to **65%+**, by beating B2 where B2 is structurally wrong.

### Insight (industry-aligned)

| Failure family | B2 (blind) | Ours (target) |
|---|---|---|
| NSF / funds | Retry 0/2/5 + nag | Salary-window silent retries |
| Transient issuer/gateway | Same ladder + nag | Short backoff, **no contact** |
| Expired / token / mandate | Wasted retries | **Zero retries** → link / mandate update |
| Fraud / risk | Still nags | Escalate / stop |

### Work

1. Audit `policy/taxonomy.yaml` per class:
   - `max_retries`, `timing`, `allow_contact`, `default_verb`
2. Tighten dead-instrument path:
   - Ensure `card_expired` / `token_invalid` / `mandate_revoked` never emit `schedule_retry` in Ours plan
3. NSF: verify salary-window day offsets align with `HiddenPayerTruth.true_credit_day` in `eval/simulate.py` / policy engine timing helpers
4. Transient: single quick retry; suppress generic nag
5. Ambiguous (`do_not_honour`): one careful retry then link — measure wasted vs recoveries
6. Re-run seed 42 n=500 after each taxonomy change; keep a changelog of Δ recovery rate

### Files likely touched

- `policy/taxonomy.yaml`
- `policy/engine.py` (timing helpers if needed)
- `eval/baselines.py` (only if Ours wrapper needs hooks — prefer taxonomy-only)

### Exit criteria

- [ ] Ours recovery rate **≥ 60%** @ seed 42, n=500
- [ ] Wasted attempts Ours **≪** B2
- [ ] `pytest -q` green (policy + eval tests)
- [ ] No silent change to winner formula

### Stretch

- [ ] Ours recovery **≥ 65%** without inventing unrealistic payer success rates

---

## Sprint 2 — Simulator economics & contact efficacy

**Goal:** Raise recovery further toward **70–78%** *honestly* by adjusting modeled response probabilities where taxonomy already chooses the right verb.

### Work

1. Review `eval/payer_model.py` / contact success paths:
   - Payment-link success on dead instruments
   - Mandate-update success
   - NSF retry success inside credit window vs outside
2. Calibrate **without** making everything succeed:
   - Raise link conversion modestly for `CUSTOMER_ACTION`
   - Keep fraud recovery near zero (compliance story)
3. Revisit fatigue `0.55` only with an explicit methodology note (challengers will ask)
4. Cost knobs in `config/costs.json`:
   - Ensure B2’s wasted retries + inappropriate contacts show on **net**
   - Do not zero-out MDR to fake wins

### Guardrails

- Document every ASSUMPTION change in `docs/METHODOLOGY.md` / `WHAT_BROKE.md`
- Prefer “Ours recovers more of the recoverable set” over “all payers magically pay”

### Exit criteria

- [ ] Ours recovery rate **≥ 70%** @ seed 42, n=500 **or** clear written ceiling with segment proof
- [ ] Net advantage **≥ ₹10,000** @ n=500
- [ ] Methodology paragraph updated for any payer-model change

### Stretch

- [ ] Ours recovery **≥ 75–78%** @ seed 42, n=500

---

## Sprint 3 — Segment scoreboard (make the win judge-visible)

**Goal:** Even if overall rate is mid-60s–70s, the **story** is undeniable on Stats / Evaluate.

### Work

1. Surface on Stats (or Evaluate disclose):
   - Recovery rate by `recovery_class` (RETRY_FIXABLE / CUSTOMER_ACTION / AMBIGUOUS / PROHIBITED)
   - Wasted attempts Ours vs B2
   - Forgone recovery on PROHIBITED (compliance cost, not a loss)
2. Hero copy: primary = **net advantage ₹**; secondary = recovery %; tertiary = wasted attempts
3. Default UI eval inputs: seed **42**, n **500** (or 1000) instead of 200 for demos

### Files likely touched

- `templates/product/overview.html`
- `api/ui_mock.py` / `evaluate_ui_context`
- `eval/segments.py` (already has structure — wire to UI)

### Exit criteria

- [ ] Judge can see CUSTOMER_ACTION win without opening CLI
- [ ] Demo script uses seed 42 / n=500 as default

---

## Sprint 4 — RAG quality & retrieval routing

**Goal:** Corpus is large; make **top-k** useful for the agent (class-aligned evidence).

### Work

1. Keep corpus healthy:
   - Re-seed or `--resume` if Inherent wiped
   - Target: **≥ 2,000** completed; optional expand `--n 500` per seed later
2. Improve query builder (`memory/rag.py` `build_retrieval_query`):
   - Emphasize failure reason + recovery class + rail + verb hints
3. Run seeder `--validate` queries; log class distribution of top hits
4. Stats: keep **Corpus** vs **Retrieved (top-k)** distinct (already started)
5. Optional: store retrieval quality metric in manifest / Stats

### Exit criteria

- [ ] `--validate` shows sensible top hits for NSF / expired / fraud queries
- [ ] Class match on top-5 ≥ **60%** for at least 4/6 validation queries
- [ ] RAG never blocks recovery if Inherent is down

---

## Sprint 5 — LLM + RAG closed loop (demo path excellence)

**Goal:** When Simulate/Live runs, the model **uses** retrieved episodes; gates still dispose.

### Already done (verify, don’t regress)

- `retrieve_for_payment` before `agent.run`
- `CaseContext.rag_episodes` / `rag_query`
- `historical_similar_episodes` in diagnose + propose prompts

### Work this sprint

1. Prompt polish:
   - Cap evidence to top **5–8** chunks
   - Instruct model to cite “similar cases preferred verb X” in `note` / `rationale`
2. UI: show “Evidence used by agent” (chunk → verb) on thinking panel
3. Ablation demo toggle:
   - RAG on / RAG off / LLM off (`force_fallback`)
4. Log structured fields: `rag_similar_cases`, `used_llm`, `fallback_reason`

### Exit criteria

- [ ] Side-by-side demo: rules_fallback vs LLM+RAG produces visibly different rationale (when Ollama up)
- [ ] Gates still block unsafe verbs
- [ ] Tests for prompt evidence remain green

---

## Sprint 6 — Optional: RAG-influenced batch ablation (advanced)

**Goal:** Measure whether retrieval-guided **rules** (not live LLM) improve batch INR.

### Approach (keep reproducibility)

1. Offline: for each sim case, retrieve top-k; majority-vote suggested verb if taxonomy allows
2. Compare labels: `ours` vs `ours_rag_hints` vs `b2` on same seed/n
3. Publish Δ recovery and Δ net in methodology — **only if positive and stable across seeds**

### Exit criteria

- [ ] Ablation table for seeds 42–51 @ n=200
- [ ] If Δ ≤ 0: document “RAG is demo/explainability, not batch money” (honest)

**Skip this sprint** if time < 48h to submission.

---

## Sprint 7 — Scale the rupee headline (₹25k → ₹100k band)

**Goal:** Hit a memorable **net advantage** without lying about recovery %.

### Math reminder

At ~₹5–15 net edge per case, ₹100k needs **very large n** or larger tickets. Prefer:

| Play | Expected advantage order |
|---|---|
| seed 42, n=500 + S1–S2 edge | ₹10k–30k |
| seed 42, n=1000 | ~2× the n=500 advantage |
| seed 42, n=2000–5000 | Toward ₹50k–100k if per-case edge holds |
| Raise `AMOUNTS_PAISE` mix (document) | Amplifies ₹ without raising % |

### Work

1. After S1–S2, run n=1000 and n=2000; archive JSON
2. Stats default N for “demo mode” = 1000
3. Pitch line:
   > “On seed 42 / n=1000 identical batch: Ours recovers **X%** vs B2 **Y%**, net **+₹Z**. Recovery rate targets industry 70–80%; rupee gap scales with book size.”

### Exit criteria

- [ ] Documented run with net advantage **≥ ₹25,000**
- [ ] Stretch: **≥ ₹50,000** or path to ₹100k with n= stated
- [ ] Never label recovery rate as 780%

---

## Sprint 8 — Hardening, docs, demo script

**Goal:** Submission-ready, stranger-reproducible.

### Work

1. Update:
   - `docs/METHODOLOGY.md` — new assumptions
   - `docs/DEMO.md` — 5-min script with Stats → Simulate → Live
   - `docs/ai_architecture.md` — mark phases 2–5 status
   - `docs/WHAT_BROKE.md` — failures during sprints
2. Smoke checklist:
   - Inherent up, Ollama up, uvicorn up
   - Stats RAG Live + Corpus 2000+
   - Eval seed 42 n=500 completes
   - Simulate shows RAG chunks → agent rationale
   - Live Payment Link (test mode) optional
3. `pytest -q` full suite (skip e2e if flaky env)
4. Record 60–90s video of scoreboard + one AI case

### Exit criteria

- [ ] Stranger can reproduce headline from README commands
- [ ] All primary metric targets either **hit** or **explicitly deferred** with numbers

---

## Risk register

| Risk | Impact | Mitigation |
|---|---|---|
| Chasing 780% recovery | Credibility loss | Educate; target 78% |
| Tuning sim to “always win” | Judge challenge | Multi-seed; document assumptions |
| RAG downtime on demo day | Blank memory step | Offline badge + rules path |
| Ollama slow/down | Weak AI beat | `force_fallback` still ships product |
| Large n eval too slow | Demo timeout | Pre-compute run JSON; load latest |
| Inherent re-seed time (~40m / 2k) | Blocked demo | Keep corpus; `--resume`; snapshot manifest |
| Embeddable Python `PYTHONPATH` | Seed/CLI fails | `sys.path.insert` pattern / fix `._pth` |

---

## RACI (solo team)

| Activity | Doer |
|---|---|
| Taxonomy / sim changes | Builder |
| Eval runs & archive | Builder |
| UI scoreboard | Builder + Cursor |
| RAG / prompts | Builder + Cursor |
| Demo script & video | Builder |

---

## Definition of Done (program-level)

1. **Recovery rate Ours ∈ 70–78%** on seed 42, n=500 (or written ceiling ≥ 65% with segment proof).  
2. **Net advantage ≥ ₹25k** on seed 42, n=1000 (stretch ₹50k–100k with stated n).  
3. **B2 wasted attempts visibly higher**; CUSTOMER_ACTION segment favors Ours.  
4. **RAG corpus ≥ 2k**, Live badge, evidence in LLM prompts on Simulate.  
5. **Methodology + DEMO.md** updated; batch remains re-runnable without LLM.  
6. No metric labeled above 100% recovery rate.

---

## Appendix A — Baseline log (fill in Sprint 0)

| Run | Seed | N | Ours recovery % | B2 recovery % | Ours net ₹ | B2 net ₹ | Advantage ₹ | Date |
|---|---|---|---|---|---|---|---|---|
| Pre S1/S2 | 42 | 200 | 47.6 | 49.0 | 117,397 | 117,234 | +163 | 2026-08-26 |
| Pre S1/S2 | 42 | 500 | 53.0 | 48.0 | 347,316 | 305,092 | +42,224 | 2026-08-26 |
| Pre S1/S2 | 42 | 1000 | 53.9 | 49.6 | 685,816 | 612,257 | +73,559 | 2026-08-26 |
| **Post S1/S2** | 42 | 200 | **70.8** | 60.9 | 174,488 | 146,617 | **+27,871** | 2026-08-26 |
| **Post S1/S2** | 42 | 500 | **74.7** | 59.8 | 489,604 | 382,467 | **+107,137** | 2026-08-26 |
| **Post S1/S2** | 42 | 1000 | **75.5** | 59.6 | 960,780 | 740,354 | **+220,426** | 2026-08-26 |

See also [`METRICS_FINAL_REPORT.md`](METRICS_FINAL_REPORT.md).

---

## Appendix B — Sprint checklist (print)

- [ ] S0 baselines archived  
- [ ] S1 taxonomy → ≥60% recovery  
- [ ] S2 sim/costs → ≥70% or documented ceiling; ₹10k+ @ n=500  
- [ ] S3 segment UI + default n=500  
- [ ] S4 RAG validate ≥60% class match  
- [ ] S5 LLM evidence demo polished  
- [ ] S6 ablation (optional)  
- [ ] S7 rupee headline scaled  
- [ ] S8 docs + video + pytest  

---

## Appendix C — Mapping to existing docs

| Doc | Role |
|---|---|
| [`SCORING.md`](SCORING.md) | Winner formula (do not break) |
| [`METHODOLOGY.md`](METHODOLOGY.md) | Assumptions & commands |
| [`ai_architecture.md`](ai_architecture.md) | RAG/LLM phases |
| [`DEMO.md`](DEMO.md) | Stage script |
| [`../BUILD_PLAN.md`](../../BUILD_PLAN.md) | Product idea & calendar |

---

*End of plan. Update Appendix A after every ranked eval run; bump sprint exit boxes when hit.*
