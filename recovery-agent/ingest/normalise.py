"""
ingest/normalise.py — Razorpay-ish webhook JSON -> RiskEvent.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ledger.schemas import EventSource, MandateState, PayerContext, Rail, RiskEvent


def _rail_from(method: str | None, entity: dict[str, Any]) -> Rail:
    m = (method or "").lower()
    if "upi" in m:
        return Rail.upi_autopay
    if "enach" in m or "nach" in m:
        return Rail.enach
    notes = entity.get("notes") or {}
    if str(notes.get("rail", "")).lower() == "upi_autopay":
        return Rail.upi_autopay
    return Rail.card


def normalise_razorpay_webhook(body: dict[str, Any]) -> RiskEvent:
    """
    Accept a payment.failed-shaped payload (or a thin demo wrapper).

    Supports:
      {"event":"payment.failed","payload":{"payment":{"entity":{...}}}}
      {"payment": {...}}  # already unwrapped entity
    """
    payload = body.get("payload") or body
    payment_wrap = payload.get("payment") or payload
    entity = payment_wrap.get("entity") if isinstance(payment_wrap, dict) else None
    if entity is None and isinstance(payment_wrap, dict):
        entity = payment_wrap

    if not isinstance(entity, dict):
        raise ValueError("webhook missing payment entity")

    if body.get("event_id"):
        event_id = str(body["event_id"])
    elif entity.get("id"):
        event_id = f"evt_fail_{entity['id']}"
    else:
        event_id = f"rzp_{entity.get('order_id', 'unknown')}"

    error = entity.get("error") or {}
    reason = (
        entity.get("error_reason")
        or error.get("reason")
        or entity.get("status_reason")
        or body.get("raw_error_reason")
        or "unknown"
    )
    code = (
        entity.get("error_code")
        or error.get("code")
        or body.get("raw_error_code")
        or ""
    )

    amount = int(entity.get("amount") or body.get("amount_paise") or 0)
    payer_ref = (
        entity.get("customer_id")
        or (entity.get("notes") or {}).get("payer_ref")
        or body.get("payer_ref")
        or "payer_unknown"
    )
    merchant_id = (
        body.get("merchant_id")
        or entity.get("merchant_id")
        or "merch_unknown"
    )

    created = entity.get("created_at")
    if isinstance(created, (int, float)):
        occurred = datetime.fromtimestamp(created, tz=timezone.utc)
    else:
        occurred = datetime.now(timezone.utc)

    mandate_state = None
    ms = (entity.get("notes") or {}).get("mandate_state") or body.get("mandate_state")
    if ms:
        try:
            mandate_state = MandateState(str(ms))
        except ValueError:
            mandate_state = MandateState.unknown

    credit = body.get("observed_credit_day")
    if credit is None:
        credit = (entity.get("notes") or {}).get("observed_credit_day")

    return RiskEvent(
        event_id=str(event_id),
        source=EventSource.razorpay_webhook,
        occurred_at=occurred,
        merchant_id=str(merchant_id),
        payer_ref=str(payer_ref),
        subscription_id=entity.get("subscription_id") or body.get("subscription_id"),
        mandate_id=entity.get("token_id") or body.get("mandate_id"),
        payment_ref=entity.get("id"),
        amount_paise=amount,
        currency=str(entity.get("currency") or "INR"),
        rail=_rail_from(entity.get("method"), entity),
        raw_error_code=str(code),
        raw_error_reason=str(reason),
        attempt_number=int(body.get("attempt_number") or 1),
        mandate_state=mandate_state,
        payer_context=PayerContext(
            observed_credit_day=credit,
            dnd_flag=bool(body.get("dnd_flag", False)),
        ),
    )
