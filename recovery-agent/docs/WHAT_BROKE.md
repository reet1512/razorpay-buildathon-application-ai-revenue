# What broke, and how we got out

Fill this before submission (judges ask). Starter notes from this build:

## 1. Broken system Python on Windows

**Broke:** `Python312\python.exe` missing; winget repair failed (1603). Store stubs on PATH.

**Got out:** Project-local embeddable runtime at `Rz/tools/python312/` + `tools/python.cmd`. All docs use that runner.

## 2. OneDrive / editor locking plan files

**Broke:** Early plan docs with fancy characters caused open/sync friction in Cursor.

**Got out:** ASCII-safe diagrams in `BUILD_PLAN.md` / `BUILD_TECH.md`; keep source of truth in repo markdown.

## 3. Batch INR vs live AI conflict

**Broke:** Making n=500 call Ollama would destroy reproducibility and demos if the model is down.

**Got out:** Split paths — harness `--policy ours` = taxonomy rules; `/agent/run` = live AI with `rules_fallback`. Say it on stage.

## 4. Webhook without a public URL

**Broke:** Razorpay cannot POST to `localhost`.

**Got out:** Code path ready (`ingest/verify` + `normalise` + `/webhooks/razorpay`). Use ngrok for live edge; `/demo/replay` as video backup.

## 5. Accidental “unsafe” timeout retry

**Risk:** Blind retry after `gateway_timeout` can double-charge optics.

**Got out:** `execute/reconcile.py` fetches payment status before retry; `reconciled_skip` if already captured.

---

Add 1–2 **personal** failures from your last coding days (timestamps help). Keep each to 3–5 sentences.
