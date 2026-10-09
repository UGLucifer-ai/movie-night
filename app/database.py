"""Database setup.

The app reads DATABASE_URL from the environment:
- In Docker Compose it points at Postgres.
- Locally (or on a tiny EC2 box) it falls back to a SQLite file.
SQLAlchemy hides the difference, so the rest of the code doesn't care.
"""

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import StaticPool

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./movienight.db")


def make_engine(url: str):
    # SQLite needs this flag because FastAPI may use the connection from
    # a different thread than the one that created it.
    if url.startswith("sqlite"):
        kwargs = {"connect_args": {"check_same_thread": False}}
        if url in ("sqlite://", "sqlite:///:memory:"):
            # In-memory DB (used by tests): share ONE connection, otherwise
            # every new connection would see a brand-new empty database.
            kwargs["poolclass"] = StaticPool
        return create_engine(url, **kwargs)
    return create_engine(url, pool_pre_ping=True)


engine = make_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    """Parent class for all table models."""


def get_db():
    """FastAPI dependency: open a session per request and always close it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
