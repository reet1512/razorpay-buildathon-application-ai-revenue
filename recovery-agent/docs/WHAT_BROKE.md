# What broke, and how we got out

A build log of the things that actually went wrong, kept because the failures
explain most of the design decisions.

## 1. Broken system Python on Windows

**Broke:** `Python312\python.exe` was missing; winget repair failed with 1603 and
Microsoft Store stubs were shadowing `python` on PATH.

**Got out:** Set up a project-local embeddable runtime at `Rz/tools/python312/`
with a `tools/python.cmd` shim. That directory is gitignored and local-only — the
supported path for anyone cloning the repo is an ordinary virtualenv, which is
what the README and CI both use.

**Aftertaste:** the embeddable runtime's `._pth` excludes the working directory,
so `python -m eval.harness` raises `ModuleNotFoundError: No module named 'eval'`
while `python eval/harness.py` works (the script inserts its own path). Commands
in docs and CI use the script form so they work under both runtimes.

## 2. OneDrive / editor locking plan files

**Broke:** Early plan documents with box-drawing characters caused open/sync
friction in Cursor on a OneDrive-backed folder.

**Got out:** ASCII-safe diagrams in `BUILD_PLAN.md` / `BUILD_TECH.md`, with the
source of truth kept in repo markdown rather than in the editor.

## 3. Batch INR versus live AI

**Broke:** Wiring the n=500 batch through Ollama would have made the headline
number non-reproducible and would have broken the demo whenever the model was
slow or offline.

**Got out:** Split the paths. `eval.harness --policy ours` uses taxonomy rules and
is deterministic; `/agent/run` uses the live model with a `rules_fallback` exit.
The cost of this split — no rupee-denominated AI claim — is recorded in
[LIMITATIONS.md](LIMITATIONS.md) §9.

## 4. Webhook without a public URL

**Broke:** Razorpay cannot POST to `localhost`, so the live webhook loop could not
be exercised end to end during the build.

**Got out:** Built the full path (`ingest/verify` → `ingest/normalise` →
`/webhooks/razorpay`) and drove it with signed synthetic payloads in tests. ngrok
covers the live edge; `/demo/replay` is the offline backup for the video.

## 5. Accidental unsafe timeout retry

**Risk:** Blindly retrying after `gateway_timeout` can double-charge a payer whose
original attempt actually succeeded.

**Got out:** `execute/reconcile.py` fetches the existing payment's status before
scheduling another attempt and returns `reconciled_skip` when it is already
`captured` or `authorized`.

## 6. Webhook verification was fail-open by default

**Broke:** `verify_razorpay_signature` treated `APP_ENV=dev` — the value shipped in
`.env.example` — as consent to skip verification whenever the webhook secret was
still the `xxx` placeholder. A fresh clone therefore accepted **unsigned**
webhooks, which in a payments system means anyone could fabricate a
`payment_link.paid` and mark a case recovered.

**Got out:** Inverted the default. No usable secret now means reject. The bypass
requires an explicit `ALLOW_UNSIGNED_WEBHOOKS=1`, is refused outright under
`APP_ENV=production`, and emits a `webhook_signature_bypass` log line every time
it fires. Covered by `tests/test_phase9_hardening.py`.

**Lesson:** the HMAC itself was correct from day one, including
`hmac.compare_digest`. The vulnerability was entirely in the default.

## 7. Idempotency gate that could not actually stop a duplicate

**Broke:** `gate_idempotency` compared against `GuardContext.executed_fingerprints`,
an in-memory set. Every HTTP request built a fresh context, so the set was always
empty and posting the same action twice executed it twice — in a component whose
entire job was preventing double charges.

**Got out:** The fingerprint set is now rebuilt from the append-only ledger
(`ledger.reader.executed_fingerprints`, replaying `kind=action` rows) inside
`guard_and_maybe_execute`, so every call path inherits it rather than each caller
remembering to. Fingerprint composition moved into a single shared helper so the
live path and the ledger replay cannot drift apart.

**Still open:** it is check-then-act, so a true concurrent race remains. See
[LIMITATIONS.md](LIMITATIONS.md) §11.

## 8. A green test suite that was red on a clean clone

**Broke:** `tests/test_phase8_api_ui.py` and `tests/test_webhooks_paid.py` each set
`RAZORPAY_WEBHOOK_SECRET` at module import time. pytest imports every test module
before running any test, so the last import silently won and the other module's
webhook test got a 401. The suite passed locally only because of the order the
files happened to be collected in — `pytest -q` on a fresh clone failed.

**Got out:** Moved the secret into an autouse `monkeypatch` fixture in both files,
so it is scoped per test. The suite now passes in default order and in reverse
order.

**Lesson:** module-level `os.environ` writes in tests are shared mutable state.
This one was invisible for weeks because it only manifested as a wrong-looking
401 in an unrelated file.

## 9. Tests that only passed because of leftover local state

**Broke:** the very first CI run failed with
`sqlite3.OperationalError: no such table: processed_events`. Locally the same
suite was green.

`tests/test_fraud_gate_demo.py` reaches for the shared `SessionLocal` without
building its own engine and without going through `TestClient(app)` — so nothing
ever called `init_db()`. It passed on our machine purely because a `recovery.db`
from an earlier manual run already had the tables. On a clean clone, with no
database file, it failed.

**Got out:** added `tests/conftest.py` with a session-scoped autouse fixture that
calls `init_db()` before any test. Verified by pointing `DATABASE_URL` at a fresh
file: the failure reproduces exactly without the fixture and the full suite passes
with it.

**Lesson:** this is precisely the bug CI exists to catch, and we would not have
found it by hand — the local environment had silently accumulated the state the
test depended on. "Works on my machine" was literally true and completely
misleading.
