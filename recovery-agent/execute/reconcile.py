"""
execute/reconcile.py — fetch payment status before blind retries.

Teaching (timeout / double-charge):
1) If we already have payment_ref, GET it from Razorpay
2) If captured/authorized already -> do NOT retry (reconciled_skip)
3) Only then allow schedule_retry
"""

from __future__ import annotations

import os
from typing import Any, Optional

import httpx
from dotenv import load_dotenv

load_dotenv()

API_BASE = os.getenv("RAZORPAY_API_BASE", "https://api.razorpay.com/v1").rstrip("/")


def fetch_payment(
    payment_id: str,
    *,
    key_id: Optional[str] = None,
    key_secret: Optional[str] = None,
    client: Optional[httpx.Client] = None,
) -> dict[str, Any]:
    key_id = key_id or os.getenv("RAZORPAY_KEY_ID", "")
    key_secret = key_secret or os.getenv("RAZORPAY_KEY_SECRET", "")
    if not key_id or not key_secret or key_id.endswith("xxx"):
        raise RuntimeError("Razorpay keys not configured (set RAZORPAY_KEY_ID/SECRET)")

    own = client is None
    client = client or httpx.Client(timeout=30.0)
    try:
        r = client.get(
            f"{API_BASE}/payments/{payment_id}",
            auth=(key_id, key_secret),
        )
        r.raise_for_status()
        return r.json()
    finally:
        if own:
            client.close()


def already_succeeded(payment: dict[str, Any]) -> bool:
    status = str(payment.get("status", "")).lower()
    return status in {"captured", "authorized", "paid"}
