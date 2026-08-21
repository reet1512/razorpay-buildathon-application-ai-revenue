"""
db.py — database engine and session factory.

Teaching:
- SQLAlchemy Engine = "how to talk to the DB file"
- Session = "one short conversation with the DB" (unit of work)
- For hackathon we use SQLite: zero ops, one file, good enough.

Later you can change DATABASE_URL to Postgres without rewriting models.
"""

from __future__ import annotations

import os
from collections.abc import Generator

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

# Load .env if present (safe no-op if missing).
load_dotenv()

# Default to a local sqlite file in the working directory.
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./recovery.db")

# SQLite needs check_same_thread=False when shared across FastAPI threads.
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    # echo=True  # uncomment while learning: prints every SQL statement
)

# sessionmaker is a factory: call SessionLocal() to get a new Session.
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    """
    All SQLAlchemy table models inherit from this.

    Why a shared Base?
    - metadata.create_all() can create every table in one call.
    """


def get_session() -> Generator[Session, None, None]:
    """
    FastAPI-style dependency (we will use it in later phases).

    Pattern:
      session = SessionLocal()
      try: ... use session ...
      finally: session.close()
    """
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def init_db() -> None:
    """
    Create tables if they do not exist.

    Hackathon shortcut: create_all is fine.
    Production would use Alembic migrations — not this week's problem.
    """
    # Import models so they register on Base.metadata before create_all.
    from ledger import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
