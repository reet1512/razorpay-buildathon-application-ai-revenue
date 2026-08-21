"""
ingest/verify.py — Razorpay webhook signature check.

Header: X-Razorpay-Signature = HMAC-SHA256(raw_body, webhook_secret) hex digest.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from typing import Optional


def verify_razorpay_signature(
    raw_body: bytes,
    signature: Optional[str],
    *,
    secret: Optional[str] = None,
    skip_in_dev: bool = True,
) -> bool:
    secret = secret or os.getenv("RAZORPAY_WEBHOOK_SECRET", "")
    if not secret or secret.endswith("xxx"):
        # Placeholder secrets: allow in APP_ENV=dev for local demos
        if skip_in_dev and os.getenv("APP_ENV", "dev") == "dev":
            return True
        return False
    if not signature:
        return False
    digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, signature.strip())
