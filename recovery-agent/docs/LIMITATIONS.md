# Limitations

Written by the builder, before anyone had to ask. Every claim in this repository
has a boundary, and this is where the boundaries live. Read it alongside
[SCORING.md](SCORING.md) and [METHODOLOGY.md](METHODOLOGY.md).

> **Short version:** the architecture is the contribution. The rupee figures are a
> ranking of two policies inside our own simulator under assumptions we chose —
> not a measurement of merchant lift.

This document is structured as a research critique rather than an apology. Where
we know the weakness, we name the file and line that causes it, and we say what
evidence would change our mind (§7).

---

## 1. Scope

### 1.1 What this project demonstrates

1. **An architecture for constraining an LLM on payment rails.** An LLM diagnoses
   a failure and proposes one action from a closed verb set; a deterministic policy
   engine repairs anything illegal; six gates can block; every verdict is written
   to an append-only ledger. This part is real, tested, and the actual
   contribution.
2. **That cause-aware recovery beats cause-blind recovery in a controlled
   simulation.** Under our payer model, on identical seeded cases, scored on net
   INR after costs.
3. **That the system degrades honestly.** No LLM, no RAG, no Razorpay keys, no
   Docker — it still runs, and the UI reports which components are live rather
   than fabricating output.

### 1.2 What it does not demonstrate

1. **Any production recovery number.** Nothing here has touched real merchant
   traffic.
2. **That the LLM improves recovery.** The headline benchmark does not use the
   LLM at all (§3.1). No AI evaluation exists.
3. **Regulatory compliance.** No RBI e-mandate, pre-debit notification, or AFA
   logic exists in this codebase (§4.5).
4. **Production robustness.** No authentication, no migrations, SQLite, and a
   check-then-act idempotency race (§4, §6).

---

## 2. Evaluation limitations

### 2.1 The policy searches exactly where the simulator hides the answer

**This is the single most important caveat**, and it is worth being precise,
because the headline is more concentrated than it looks.

At seed 42, n=500, essentially the entire gross advantage comes from one failure
reason:

| Failure reason | n | Δ gross INR (Ours − B2) |
|---|---:|---:|
| `insufficient_funds` | 156 | **+98,732** |
| `card_expired` | 80 | +9,192 |
| `mandate_revoked` | 36 | +5,996 |
| `token_invalid` | 36 | +5,996 |
| `gateway_timeout` | 32 | −1,499 |
| `issuer_transient` | 77 | −2,697 |
| `risk_fraud` | 22 | −5,394 |
| `do_not_honour` | 61 | −10,494 |
| **Total** | **500** | **+99,832** |

So ~99% of the gross edge is NSF timing. Now look at how both sides model NSF.

The simulator draws the payer's hidden payday and funds a 3-day window
(`eval/payer_model.py`):

```python
credit_day = rng.randint(1, 7)          # salary clustering heuristic
window = {credit, (credit % 28) + 1, ((credit + 1) % 28) + 1}
```

with `retry_success_if_funded=0.92` for NSF. The policy, when it has no
`observed_credit_day` hint, fans its retries across
(`policy/timing.py`, `salary_window_offsets`):

```python
for target in (1, 2, 3, 5, 7):          # likely payday cluster
```

**The policy's search set is the simulator's support.** Days 1–7 is where the
simulator hides funded days, and days 1–7 is where the policy looks — with
`max_retries: 4` in `taxonomy.yaml` covering four of the seven. B2, a blind fixed
ladder, retries on arbitrary days and mostly misses the window.

**Why this is circular.** The payer model and the taxonomy encode the *same causal
assumption* — that NSF resolves when salary lands early in the month. One file
asserts it as ground truth and the other exploits it. We are therefore not
measuring "cause-aware timing beats blind retry in the real world"; we are
measuring that **a policy which knows the generative model beats one that does
not.** That is close to a tautology.

The direction remains defensible on domain grounds: Indian salary credits really
do cluster early in the month, and timing NSF retries to payday really is standard
practice. But **the magnitude is an artefact of two files agreeing.**

