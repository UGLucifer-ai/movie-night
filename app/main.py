"""Movie Night API.

Endpoints (see /docs for the auto-generated Swagger UI):
    GET    /health                         liveness + database check
    GET    /metrics                        Prometheus metrics
    GET    /api/movies                     list movies with vote counts
    POST   /api/movies                     suggest a movie
    POST   /api/movies/{movie_id}/vote     vote for a movie
    DELETE /api/movies/{movie_id}/vote/{voter}  take a vote back
    POST   /api/pick                       pick tonight's movie (weighted random)
    GET    /api/picks                      history of past picks (with average rating)
    POST   /api/picks/{pick_id}/reviews    rate (1-5) and review a picked movie
    GET    /api/picks/{pick_id}/reviews    list reviews + average rating for a pick
    GET    /api/rating-scale               the 1-5 symbols/labels (💩 .. 🎞️💥)
"""

import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Response, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from . import __version__
from .database import Base, SessionLocal, add_missing_columns, engine, get_db
from .metrics import (
    MOVIES_UNWATCHED,
    PICKS_MADE,
    REVIEWS_SUBMITTED,
    VOTES_CAST,
    MetricsMiddleware,
)
from .models import Movie, Pick, Review, Vote
from .picker import weighted_pick
from .posters import fill_posters
from .ratings import RATING_SCALE, describe
from .schemas import (
    MovieCreate,
    MovieOut,
    PickOut,
    PickReviews,
    RatingStep,
    ReviewIn,
    ReviewOut,
    VoteIn,
)
from .seed import seed_movies

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("movienight")

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Runs once at startup. create_all is fine for a small project;
    # a bigger one would use Alembic migrations instead.
    Base.metadata.create_all(engine)
    for column in add_missing_columns(engine):
        log.info("added missing column %s", column)
    with SessionLocal() as db:
        added = seed_movies(db)
    # Fetch posters in a background thread so startup (and /health) isn't
    # blocked by ~20 web requests. Movies show fallback cards until it's done.
    threading.Thread(target=fill_posters, args=(SessionLocal,), daemon=True).start()
    log.info("startup complete, seeded %d movies", added)
    yield


app = FastAPI(title="Movie Night", version=__version__, lifespan=lifespan)
app.add_middleware(MetricsMiddleware)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ---------- helpers ----------


def vote_counts_query():
    """SELECT movie, COUNT(votes) ... in ONE query (avoids the N+1 problem)."""
    return (
        select(Movie, func.count(Vote.id).label("votes"))
        .outerjoin(Vote, Vote.movie_id == Movie.id)
        .group_by(Movie.id)
    )


def to_out(movie: Movie, votes: int) -> MovieOut:
    return MovieOut(
        id=movie.id,
        title=movie.title,
        year=movie.year,
        added_by=movie.added_by,
        watched=movie.watched,
        votes=votes,
        poster_url=movie.poster_url,
    )


def rating_summary(pick: Pick) -> tuple[float | None, int]:
    """Average stars (rounded to 1 decimal) and number of reviews for a pick."""
    ratings = [r.rating for r in pick.reviews]
    if not ratings:
        return None, 0
    return round(sum(ratings) / len(ratings), 1), len(ratings)


def pick_to_out(pick: Pick) -> PickOut:
    average, count = rating_summary(pick)
    shown = describe(average) or {}
    return PickOut(
        id=pick.id,
        movie=to_out(pick.movie, pick.votes_at_pick),
        votes_at_pick=pick.votes_at_pick,
        picked_at=pick.picked_at,
        average_rating=average,
        average_symbol=shown.get("symbol"),
        average_label=shown.get("label"),
        review_count=count,
    )


def review_to_out(review: Review) -> ReviewOut:
    shown = RATING_SCALE[review.rating]
    return ReviewOut(
        id=review.id,
        reviewer=review.reviewer,
        rating=review.rating,
        symbol=shown["symbol"],
        label=shown["label"],
        comment=review.comment,
        created_at=review.created_at,
    )


def get_movie_or_404(db: Session, movie_id: int) -> Movie:
    movie = db.get(Movie, movie_id)
    if movie is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Movie not found")
    return movie


# ---------- ops endpoints ----------


@app.get("/health")
def health(db: Session = Depends(get_db)):
    """Used by Docker, load balancers and humans to check the app is alive."""
    try:
        db.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001 - any DB failure means "unhealthy"
        log.exception("health check: database unreachable")
        return JSONResponse({"status": "error", "database": "unreachable"}, status_code=503)
    return {"status": "ok", "database": "ok", "version": __version__}


@app.get("/metrics")
def metrics(db: Session = Depends(get_db)):
    unwatched = db.scalar(select(func.count()).select_from(Movie).where(Movie.watched.is_(False)))
    MOVIES_UNWATCHED.set(unwatched or 0)
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC_DIR / "index.html")


# ---------- movie endpoints ----------


@app.get("/api/movies", response_model=list[MovieOut])
def list_movies(include_watched: bool = False, db: Session = Depends(get_db)):
    query = vote_counts_query()
    if not include_watched:
        query = query.where(Movie.watched.is_(False))
    rows = db.execute(query.order_by(func.count(Vote.id).desc(), Movie.title)).all()
    return [to_out(movie, votes) for movie, votes in rows]


