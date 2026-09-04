# Limitations — what this project does not prove

Written by the builder, before anyone had to ask. Every claim in this repo has a
boundary; this page is where the boundaries live. If you are reviewing the code,
read this alongside [SCORING.md](SCORING.md) and [METHODOLOGY.md](METHODOLOGY.md).

Short version: **the architecture is the contribution; the rupee figures are a
ranking under stated assumptions, not a measurement of merchant lift.**

---

## 1. The policy searches exactly where the simulator hides the answer (the big one)

This is the single most important caveat, and it is worth being precise about
because the headline is more concentrated than it looks.

At seed 42, n=500, the **entire** gross advantage comes from one failure reason:

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
`max_retries: 4` in `taxonomy.yaml` to cover four of the seven. B2, a blind
fixed ladder, retries on arbitrary days and mostly misses the window.

**Consequence:** the NSF result is close to a tautology. We are not measuring
"cause-aware timing beats blind retry in the real world"; we are measuring that a
policy which knows the generative model beats one that does not. The direction is
defensible on domain grounds — Indian salary credits really do cluster early in
the month, and timing NSF retries to payday really is standard practice — but
**the magnitude is an artefact of the two files agreeing.**

The honest fix, designed but not run: widen the simulator's `credit_day` draw
(e.g. 1–28, or a mixture with a mid-month cluster) so the policy's 1–7 fan-out is
no longer a perfect cover, then report how much edge survives. We expect it to
shrink substantially.

Note also that this repo's advantage is **not** where the narrative suggests:
dead instruments contribute only +21,184, and Ours actually **loses** on four of
eight reasons (−20,084 combined), most notably `do_not_honour`, the ambiguous
class the LLM is supposed to help with.

## 2. Dead-instrument recovery is structurally assumed

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
B2 retries into a guaranteed zero while we send a link instead. Again encoded, not
discovered. In reality the zero is not exact: Visa Account Updater and Mastercard
Automatic Billing Updater silently refresh stored cards, so some retries on
"expired" cards do succeed. Replacing the hard zero with a small non-zero
probability is the correct fix and is not implemented.

## 3. `wasted_attempts` is favourable by definition

`eval/simulate.py` defines a wasted attempt *as* a retry against
`CUSTOMER_ACTION`. A policy that never retries dead instruments therefore scores
zero wasted attempts by construction — and indeed we report exactly **0 vs 258**.
That is a restatement of our own taxonomy, not an independent finding. Read it as
a description of behaviour, not as evidence.

## 4. The classifier is a perfect oracle

In the batch, the policy reads the true failure reason directly
(`policy/engine.py`, `policy_ours_from_taxonomy`). Nothing injects
misclassification. In production, issuer reason codes are unreliable and
`do_not_honour` is a catch-all that hides several distinct causes.

Since our entire advantage comes from knowing the cause, the untested question
is how fast that advantage decays as classification degrades. **We have not run
this experiment.** The design is specified: add an `observed_failure_reason` to
`VisibleCase`, corrupt it at rates 0–30% using plausible confusion pairs
(NSF ↔ `do_not_honour`, `card_expired` ↔ `token_invalid`), keep every
ground-truth call site on the true reason, and use B2 as an invariant control
because it is cause-blind.

There is also a known failure mode worth naming: `gate_prohibited_recovery`
keys off the *classifier's* output, so a fraud case misread as a generic decline
would bypass the fraud gate. In production that gate should read an independent
risk signal rather than the classifier's label.

## 5. Absolute recovery rates are not benchmarked

Recovery rates in the 70–78% range are a property of the priors we chose in
`eval/payer_model.py` (`base_contact_response_prob`, `retry_success_if_funded`,
`natural_recovery_prob`). They are **not** validated against real dunning
performance, which is generally reported much lower.

We claim only the **delta between two policies on an identical seeded batch
under stated assumptions**. We do not claim the absolute level, and no number in
this repo should be read as "this agent recovers 74% of failed payments in
production."

## 6. Most cost inputs are assumptions

`config/costs.json` tags every priced input with a `source`. Of 13 parameters,
**11 are `ASSUMPTION`**; only `success.mdr_pct` is `published` and only
`attempt.psp_fee_on_failed_attempt` is `dashboard`. The most consequential
guesses are `customer.ltv`, `churn_prob_per_inappropriate_contact`, and
`risk.issuer_auth_decay_pct_per_excess_attempt` (the last is explicitly marked
unsourceable in the file itself).

Net INR is therefore model-dependent. The cost model is transparent and swappable
— that is the point of the file — but it is not audited.

## 7. The fatigue curve is one number doing a lot of work

Each prior contact multiplies response probability by **0.55**
(`eval/payer_model.py`, `FatigueState.response_prob`). This single assumption
drives much of the contacts-per-recovery story. It has no source. A sensitivity
sweep at 0.40 / 0.55 / 0.70 is the obvious check and has not been run.

## 8. The decline mix is estimated

