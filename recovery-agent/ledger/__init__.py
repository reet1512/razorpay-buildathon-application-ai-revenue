"""
ledger package — Phase 1 data layer.

Remember the senior rule from BUILD_TECH:
  Pydantic  = shapes we pass through the pipeline (validation)
  SQLAlchemy = tables that survive restarts (persistence)

We keep BOTH. Do not pass raw dicts through the whole app.
"""