> The benchmark is useful for comparing policies in a controlled environment. It
> is **not an unbiased estimate of production recovery.** Because the payer model
> and the taxonomy share causal assumptions, the measured advantage should be read
> as **conditional policy performance**, not externally validated lift.

The fix, designed but not run: widen the simulator's `credit_day` draw (1–28, or a
mixture with a mid-month cluster) so the policy's 1–7 fan-out is no longer a
perfect cover, then report how much edge survives. We expect it to shrink
substantially.

Note also that the advantage is **not** where the project narrative would suggest:
dead instruments contribute only +21,184, and Ours actually **loses** on four of
eight reasons (−20,084 combined), most notably `do_not_honour` — the ambiguous
class the LLM is supposed to help with.

### 2.2 Dead-instrument recovery is structurally assumed

A second shared assumption, smaller in effect. `eval/recovery_class.py` maps
`card_expired` / `token_invalid` / `mandate_revoked` to `CUSTOMER_ACTION`;
`policy/taxonomy.yaml` independently declares the same and sets `max_retries: 0`.
The simulator then hard-codes the matching zero in `eval/payer_model.py`:

```python
# Structural invariant: dead instruments never recover via retry alone.
if recovery_class_for(case.visible.failure_reason) == RecoveryClass.CUSTOMER_ACTION:
    return False
```

Dead instruments are 30% of the batch (0.16 + 0.08 + 0.06 in `eval/batch.py`), so
B2 retries into a guaranteed zero while we send a link instead. Encoded, not
discovered.

In reality the zero is not exact: Visa Account Updater and Mastercard Automatic
Billing Updater silently refresh stored cards, so some retries on "expired" cards
do succeed. Replacing the hard zero with a small non-zero probability is the
correct fix and is not implemented.

### 2.3 `wasted_attempts` is favourable by definition

`eval/simulate.py` defines a wasted attempt *as* a retry against
`CUSTOMER_ACTION`. A policy that never retries dead instruments therefore scores
zero wasted attempts **by construction** — and we duly report 0 vs 258.

That is a restatement of our own taxonomy, not an independent finding. Read it as
a description of behaviour, not as evidence. It should not appear on a slide as if
it were a discovered result.

### 2.4 The classifier is a perfect oracle

In the batch, the policy reads the **true** failure reason directly
(`policy/engine.py`, `policy_ours_from_taxonomy` passes `v.failure_reason.value`
verbatim). Nothing injects misclassification, and every reason in the decline mix
maps cleanly in `fixtures/decline_codes.json`, so the classifier returns
`confidence=1.0` on every batch case.

In production, issuer reason codes are unreliable and `do_not_honour` is a
catch-all hiding several distinct causes.

Since our entire advantage comes from knowing the cause (§2.1), the untested
question is how fast that advantage decays as classification degrades. **We have
not run this experiment.** The design is specified in §3.4.

### 2.5 Absolute recovery rates are not benchmarked

Recovery rates in the 70–78% range are a property of the priors we chose in
`eval/payer_model.py` (`base_contact_response_prob`, `retry_success_if_funded`,
`natural_recovery_prob`). They are **not** validated against real dunning
performance, which is generally reported much lower.

We claim only the **delta between two policies on an identical seeded batch under
stated assumptions.** No number in this repository should be read as "this agent
recovers 74% of failed payments in production." Where older sprint documents
compare our target against industry ranges, that was goal-setting for a simulator
knob, not a claim of parity with production systems.

### 2.6 The fatigue curve is one number doing a lot of work

Each prior contact multiplies response probability by **0.55**
(`eval/payer_model.py`, `FatigueState.response_prob`). This single assumption
drives much of the contacts-per-recovery story. It has no source. A sensitivity
sweep at 0.40 / 0.55 / 0.70 is the obvious check and has not been run.

### 2.7 The decline mix is estimated