`DECLINE_WEIGHTS` in `eval/batch.py` is estimated from public industry
commentary patterns, **not** from Razorpay data. Change the mix and the headline
changes.

## 9. The AI is not in the headline number

The batch path uses taxonomy rules, not the LLM (`eval/harness.py` →
`policy_ours_from_taxonomy`). This is deliberate: making n=500 depend on a local
8B model would destroy reproducibility and break the demo whenever Ollama is
slow or down. It is recorded as a design decision in [WHAT_BROKE.md](WHAT_BROKE.md).

The cost of that decision is that **we cannot quantify the LLM's contribution in
rupees**, and we do not try. The LLM's role is real but narrower than the project
title suggests: diagnosis, action proposal, and message drafting on the case
path, always bounded by `validate_proposal` and the gates.

What we would need to make a defensible AI claim: a labeled set of free-text
decline strings that the deterministic map returns `ambiguous` for, and a
measured accuracy comparison. Not built. Note that the `ambiguous` branch of
`diagnose/classifier.py` is **never exercised by the batch**, because every
reason in `DECLINE_WEIGHTS` maps cleanly in `fixtures/decline_codes.json`.

## 10. `scheme_cap_breaches` is currently inert

`eval/costing.py` flags a breach when a case's retries exceed
`scheme_limits.max_attempts_per_transaction_30d`, which is **15**. No policy in
this repo issues more than 7 retries (B3), and ours caps at 4. **The counter is
therefore always 0**, and `attempt.network_excess_retry_penalty` is priced at
`0.0`, so the cost path is inert too.

Related: `scheme_limits.max_attempts_hard_decline` (value `1`) is defined in
`config/costs.json` and **read by no code**. Wiring it up — one attempt maximum
on a dead instrument — would produce a genuinely differentiating compliance
number, since B2 retries 3× on every case regardless of cause. Identified, not
implemented.

## 11. Security is hackathon-scoped, deliberately

| Area | State |
|---|---|
| Endpoint auth | **None.** Every route is unauthenticated, including mutating ones |
| Webhook signature | HMAC-SHA256 with `hmac.compare_digest`; **fails closed**. The unsigned bypass now requires an explicit `ALLOW_UNSIGNED_WEBHOOKS=1`, is impossible under `APP_ENV=production`, and is logged on every use |
| Webhook replay | Covered by the `processed_events` unique constraint on `event_id` |
| Action idempotency | Durable — rebuilt from `kind=action` ledger rows. Residual gap below |
| PII | Structured logs drop `phone`/`email`/`pan`/`card`/`body`/`raw`; LLM prompts receive amount *buckets*, never raw identifiers |
| Rate limiting | None |

**Known race:** idempotency and event dedup are both check-then-act. Two truly
concurrent requests can each observe "not yet executed" before either commits.
The production fix is a unique constraint on `(case_id, fingerprint)` with the
resulting `IntegrityError` caught and converted to a duplicate response. Scoped
out for the hackathon; single-request duplication is blocked and tested
(`tests/test_idempotency_durable.py`).

## 12. Operational shortcuts

- **Schema:** `Base.metadata.create_all()` at startup, no Alembic migrations.
- **Database:** SQLite with WAL and a 60s busy timeout. Fine for one process;
  concurrent writers can still contend.
- **Async hygiene:** several routes are `async def` but perform synchronous DB
  and HTTP work, which blocks the event loop under load. Correct at demo scale,
  wrong at production scale.
- **Queries:** `find_case_id_by_plink` scans outcome rows in Python rather than
  querying by an indexed column.
- **Observability:** structured stdout logs only. No metrics endpoint, no
  tracing, no error-handling middleware or request IDs.

## 13. Illustrative UI screens

`/ui/cases`, `/ui/intelligence`, `/ui/intelligence/strategies`, and
`/ui/intelligence/historical` render hand-authored sample content from
`api/ui_mock.py` to show the intended product surface. Each carries an
**"Illustrative data"** banner.

Measured numbers appear in exactly two places: the Stats screen (`/ui`), which
renders only from a stored `EvalRunRecord` and shows an em dash when no run
exists, and real case trails under `/cases/{id}`, which read from the ledger.
No screen displays a rupee value that was not computed.

---

## What we would do next, in order

1. Widen the simulator's `credit_day` draw so the policy's 1–7 fan-out is no
   longer a perfect cover, and report how much of the NSF edge survives (§1).
   This is the one that most changes what we are allowed to claim.
2. Run the classifier-noise sweep (§4) — converts the weakest claim into a
   measured one.
3. Replace the dead-instrument hard zero with an account-updater probability and
   report the sensitivity (§2).
4. Wire up `max_attempts_hard_decline` as a real gate (§10).
5. Build the free-text classification dataset so the AI claim becomes
   quantitative (§9), starting with `do_not_honour` — the class we currently
   lose on.
6. Persist idempotency with a DB constraint to close the race (§11).