@app.post("/api/movies", response_model=MovieOut, status_code=status.HTTP_201_CREATED)
def add_movie(payload: MovieCreate, background: BackgroundTasks, db: Session = Depends(get_db)):
    title = payload.title.strip()
    exists = db.scalar(select(Movie).where(func.lower(Movie.title) == title.lower()))
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, f"'{exists.title}' is already on the list")
    movie = Movie(title=title, year=payload.year, added_by=payload.added_by.strip())
    db.add(movie)
    db.commit()
    log.info("movie added: %s by %s", movie.title, movie.added_by)
    # Look up the poster AFTER responding, so adding a movie stays instant.
    background.add_task(fill_posters, SessionLocal, [movie.id])
    return to_out(movie, 0)


@app.post("/api/movies/{movie_id}/vote", response_model=MovieOut, status_code=201)
def vote(movie_id: int, payload: VoteIn, db: Session = Depends(get_db)):
    movie = get_movie_or_404(db, movie_id)
    if movie.watched:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Already watched; suggest something new")
    db.add(Vote(movie_id=movie.id, voter=payload.voter.strip().lower()))
    try:
        db.commit()
    except IntegrityError:
        # The UNIQUE(movie_id, voter) constraint fired: this person already voted.
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "You already voted for this movie") from None
    VOTES_CAST.inc()
    votes = db.scalar(select(func.count()).select_from(Vote).where(Vote.movie_id == movie.id))
    return to_out(movie, votes)


@app.delete("/api/movies/{movie_id}/vote/{voter}", status_code=204)
def unvote(movie_id: int, voter: str, db: Session = Depends(get_db)):
    get_movie_or_404(db, movie_id)
    existing = db.scalar(
        select(Vote).where(Vote.movie_id == movie_id, Vote.voter == voter.strip().lower())
    )
    if existing is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No vote to remove")
    db.delete(existing)
    db.commit()
    return Response(status_code=204)


# ---------- the pick ----------


@app.post("/api/pick", response_model=PickOut)
def pick(db: Session = Depends(get_db)):
    """Pick tonight's movie. More votes = better odds, but never a sure thing."""
    rows = db.execute(vote_counts_query().where(Movie.watched.is_(False))).all()
    chosen = weighted_pick([((movie, votes), votes) for movie, votes in rows])
    if chosen is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No movies left to pick from")

    movie, votes = chosen
    movie.watched = True  # so it won't be picked again next time
    record = Pick(movie_id=movie.id, votes_at_pick=votes)
    db.add(record)
    db.commit()
    PICKS_MADE.inc()
    log.info("picked %s (%d votes)", movie.title, votes)
    return pick_to_out(record)


@app.get("/api/picks", response_model=list[PickOut])
def pick_history(db: Session = Depends(get_db)):
    # selectinload fetches all movies and reviews in 2 extra queries total,
    # instead of 2 extra queries *per pick* (the N+1 problem).
    query = (
        select(Pick)
        .options(selectinload(Pick.movie), selectinload(Pick.reviews))
        .order_by(Pick.picked_at.desc(), Pick.id.desc())
    )
    picks = db.scalars(query).all()
    return [pick_to_out(p) for p in picks]


# ---------- reviews (only for movies that were actually picked) ----------


def get_pick_or_404(db: Session, pick_id: int) -> Pick:
    pick = db.get(Pick, pick_id)
    if pick is None:
        # No pick = the group never watched it = nothing to review.
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Pick not found; only picked movies can be reviewed"
        )
    return pick


@app.post("/api/picks/{pick_id}/reviews", response_model=ReviewOut, status_code=201)
def add_review(pick_id: int, payload: ReviewIn, db: Session = Depends(get_db)):
    pick = get_pick_or_404(db, pick_id)
    review = Review(
        pick_id=pick.id,
        reviewer=payload.reviewer.strip().lower(),
        rating=payload.rating,
        comment=payload.comment.strip(),
    )
    db.add(review)
    try:
        db.commit()
    except IntegrityError:
        # UNIQUE(pick_id, reviewer): one review per person per movie night.
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "You already reviewed this pick") from None
    REVIEWS_SUBMITTED.inc()
    log.info("review: pick %d rated %d by %s", pick.id, review.rating, review.reviewer)
    return review_to_out(review)


@app.get("/api/picks/{pick_id}/reviews", response_model=PickReviews)
def list_reviews(pick_id: int, db: Session = Depends(get_db)):
    pick = get_pick_or_404(db, pick_id)
    summary = pick_to_out(pick)
    reviews = sorted(pick.reviews, key=lambda r: (r.created_at, r.id), reverse=True)
    return PickReviews(
        pick=summary,
        average_rating=summary.average_rating,
        average_symbol=summary.average_symbol,
        average_label=summary.average_label,
        review_count=summary.review_count,
        reviews=[review_to_out(r) for r in reviews],
    )


@app.get("/api/rating-scale", response_model=list[RatingStep])
def rating_scale():
    """The frontend reads the symbols from here, so they live in ONE place."""
    return [RatingStep(value=v, **step) for v, step in RATING_SCALE.items()]
