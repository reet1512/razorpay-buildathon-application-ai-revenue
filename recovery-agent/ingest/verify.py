"""
ingest/verify.py — Razorpay webhook signature check.

Header: X-Razorpay-Signature = HMAC-SHA256(raw_body, webhook_secret) hex digest.

Fail-closed contract:
    No usable secret => reject. There is exactly one bypass, and it must be
    switched on deliberately via ALLOW_UNSIGNED_WEBHOOKS=1. It can never be
    enabled in APP_ENV=production, and every use is logged.

Rationale: an earlier revision treated APP_ENV=dev (the shipped default) as
consent to skip verification, which meant a fresh clone accepted unsigned
webhooks. Defaults must be safe; convenience must be opt-in.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from typing import Optional

from logging_util import slog

_TRUTHY = {"1", "true", "yes", "on"}


def unsigned_webhooks_allowed() -> bool:
    """True only when an operator explicitly opted in outside production."""
    if os.getenv("APP_ENV", "dev").strip().lower() == "production":
        return False
    return os.getenv("ALLOW_UNSIGNED_WEBHOOKS", "").strip().lower() in _TRUTHY


def _secret_is_usable(secret: str) -> bool:
    """Placeholder secrets from .env.example are not real secrets."""
    return bool(secret) and not secret.endswith("xxx")


def verify_razorpay_signature(
    raw_body: bytes,
    signature: Optional[str],
    *,
    secret: Optional[str] = None,
    allow_unsigned: Optional[bool] = None,
) -> bool:
    """
    Verify the Razorpay webhook HMAC.

    allow_unsigned overrides the environment check (tests inject it directly).
    """
    secret = secret if secret is not None else os.getenv("RAZORPAY_WEBHOOK_SECRET", "")

    if not _secret_is_usable(secret):
        bypass = unsigned_webhooks_allowed() if allow_unsigned is None else allow_unsigned
        if bypass:
            slog(
                "webhook_signature_bypass",
                status="insecure",
                reason="no_usable_secret_and_bypass_enabled",
            )
            return True
        return False

    if not signature:
        return False

    digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, signature.strip())
