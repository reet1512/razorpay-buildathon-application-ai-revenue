"""
memory/episode_text.py — deterministic semantic text for payment episodes.

Used for future Inherent embedding/retrieval. No secrets or raw PII.
"""

from __future__ import annotations

from ai.agent import amount_bucket_inr

from memory.schemas import DataSource, EpisodeOutcome, PaymentEpisode

_DATA_SOURCE_LABELS: dict[DataSource, str] = {
    DataSource.synthetic_simulation: "synthetic simulation",
    DataSource.razorpay_test: "Razorpay test mode",
    DataSource.demo: "demo",
}

_RAIL_LABELS: dict[str, str] = {
    "card": "card",
    "upi_autopay": "UPI autopay",
    "enach": "eNACH",
}

_ACTION_LABELS: dict[str, str] = {
    "schedule_retry": "delayed retry",
    "send_payment_link": "payment link",
    "request_mandate_update": "mandate update request",
    "escalate_human": "human escalation",
    "generic_nag": "generic contact",
}


def _format_inr(paise: int) -> str:
    inr = paise / 100.0
    if inr == int(inr):
        return f"₹{int(inr):,}"
    return f"₹{inr:,.2f}"


def _bucket_label(amount_paise: int) -> str:
    bucket = amount_bucket_inr(amount_paise)
    if bucket == "2000+":
        return "₹2,000+"
    low, high = bucket.split("-")
    return f"₹{int(low):,}–₹{int(high):,}"


def build_episode_text(episode: PaymentEpisode) -> str:
    """
    Turn a PaymentEpisode into human-readable semantic text for retrieval.

    Output is deterministic for a given episode (stable for tests).
    """
    rail = _RAIL_LABELS.get(episode.rail_value(), episode.rail_value())
    action = _ACTION_LABELS.get(episode.action_value(), episode.action_value())
    reason = episode.failure_reason_value().replace("_", " ")
    rc = episode.recovery_class_value().replace("_", " ")
    source = _DATA_SOURCE_LABELS.get(episode.data_source, episode.data_source.value)

    if episode.outcome == EpisodeOutcome.success:
        outcome_line = "Outcome: successful"
    elif episode.outcome == EpisodeOutcome.failed:
        outcome_line = "Outcome: not recovered"
    else:
        outcome_line = "Outcome: pending"

    lines = [
        "Payment recovery episode.",
        "",
        f"Payment method: {rail}",
        f"Failure reason: {reason}",
        f"Recovery class: {rc}",
        f"Amount: {_format_inr(episode.amount_paise)}",
        f"Attempt number: {episode.attempt_number}",
    ]

    if episode.seed is not None:
        lines.append(f"Seed: {episode.seed}")
    if episode.case_id:
        lines.append(f"Case: {episode.case_id}")

    if episode.customer_type:
        lines.append(f"Customer type: {episode.customer_type}")

    lines.append("")
    lines.append(f"Recovery action: {action}")

    if episode.delay_seconds is not None:
        if episode.delay_seconds >= 3600:
            mins = episode.delay_seconds // 60
            lines.append(f"Delay: {mins} minutes")
        elif episode.delay_seconds >= 60:
            lines.append(f"Delay: {episode.delay_seconds // 60} minutes")
        else:
            lines.append(f"Delay: {episode.delay_seconds} seconds")

    lines.extend(
        [
            "",
            outcome_line,
            f"Recovered amount: {_format_inr(episode.recovered_paise)}",
        ]
    )

    if episode.net_recovered_paise is not None:
        lines.append(f"Net recovered amount: {_format_inr(episode.net_recovered_paise)}")

    lines.append(f"Data source: {source}")

    if episode.prohibited:
        lines.append("Policy: prohibited recovery class")

    # Structured metadata block for hybrid/keyword retrieval of exact codes
    meta = episode.metadata_for_ingest()
    lines.append("")
    lines.append("--- metadata ---")
    for key in (
        "episode_id",
        "seed",
        "case_id",
        "simulation_version",
        "data_source",
        "recovery_class",
        "failure_reason",
        "payment_method",
        "action",
        "outcome",
        "attempt_number",
        "amount_bucket",
        "prohibited",
    ):
        if key == "payment_method":
            val = meta.get("rail")
        elif key in meta:
            val = meta[key]
        else:
            continue
        lines.append(f"{key}: {val}")

    return "\n".join(lines)
