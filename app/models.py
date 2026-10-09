"""Database tables."""

from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class Movie(Base):
    __tablename__ = "movies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    added_by: Mapped[str] = mapped_column(String(50), default="seed")
    watched: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    votes: Mapped[list["Vote"]] = relationship(back_populates="movie", cascade="all, delete-orphan")


class Vote(Base):
    """One row per (movie, voter). The unique constraint stops double voting."""

    __tablename__ = "votes"
    __table_args__ = (UniqueConstraint("movie_id", "voter", name="uq_vote_movie_voter"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    movie_id: Mapped[int] = mapped_column(ForeignKey("movies.id", ondelete="CASCADE"))
    voter: Mapped[str] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    movie: Mapped[Movie] = relationship(back_populates="votes")


class Pick(Base):
    """History of what the app picked, so the group can see past movie nights."""

    __tablename__ = "picks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    movie_id: Mapped[int] = mapped_column(ForeignKey("movies.id", ondelete="CASCADE"))
    votes_at_pick: Mapped[int] = mapped_column(Integer)
    picked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    movie: Mapped[Movie] = relationship()
    reviews: Mapped[list["Review"]] = relationship(
        back_populates="pick", cascade="all, delete-orphan"
    )


class Review(Base):
    """A star rating + short review, attached to a *pick* (a movie night).

    Linking to the pick (not just the movie) is what guarantees you can only
    review something the group actually watched: no pick, no review.
    """

    __tablename__ = "reviews"
    __table_args__ = (
        UniqueConstraint("pick_id", "reviewer", name="uq_review_pick_reviewer"),
        CheckConstraint("rating BETWEEN 1 AND 5", name="ck_review_rating_1_5"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pick_id: Mapped[int] = mapped_column(ForeignKey("picks.id", ondelete="CASCADE"), index=True)
    reviewer: Mapped[str] = mapped_column(String(50))
    rating: Mapped[int] = mapped_column(Integer)
    comment: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    pick: Mapped[Pick] = relationship(back_populates="reviews")
