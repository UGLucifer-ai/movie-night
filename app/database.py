"""Database setup.

The app reads DATABASE_URL from the environment:
- In Docker Compose it points at Postgres.
- Locally (or on a tiny EC2 box) it falls back to a SQLite file.
SQLAlchemy hides the difference, so the rest of the code doesn't care.
"""

import os

from sqlalchemy import create_engine, inspect, text
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


# Columns added after the first release. create_all() only creates NEW tables,
# it never alters existing ones, so an existing database (e.g. the Postgres
# volume from docker compose) needs these added by hand. This is a tiny,
# idempotent stand-in for a migration tool like Alembic.
ADDED_COLUMNS = {
    "movies": {
        "poster_url": "VARCHAR(500)",
        "poster_checked": "BOOLEAN NOT NULL DEFAULT FALSE",
    },
}


def add_missing_columns(bind) -> list[str]:
    inspector = inspect(bind)
    added = []
    with bind.begin() as conn:
        for table, columns in ADDED_COLUMNS.items():
            if not inspector.has_table(table):
                continue
            existing = {c["name"] for c in inspector.get_columns(table)}
            for name, ddl in columns.items():
                if name not in existing:
                    # Names come from the constant above, never from user input.
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))  # noqa: S608
                    added.append(f"{table}.{name}")
    return added