`DECLINE_WEIGHTS` in `eval/batch.py` is estimated from public industry commentary
patterns, **not** from Razorpay data. Change the mix and the headline changes —
particularly since the edge is concentrated in a single reason whose weight we
chose (§2.1).

### 2.8 Everything published is a single seed

All results in this repository are **seed 42**, at n=200/500/1000. The harness
supports `--multi-seed` and `--seeds 42-51`, and those commands appear in
[METHODOLOGY.md](METHODOLOGY.md), but **we never published the sweep.** It remains
an open follow-up in [METRICS_FINAL_REPORT.md](METRICS_FINAL_REPORT.md).

Single-seed reporting cannot distinguish a real effect from a favourable draw. The
direction held across three batch sizes on this seed, which is weak evidence of
stability, not proof of it. This is the cheapest remaining fix and the one we would
do first.

---

## 3. AI limitations

### 3.1 The headline batch benchmark is deterministic — the LLM is not in it

No module under `eval/` imports the LLM, the Ollama client, or the RAG layer. The
batch path is `eval/harness.py` → `policy_ours_from_taxonomy` → `engine.decide()`,
which is pure rules. The CLI says so itself:

```python
help="Run our cause-aware taxonomy policy (batch path; not live LLM)"
```

**This is deliberate.** Making an n=500 benchmark depend on a local 8B model would
destroy reproducibility, tie the headline to sampling temperature, break the demo
whenever Ollama is slow, and measure model variance instead of policy quality. It
is recorded as a design decision in [WHAT_BROKE.md](WHAT_BROKE.md) §3.

**The cost of that decision:** we cannot quantify the LLM's contribution in rupees,
and we do not try. Any reading of the headline number as an "AI improvement" is a
misreading, and we have tried to make that misreading impossible throughout the
documentation.

### 3.2 What the LLM actually contributes

Real, but narrower than the project title suggests. On the case path only
(`ai/agent.py`, reached via `POST /agent/run` and the UI demo):

| Contribution | Constraint |
|---|---|
| Failure diagnosis | Pydantic-validated; `likely_class` clamped to taxonomy keys, else rules classifier |
| Action proposal | `verb` is a closed enum; unknown verbs fail parsing → full rules fallback |
| Customer message drafting | Contact verbs only; on failure a canned template, action unchanged |

Every proposal then passes `policy/engine.py::validate_proposal`, which repairs
rather than trusts. Retrieved episodes (Inherent/RAG) enter the prompts as
**evidence text only** — they cannot override the validator or the gates, and when
Ollama is down they have no effect on the action at all.

### 3.3 No AI evaluation exists

There is **no measured LLM claim** in this repository:

- No accuracy figure on free-text declines
- No LLM-vs-rules comparison on recovery or INR
- No confusion matrix
- No labelled dataset of ambiguous failure reasons

The AI tests (`tests/test_ai_phase5.py` and friends) verify **plumbing** —
structured output parsing, taxonomy clamping, graceful fallback when Ollama is
down. They do not measure judgement quality. Mentions of an AI ablation in the
historical planning documents were **deferred and never run**.

Note also that the `ambiguous` branch of `diagnose/classifier.py` is **never
exercised by the batch**, because every reason in the decline mix maps cleanly.
The code path where the LLM would add the most value is the one the benchmark
never touches.

### 3.4 Classifier errors are a safety problem, not just an accuracy problem

This is the AI limitation we would rank highest, because it has teeth.

`gate_prohibited_recovery` keys off the **classifier's** output, not an independent
signal. A fraud case misread as a generic decline would therefore **bypass the
fraud gate entirely.** The gate is only as trustworthy as the label feeding it.

In production that gate should read an independent risk signal — the risk engine's
own verdict, not a text classification of the decline reason. Naming this is more
useful than claiming the gate is unconditionally safe.

