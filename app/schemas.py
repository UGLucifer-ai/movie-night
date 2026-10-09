"""Request/response shapes. Pydantic validates input before our code runs."""

from datetime import datetime

from pydantic import BaseModel, Field


class MovieCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    year: int | None = Field(default=None, ge=1888, le=2100)
    added_by: str = Field(default="anonymous", min_length=1, max_length=50)


class VoteIn(BaseModel):
    voter: str = Field(min_length=1, max_length=50)


class MovieOut(BaseModel):
    id: int
    title: str
    year: int | None
    added_by: str
    watched: bool
    votes: int


class PickOut(BaseModel):
    id: int
    movie: MovieOut
    votes_at_pick: int
    picked_at: datetime
    average_rating: float | None = None  # None until someone reviews it
    average_symbol: str | None = None  # e.g. "🎬" for an average of ~4
    average_label: str | None = None  # e.g. "Great"
    review_count: int = 0


class ReviewIn(BaseModel):
    reviewer: str = Field(min_length=1, max_length=50)
    rating: int = Field(ge=1, le=5)  # 1-5 stars, validated before our code runs
    comment: str = Field(default="", max_length=500)


class ReviewOut(BaseModel):
    id: int
    reviewer: str
    rating: int  # stored as 1-5
    symbol: str  # display only, from app/ratings.py
    label: str
    comment: str
    created_at: datetime


class RatingStep(BaseModel):
    value: int
    symbol: str
    label: str


class PickReviews(BaseModel):
    pick: PickOut
    average_rating: float | None
    average_symbol: str | None
    average_label: str | None
    review_count: int
    reviews: list[ReviewOut]
