"""
execute/razorpay_adapter.py — real test-mode edge (Payment Links).

Creates a Razorpay Payment Link for contact verbs.
For schedule_retry: reconcile existing payment_ref first when present.

Auth: HTTP Basic with key_id:key_secret (test mode keys only).
"""

from __future__ import annotations

import os
from typing import Any, Optional
from uuid import uuid4

import httpx
from dotenv import load_dotenv

from execute.base import ExecuteMeta, Outcome
from execute.reconcile import already_succeeded, fetch_payment
from ledger.models import CaseRow
from policy.schemas import Action, ActionVerb

load_dotenv()

API_BASE = os.getenv("RAZORPAY_API_BASE", "https://api.razorpay.com/v1").rstrip("/")


class RazorpayExecutor:
    name = "razorpay"

    def __init__(
        self,
        key_id: Optional[str] = None,
        key_secret: Optional[str] = None,
        client: Optional[httpx.Client] = None,
    ) -> None:
        self.key_id = key_id or os.getenv("RAZORPAY_KEY_ID", "")
        self.key_secret = key_secret or os.getenv("RAZORPAY_KEY_SECRET", "")
        self._client = client
        self.dry_run = os.getenv("RAZORPAY_DRY_RUN", "0") == "1" or self.key_id.endswith(
            "xxx"
        )

    def run(self, action: Action, case: CaseRow, meta: ExecuteMeta) -> Outcome:
        if action.verb == ActionVerb.escalate_human:
            return Outcome(
                ok=True,
                external_id=None,
                status="escalated",
                note="no_razorpay_call",
            )

        if action.verb == ActionVerb.schedule_retry:
            return self._retry_with_reconcile(action, case, meta)

        if action.verb in {
            ActionVerb.send_payment_link,
            ActionVerb.request_mandate_update,
        }:
            return self._create_payment_link(action, case, meta)

        return Outcome(ok=False, status="failed", note="unsupported_verb")

    def _retry_with_reconcile(
        self, action: Action, case: CaseRow, meta: ExecuteMeta
    ) -> Outcome:
        """
        Never blind-retry a timeout without checking status first.
        """
        pay_id = meta.payment_ref
        if pay_id and not self.dry_run:
            try:
                payment = fetch_payment(
                    pay_id,
                    key_id=self.key_id,
                    key_secret=self.key_secret,
                    client=self._client,
                )
                if already_succeeded(payment):
                    return Outcome(
                        ok=True,
                        external_id=pay_id,
                        recovered=True,
                        status="reconciled_skip",
                        note="payment_already_succeeded_skip_retry",
                        raw=payment,
                    )
            except Exception as exc:
                return Outcome(
                    ok=False,
                    external_id=pay_id,
                    status="failed",
                    note=f"reconcile_failed:{exc}",
                )

        # Test-mode recurring charge APIs vary; for the hackathon edge we
        # record intent and let sim/metrics handle scale retries.
        return Outcome(
            ok=True,
            external_id=pay_id or f"retry_intent_{case.id[:8]}",
            recovered=False,
            status="ok",
            note="retry_intent_recorded_after_reconcile",
            raw={"dry_run": self.dry_run, "day_offset": action.day_offset},
        )

    def _create_payment_link(
        self, action: Action, case: CaseRow, meta: ExecuteMeta
    ) -> Outcome:
        amount = action.amount_paise if action.amount_paise is not None else case.amount_paise
        reference = f"recovery_{case.id}"

        if self.dry_run or meta.dry_run:
            plink = f"plink_test_{uuid4().hex[:10]}"
            return Outcome(
                ok=True,
                external_id=plink,
                recovered=False,
                status="created_link",
                note="dry_run_payment_link",
                raw={
                    "dry_run": True,
                    "amount": amount,
                    "reference_id": reference,
                    "short_url": f"https://rzp.io/i/{plink}",
                },
            )

        payload: dict[str, Any] = {
            "amount": amount,
            "currency": "INR",
            "accept_partial": False,
            "reference_id": reference[:40],
            "description": f"Recovery link for case {case.id}",
            "reminder_enable": False,
            "notes": {
                "case_id": case.id,
                "failure_reason": meta.failure_reason,
                "verb": action.verb.value,
            },
        }

        own = self._client is None
        client = self._client or httpx.Client(timeout=30.0)
        try:
            r = client.post(
                f"{API_BASE}/payment_links",
                auth=(self.key_id, self.key_secret),
                json=payload,
            )
            if r.status_code >= 400:
                return Outcome(
                    ok=False,
                    status="failed",
                    note="payment_link_http_error",
                    raw={"status_code": r.status_code, "body": r.text[:500]},
                )
            data = r.json()
            plink_id = data.get("id")
            return Outcome(
                ok=True,
                external_id=plink_id,
                recovered=False,
                status="created_link",
                note="razorpay_payment_link_created",
                raw=data,
            )
        except Exception as exc:
            return Outcome(ok=False, status="failed", note=f"payment_link_exc:{exc}")
        finally:
            if own:
                client.close()