**The experiment we would run**, specified but not implemented: add an
`observed_failure_reason` to `VisibleCase`; corrupt it at 0/5/10/15/20/30% using
plausible confusion pairs (NSF ↔ `do_not_honour`, `card_expired` ↔
`token_invalid`) rather than uniform random labels; keep every ground-truth call
site on the true reason so the simulator stays honest; and use B2 as an invariant
control, since a cause-blind policy should be unaffected by classifier noise. The
metric is how much of the net advantage survives at each noise level.

---

## 4. Safety limitations

| Area | State |
|---|---|
| **Endpoint auth** | **None.** Every route is unauthenticated, including mutating ones |
| **Webhook signature** | HMAC-SHA256 with `hmac.compare_digest`; **fails closed**. Unsigned bypass requires an explicit `ALLOW_UNSIGNED_WEBHOOKS=1`, is impossible under `APP_ENV=production`, and is logged on every use |
| **Webhook replay** | Covered by the `processed_events` unique constraint on `event_id` |
| **Action idempotency** | Durable — rebuilt from `kind=action` ledger rows. Residual race in §4.1 |
| **PII** | Structured logs drop `phone`/`email`/`pan`/`card`/`body`/`raw`; LLM prompts receive amount *buckets*, never raw identifiers |
| **Rate limiting** | None |

### 4.1 Idempotency is durable but check-then-act

The action idempotency gate is **ledger-backed**: `ledger/reader.py::executed_fingerprints`
replays `kind=action` rows for the case, and `guard/pipeline.py` hydrates that set
before the gates run. This is what makes it survive a process restart or a
separate request — the property that matters for "did this already execute?"

It is **not** constraint-backed. Both action idempotency and webhook event dedup
are check-then-act: two genuinely concurrent requests can each observe "not yet
executed" before either commits. The production fix is a unique constraint on
`(case_id, fingerprint)` with the resulting `IntegrityError` caught and converted
to a duplicate response.

Scoped out for the hackathon. Single-request duplication **is** blocked and tested
(`tests/test_idempotency_durable.py`).

### 4.2 The fraud gate is inert on the generic execute endpoint

`gate_prohibited_recovery` only fires when `ctx.failure_class == "risk_fraud"`. The
live `POST /execute/run` path **never populates `failure_class`** on the guard
context, so on that endpoint the gate cannot fire. It works where the caller sets
it explicitly, which today means the fraud demo path (`demo/live_flow.py`).

So the fraud gate is genuinely implemented and genuinely demonstrable, but it is
**not yet wired into every path that can move money.** Threading classification
through to the execute endpoint is a small change we did not make, and we would
rather state that than let the gate table imply blanket coverage.

### 4.3 Reconciliation covers the Razorpay path only

`execute/reconcile.py` fetches payment status and treats
`captured`/`authorized`/`paid` as already-succeeded. It is wired into
`execute/razorpay_adapter.py::_retry_with_reconcile`, and only when the verb is
`schedule_retry`, a `payment_ref` exists, and dry-run is off.

It is **not** in the sim executor — which is the default mode
(`EXECUTOR_MODE=sim`) and the one the batch evaluation uses — because there is no
gateway to query. If `payment_ref` is missing or dry-run is on, reconciliation is
skipped and the retry intent is recorded anyway.

Therefore: a real safeguard on the real-money path, **not** a universal
double-charge guarantee. No number in the batch evaluation was produced with
reconciliation active.

### 4.4 Card-network retry caps are counted, never enforced

`eval/costing.py` flags a breach when a case's retries exceed
`scheme_limits.max_attempts_per_transaction_30d`, which is **15**. No policy here
issues more than 7 retries (B3), and ours caps at 4, so **the counter is always
0**. `attempt.network_excess_retry_penalty` is priced at `0.0`, so the cost path
is inert too.

No gate in `guard/gates.py` references scheme limits at all. Live enforcement is
`gate_attempt_cap` with a default `max_attempts=3` — a different, lower, per-case
cap that is not network-aware.

