# Compliance — gates, stops, and audit

How this agent stays safe enough for a payments audience.

## Principle

**AI proposes. Policy validates. Gates may refuse. Stops terminate. The ledger never lies.**

We do not let the model execute money or contact actions unbound.

## Gates (per-action veto)

Implemented in `guard/gates.py`. Every check is written to the ledger (`kind=gate_check`), pass **or** block.

| Gate | Blocks when | Why |
|---|---|---|
| `contact_window` | Outbound contact outside IST 09:00–21:00 | No midnight nags |
| `frequency_cap` | `contacts_used >= max_contacts` (default 2) | Anti-spam |
| `mandate_validity` | Mandate revoked/expired on money actions | Dead mandate ≠ retry |
| `attempt_cap` | `attempts_used >= max_attempts` (default 3) | Fee / fatigue ceiling |
| `idempotency` | Same action fingerprint already executed | No double charge / double message |

Silent `schedule_retry` is **not** blocked by contact window (only customer-facing contact is).

## Stops (terminal)

Implemented in `guard/stops.py`. Once stopped/recovered, `guard_and_maybe_execute` will not call adapters.

| Stop reason | Meaning |
|---|---|
| `recovered` | Money recovered; halt automation |
| `mandate_revoked` | Structural death of rail |
| `attempt_cap` | Exhausted retries/contacts budget |
| `opt_out` | Payer asked to stop |
| `human_override` | Ops took the case |

**Gate block ≠ stop.** A night-time window block can retry next morning. A stop closes the case.

## Webhook / secrets

- Verify `X-Razorpay-Signature` with HMAC-SHA256 (`ingest/verify.py`).
- Keys only in `.env` (never git). See `.env.example`.
- Do not log full webhook bodies or phone/email/PAN.
- Structured logs use `case_id`, `event_id`, `verb`, `gate` only (`logging_util.py`).

## Timeout / double-charge

For `gateway_timeout`-class retries, Razorpay adapter **reconciles** existing `payment_ref` before scheduling another attempt (`execute/reconcile.py`). If already `captured`/`authorized`, status = `reconciled_skip`.

## PII in LLM prompts

`CaseContext` sends amount **buckets**, decline codes, rail — not phone, email, card PAN, or legal name (`ai/schemas.py`).

## Demo of refusal (feature, not bug)

`POST /guard/check` or the demo case trail (`/demo/replay`) shows an AI/proposal path where `contact_window` **blocks**. Judges should see refusal in the ledger.

## Checklist for operators

- [ ] Test-mode Razorpay keys only in demo
- [ ] Webhook secret set before public tunnel
- [ ] `RAZORPAY_DRY_RUN=0` only when intentionally creating real test links
- [ ] Batch claims cite seed + methodology assumptions
