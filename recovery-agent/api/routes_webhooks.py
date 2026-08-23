"""
api/routes_webhooks.py — POST /webhooks/razorpay
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Header, HTTPException, Request

from ingest.normalise import (
    normalise_payment_link_paid,
    normalise_razorpay_webhook,
    razorpay_event_name,
)
from ingest.verify import verify_razorpay_signature
from ledger.db import SessionLocal
from ledger.service import handle_payment_link_paid, ingest_risk_event
from logging_util import slog

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/razorpay")
async def razorpay_webhook(
    request: Request,
    x_razorpay_signature: str | None = Header(default=None),
) -> dict:
    raw = await request.body()
    if not verify_razorpay_signature(raw, x_razorpay_signature):
        slog("webhook_reject", status="bad_signature")
        raise HTTPException(401, "invalid webhook signature")

    try:
        body = json.loads(raw.decode("utf-8") or "{}")
    except json.JSONDecodeError as exc:
        slog("webhook_reject", status="bad_json")
        raise HTTPException(400, "invalid JSON") from exc

    event_name = razorpay_event_name(body)
    session = SessionLocal()
    try:
        if event_name == "payment_link.paid":
            try:
                paid = normalise_payment_link_paid(body)
            except ValueError as exc:
                slog("webhook_reject", status="bad_payload")
                raise HTTPException(400, str(exc)) from exc

            result = handle_payment_link_paid(session, paid)
            session.commit()
            slog(
                "webhook_paid",
                case_id=result.case_id,
                event_id=result.event_id,
                status="duplicate" if result.duplicate else "recovered",
            )
            return {
                "ok": True,
                "event": event_name,
                "case_id": result.case_id,
                "event_id": result.event_id,
                "duplicate": result.duplicate,
                "recovered": result.recovered,
                "payment_link_id": result.payment_link_id,
                "payment_id": result.payment_id,
                "ledger_seq": result.ledger_seq,
                "webhook": body,
            }

        try:
            event = normalise_razorpay_webhook(body)
        except ValueError as exc:
            slog("webhook_reject", status="bad_payload")
            raise HTTPException(400, str(exc)) from exc

        result = ingest_risk_event(session, event)
        session.commit()
        slog(
            "webhook_ingest",
            case_id=result.case_id,
            event_id=result.event_id,
            status="duplicate" if result.duplicate else "ok",
        )
        return {
            "ok": True,
            "event": event_name or "payment.failed",
            "case_id": result.case_id,
            "event_id": result.event_id,
            "duplicate": result.duplicate,
            "ledger_seq": result.ledger_seq,
        }
    finally:
        session.close()
