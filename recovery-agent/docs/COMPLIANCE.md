# Compliance — gates, stops, and audit

How this agent stays safe enough for a payments audience, and where that safety
currently stops.

> **Terminology note, since this doc is about precision:** this page uses
> "compliance" in the engineering sense — enforceable safety constraints on money
> movement and customer contact. It is **not** a claim of regulatory compliance.
> No RBI e-mandate, pre-debit notification, or AFA logic exists in this codebase.
> See [LIMITATIONS.md](LIMITATIONS.md) §4.5.

## Principle

**AI proposes. Policy validates and repairs. Gates may refuse. Stops terminate.
The ledger never lies.**

The model never executes money or contact actions unbound. Two distinct layers do
two distinct jobs:

| Layer | Power | Where |
|---|---|---|
| **Policy validator** | Rewrites an illegal proposal into the nearest legal action | `policy/engine.py::validate_proposal` |
| **Gates** | Allow or **block**. They never rewrite | `guard/gates.py` |

Keeping these separate matters when reading the code: a "repair" is a policy
decision, a "block" is a gate decision, and they appear differently in the ledger.

## Gates (per-action veto)

Implemented in `guard/gates.py`. **All six always run** so the audit trail is
complete; the action proceeds only if every one passes, and the reported
`blocked_by` is the first failure in order. Every check is written to the ledger
(`kind=gate_check`), pass **or** block.

| # | Gate | Blocks when | Why |
|---|---|---|---|
| 1 | `prohibited_recovery` | Failure class is `risk_fraud` and the action moves money or contacts the payer | No automated dunning against a flagged account |
| 2 | `contact_window` | Outbound contact outside IST 09:00–21:00 | No midnight nags |
| 3 | `frequency_cap` | `contacts_used >= max_contacts` (default 2) | Anti-spam |
| 4 | `mandate_validity` | Mandate revoked/expired on money actions | Dead mandate ≠ retry |
| 5 | `attempt_cap` | `attempts_used >= max_attempts` (default 3) | Fee / fatigue ceiling |
| 6 | `idempotency` | Same action fingerprint already executed for this case | No double charge / double message |

Silent `schedule_retry` is **not** blocked by the contact window — only
customer-facing contact is.

### Known coverage gaps

Stated here rather than in a footnote, because a gate table that omits its own
limits is misleading:

- **`prohibited_recovery` is inert on `POST /execute/run`.** That endpoint never
  populates `failure_class` on the guard context, so the gate cannot fire there.
  It works where the caller sets it explicitly — today the fraud demo path
  (`demo/live_flow.py`). Threading classification through the execute endpoint is
  an unfinished wiring job, not a claim. ([LIMITATIONS.md](LIMITATIONS.md) §4.2)
- **`prohibited_recovery` trusts the classifier.** It keys off a classified label,
  not an independent risk signal, so a fraud case misread as a generic decline
  bypasses it. In production this gate should read the risk engine's own verdict.
  ([LIMITATIONS.md](LIMITATIONS.md) §3.4)
- **`mandate_validity` is a simplified check.** It blocks `revoked` and `expired`.
  It allows `unknown` and `paused` through, and never checks `mandate_cap_paise`.
- **Card-network retry caps are measured, not enforced.** `scheme_cap_breaches` is
  counted in the evaluation economics; no gate blocks on it, and with current
  policies the counter is always 0. ([LIMITATIONS.md](LIMITATIONS.md) §4.4)
- **No endpoint authentication.** Every route, including mutating ones, is open.

## Stops (terminal)

Implemented in `guard/stops.py`. Once stopped or recovered,
`guard_and_maybe_execute` will not call adapters.

| Stop reason | Meaning |
|---|---|
| `recovered` | Money recovered; halt automation |
| `mandate_revoked` | Structural death of rail |
| `attempt_cap` | Exhausted retries/contacts budget |
| `opt_out` | Payer asked to stop |
| `human_override` | Ops took the case |

**Gate block ≠ stop.** A night-time window block can retry next morning. A stop
closes the case.

## Idempotency

The action idempotency gate is **ledger-backed**: on each request the pipeline
replays `kind=action` rows for the case (`ledger/reader.py::executed_fingerprints`)
to rebuild the set of fingerprints that already executed. This is what makes it
survive a process restart or a separate request, and it is tested in
`tests/test_idempotency_durable.py`.

It is **check-then-act, not atomic.** Two genuinely concurrent requests can each
observe "not yet executed" before either commits. The production fix is a unique
constraint on `(case_id, fingerprint)` with `IntegrityError` converted to a
duplicate response. ([LIMITATIONS.md](LIMITATIONS.md) §4.1)

Webhook replay is handled separately by the `processed_events` unique constraint
on `event_id` — also check-then-act.

## Webhook verification

- `X-Razorpay-Signature` verified with HMAC-SHA256 over the raw body, compared with
  `hmac.compare_digest` (`ingest/verify.py`).
- **Fails closed.** With no usable secret, requests are rejected with 401.
- The unsigned bypass requires an explicit `ALLOW_UNSIGNED_WEBHOOKS=1`, is
  **impossible** under `APP_ENV=production`, and logs `webhook_signature_bypass`
  on every use.
- Keys only in `.env`, never committed. See `.env.example` and
  `scripts/check_no_secrets.py`.
- Full webhook bodies are not logged or echoed.

## Timeout / double-charge

For `gateway_timeout`-class retries, the Razorpay adapter **reconciles** the
existing `payment_ref` before scheduling another attempt (`execute/reconcile.py`,
called from `execute/razorpay_adapter.py::_retry_with_reconcile`). If the payment
is already `captured`/`authorized`/`paid`, the status is `reconciled_skip` and no
retry is issued.

**Scope:** this runs on the live Razorpay `schedule_retry` path only, and only when
a `payment_ref` exists and dry-run is off. The simulated executor — the default
mode, and the one the batch evaluation uses — does not reconcile, because there is
no gateway to query. So this is a real safeguard on the real-money path, **not** a
universal double-charge guarantee. ([LIMITATIONS.md](LIMITATIONS.md) §4.3)

## PII

- Structured logs carry `case_id`, `event_id`, `verb`, `gate` only, and drop
  `phone`/`email`/`pan`/`card`/`body`/`raw` (`logging_util.py`).
- `CaseContext` sends the LLM amount **buckets**, decline codes, and rail — never
  phone, email, card PAN, or legal name (`ai/schemas.py`).

## Demo of refusal (feature, not bug)

`POST /guard/check`, the fraud-gate demo, and the demo case trail
(`POST /demo/replay`) all show a proposal path where a gate **blocks**. A reviewer
should be able to see refusal recorded in the ledger, not just success.

## Checklist for operators

- [ ] Test-mode Razorpay keys only in demo
- [ ] Webhook secret set before exposing a public tunnel
- [ ] `RAZORPAY_DRY_RUN=0` only when intentionally creating real test links
- [ ] `ALLOW_UNSIGNED_WEBHOOKS` unset outside local demos
- [ ] Batch claims cite seed + methodology assumptions
- [ ] No compliance claim made beyond what this page lists as implemented