Related: `scheme_limits.max_attempts_hard_decline` (value `1`) is defined in
`config/costs.json` and **read by no code.** Wiring it up — one attempt maximum on
a dead instrument — would produce a genuinely differentiating compliance number,
since B2 retries 3× on every case regardless of cause. Identified, not
implemented.

We describe this as measured rather than enforced everywhere it appears, because a
compliance-first architecture that knowingly counts a violation without blocking it
would be making a claim it has not earned.

### 4.5 No regulatory compliance implementation

There is **no RBI, e-mandate, pre-debit notification, or AFA logic in this
codebase.** What exists:

| Item | Status |
|---|---|
| Mandate revoked/expired block | Implemented — a simplified enum check |
| Mandate `unknown` | **Allowed through** |
| Mandate `paused` | **Allowed through** (not in the blocked set) |
| `mandate_cap_paise` | Schema field only, **never checked** |
| Contact window 09:00–21:00 IST | Implemented — general anti-spam, not RBI-derived |
| Pre-debit notification | **Absent** |
| AFA / re-authentication | **Absent** (a UI label only) |
| E-mandate lifecycle rules | **Absent** — `MandateState` is explicitly a simplified lifecycle |

`gate_mandate_validity` is a sensible engineering check that happens to align with
the spirit of mandate rules. Calling it regulatory compliance would be false, and
we do not. Implementing real e-mandate requirements would start with verifying the
current framework text rather than working from memory of the thresholds.

---

## 5. Economic limitations

### 5.1 Most cost inputs are assumptions

`config/costs.json` tags every priced input with a `source`. Of 13 parameters,
**11 are `ASSUMPTION`**; only `success.mdr_pct` is `published` and only
`attempt.psp_fee_on_failed_attempt` is `dashboard`.

The most consequential guesses:

| Parameter | Why it matters |
|---|---|
| `customer.ltv` | Scales the entire churn penalty |
| `churn_prob_per_inappropriate_contact` | Drives the contacts-per-recovery advantage |
| `risk.issuer_auth_decay_pct_per_excess_attempt` | Marked unsourceable in the file itself |

Net INR is therefore **model-dependent**. The cost model is transparent and
swappable — that is the point of putting it in a config file — but it is not
audited, and simulated MDR is not a quoted merchant rate.

### 5.2 Forgone recovery is the right idea, priced with guesses

`forgone_recovery_inr` records money the system **chose not to pursue** — for
example when the fraud gate blocks a recovery attempt. We think this is the
economically honest way to score a safety-first system: otherwise "we blocked it"
is an unfalsifiable virtue and the `PROHIBITED` segment looks like a bug rather
than a decision.

But its magnitude inherits every assumption in §5.1. It demonstrates that we
priced the trade-off, not that we priced it *correctly*.

### 5.3 Churn and LTV are the softest numbers here

Churn probability per inappropriate contact and customer LTV are the two inputs
with the least defensible provenance and among the largest leverage on net INR.
A reviewer who disagrees with them should be able to change two config values and
re-run — that is deliberate — but they should know the headline moves when they do.

---

## 6. Production gaps

Separated from hackathon scope, and named concretely rather than as "needs
scaling".

### 6.1 Deliberate hackathon scope

| Choice | Production requirement |
|---|---|
| No API authentication on any route | Auth on every mutating endpoint, scoped service credentials |
| SQLite with WAL and a 60s busy timeout | Postgres; SQLite contends under concurrent writers |
| `Base.metadata.create_all()` at startup | Alembic migrations with reviewable version history |
| Check-then-act idempotency | Unique constraint on `(case_id, fingerprint)` + `IntegrityError` handling |
| No rate limiting | Per-caller limits on execute and webhook routes |
| Sim executor by default | Real gateway with reconciliation on every uncertain outcome (§4.3) |

### 6.2 Concrete code-level gaps

- **Async hygiene:** several routes are `async def` but perform synchronous DB and
  HTTP work, blocking the event loop. Correct at demo scale, wrong under load.
- **Query efficiency:** `find_case_id_by_plink` scans outcome rows in Python
  rather than querying an indexed column.
