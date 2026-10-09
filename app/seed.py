"""Sample data so the app isn't empty on first run."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Movie

CLASSIC_FILMS: list[tuple[str, int]] = [
    ("Casablanca", 1942),
    ("Citizen Kane", 1941),
    ("Rear Window", 1954),
    ("Seven Samurai", 1954),
    ("12 Angry Men", 1957),
    ("Vertigo", 1958),
    ("Some Like It Hot", 1959),
    ("Psycho", 1960),
    ("Lawrence of Arabia", 1962),
    ("Dr. Strangelove", 1964),
    ("2001: A Space Odyssey", 1968),
    ("The Godfather", 1972),
    ("Jaws", 1975),
    ("Star Wars", 1977),
    ("Alien", 1979),
    ("Back to the Future", 1985),
    ("The Princess Bride", 1987),
    ("Goodfellas", 1990),
    ("Jurassic Park", 1993),
    ("Pulp Fiction", 1994),
]


def seed_movies(db: Session) -> int:
    """Insert the classics only if the table is empty. Returns rows added."""
    existing = db.scalar(select(func.count()).select_from(Movie))
    if existing:
        return 0
    db.add_all(Movie(title=t, year=y, added_by="seed") for t, y in CLASSIC_FILMS)
    db.commit()
    return len(CLASSIC_FILMS)
