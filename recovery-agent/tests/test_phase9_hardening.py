"""
tests/test_phase9_hardening.py — secrets check + structured log fields.
"""

from __future__ import annotations

import json
import logging

from logging_util import configure_logging, slog
from scripts.check_no_secrets import main as secrets_main


def test_secrets_scan_clean():
    assert secrets_main() == 0


def test_slog_emits_json_without_raw_body(caplog):
    configure_logging(logging.INFO)
    with caplog.at_level(logging.INFO, logger="recovery_agent"):
        slog(
            "unit_test",
            case_id="case_x",
            event_id="evt_y",
            verb="send_payment_link",
            gate="contact_window",
            status="blocked",
            raw="SHOULD_NOT_APPEAR",
            phone="9999999999",
        )
    assert caplog.records
    payload = json.loads(caplog.records[-1].message)
    assert payload["event"] == "unit_test"
    assert payload["case_id"] == "case_x"
    assert payload["gate"] == "contact_window"
    assert "raw" not in payload
    assert "phone" not in payload