- **Observability:** structured stdout logs only. No metrics endpoint, no tracing,
  no error-handling middleware, no request IDs.
- **Fraud classification path:** `failure_class` is not threaded through
  `/execute/run` (§4.2).

### 6.3 Illustrative UI screens

`/ui/cases`, `/ui/intelligence`, `/ui/intelligence/strategies`, and
`/ui/intelligence/historical` render hand-authored sample content from
`api/ui_mock.py` to show the intended product surface. Each carries an
**"Illustrative data"** banner.

Measured numbers appear in exactly two places: the Stats screen (`/ui`), which
renders only from a stored `EvalRunRecord` and shows an em dash when no run
exists, and real case trails under `/cases/{id}`, which read from the ledger. **No
screen displays a rupee value that was not computed** — enforced by
`tests/test_ui_honesty.py`.

---

## 7. What would change our conclusions?

The point of the sections above is not self-flagellation; it is knowing which
experiment to run next. In descending order of how much each would move our
confidence:

### 7.1 Evidence that would *reduce* our confidence

| Experiment | What a negative result would show |
|---|---|
| **Widen the simulator's payday draw** to 1–28 (§2.1) | If the NSF edge largely vanishes, our headline was mostly measuring the shared assumption, and the honest claim shrinks to "correct timing matters when you know the timing" |
| **Classifier-noise sweep**, 0–30% (§3.4) | If the advantage decays fast, cause-aware policy is fragile exactly where production data is weakest, and the oracle assumption was carrying the result |
| **Non-zero dead-instrument recovery** (§2.2) | If account-updater refreshes make retries partly effective, our zero-retry rule is over-aggressive and B2's brute force is less wasteful than we score it |
| **Fatigue sweep** at 0.40 / 0.70 (§2.6) | Would recalibrate or eliminate the contacts-per-recovery story |
| **Multi-seed sweep**, 42–51 (§2.8) | If the advantage is unstable across seeds, seed 42 was a favourable draw |

We list these first on purpose. Each one is a way our own result could turn out to
be weaker than advertised, and none of them is hard to run.

### 7.2 Evidence that would *increase* our confidence

| Evidence | What it would establish |
|---|---|
| **Real historical failure data** — decline mix and issuer code distribution from actual traffic | Replaces the estimated `DECLINE_WEIGHTS` (§2.7) and the payer priors with observed ones |
| **Real recovery outcomes** from a live dunning system | The first genuine calibration of absolute recovery rates (§2.5) |
| **A randomised policy experiment** on real traffic | The only design that breaks the circularity in §2.1, because the payer's behaviour is no longer something we authored |
| **A labelled ambiguous-decline dataset** with measured LLM vs rules accuracy (§3.3) | Converts our AI story from architectural to quantitative — starting with `do_not_honour`, the class we currently lose |
| **Independent risk signal wired into the fraud gate** (§3.4) | Removes the classifier as a single point of failure for the safety-critical gate |
| **Compliance review against the current e-mandate framework** (§4.5) | Would let us make a compliance claim at all, which today we cannot |

### 7.3 What we would do next, in order

1. **Widen the payday distribution** (§2.1) and report surviving edge. This is the
   one that most changes what we are allowed to claim.
2. **Publish the multi-seed sweep** (§2.8). Cheapest credibility fix available.
3. **Run the classifier-noise sweep** (§3.4). Converts the weakest claim into a
   measured one.
4. **Build the ambiguous free-text dataset** (§3.3), starting with `do_not_honour`.
5. **Replace the dead-instrument hard zero** with an account-updater probability
   (§2.2).
6. **Close the idempotency race** with a DB constraint (§4.1).
7. **Enforce retry caps** by wiring `max_attempts_hard_decline` into a gate (§4.4).
8. **Thread `failure_class` through `/execute/run`** so the fraud gate is live
   everywhere (§4.2).

Items 1–3 change what we may claim. Items 4–8 change what the system does. We
ranked the epistemics above the features on purpose.
