"""Shared test setup.

We point the app at an in-memory SQLite database BEFORE importing it, so tests
never touch a real database and every test starts from a clean, seeded state.
"""

import os

os.environ["DATABASE_URL"] = "sqlite://"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.seed import seed_movies  # noqa: E402


@pytest.fixture()
def client():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed_movies(db)
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def first_movie_id(client):
    return client.get("/api/movies").json()[0]["id"]
