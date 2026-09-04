"""
Shared pytest setup.

Most tests build their own in-memory engine, and API tests get the schema for
free because TestClient(app) runs the FastAPI lifespan, which calls init_db().
A few tests neither do that nor create their own engine — they just reach for
the shared SessionLocal (tests/test_fraud_gate_demo.py is the example). Those
only passed on machines where a recovery.db already existed from a previous run.

On a clean clone the tables did not exist yet and the suite failed with
"no such table: processed_events", depending on collection order. Creating the
schema once per session removes the hidden dependency on leftover local state.
"""

from __future__ import annotations

import pytest

from ledger.db import init_db


@pytest.fixture(scope="session", autouse=True)
def _create_schema() -> None:
    """Ensure the shared SQLite schema exists before any test runs."""
    init_db()
