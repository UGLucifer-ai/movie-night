"""Movie poster lookup.

Default source: Wikipedia (no API key). We ask the MediaWiki API for the lead
image of the film's article, trying the usual article names in order:

    "Casablanca (1942 film)" -> "Casablanca (film)" -> "Casablanca"

and only accept a page whose short description mentions "film" (and the year,
when we know it), so we don't show a poster of the city of Casablanca.

Optional sources, used first ONLY if their env var is set:
    TMDB_API_KEY  -> The Movie Database
    OMDB_API_KEY  -> OMDb

Caching (two layers):
1. In memory: a dict keyed by (title, year) so the same lookup never hits
   the network twice while the process runs (including misses).
2. In the database: Movie.poster_url + Movie.poster_checked, so after a
   restart we don't look up films we've already resolved.

The frontend always has a fallback: if poster_url is empty or the image fails
to load, it draws a generated gradient "poster card" with the title and year.
"""

import json
import logging
import os
import threading
import urllib.parse
import urllib.request

from sqlalchemy import select

from .models import Movie

log = logging.getLogger("movienight.posters")

USER_AGENT = (
    "MovieNight/0.2 (DevOps portfolio demo by Uday Charan Gopi; "
    "https://github.com/UGLucifer-ai/movie-night)"
)
TIMEOUT_SECONDS = 5
WIKI_API = "https://en.wikipedia.org/w/api.php"

_cache: dict[tuple[str, int | None], str | None] = {}
_cache_lock = threading.Lock()


def lookup_enabled() -> bool:
    """POSTER_LOOKUP=off disables all network lookups (used by the test suite)."""
    return os.getenv("POSTER_LOOKUP", "on").lower() not in ("off", "0", "false", "no")


def http_get_json(url: str, params: dict[str, str]) -> dict:
    """The ONLY function that touches the network. Tests replace it with a fake."""
    full_url = f"{url}?{urllib.parse.urlencode(params)}"
    if not full_url.startswith("https://"):
        raise ValueError("only https URLs are allowed")
    # https is checked above, so the S310 "file:// scheme" concern does not apply.
    request = urllib.request.Request(full_url, headers={"User-Agent": USER_AGENT})  # noqa: S310
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310
        return json.load(response)


# ---------- sources ----------


def wikipedia_candidates(title: str, year: int | None) -> list[str]:
    names = [f"{title} ({year} film)"] if year else []
    return [*names, f"{title} (film)", title]


def looks_like_the_film(description: str, year: int | None) -> bool:
    text = description.lower()
    return "film" in text and (year is None or str(year) in text)


def from_wikipedia(title: str, year: int | None) -> str | None:
    for candidate in wikipedia_candidates(title, year):
        data = http_get_json(
            WIKI_API,
            {
                "action": "query",
                "format": "json",
                "formatversion": "2",
                "prop": "pageimages|description",
                "piprop": "thumbnail",
                "pithumbsize": "400",
                "pilicense": "any",  # film posters are usually non-free (fair use)
                "redirects": "1",
                "titles": candidate,
            },
        )
        for page in data.get("query", {}).get("pages", []):
            thumb = page.get("thumbnail", {}).get("source")
            if thumb and looks_like_the_film(page.get("description", ""), year):
                return thumb
    return None


def from_tmdb(title: str, year: int | None, api_key: str) -> str | None:
    params = {"api_key": api_key, "query": title}
    if year:
        params["year"] = str(year)
    data = http_get_json("https://api.themoviedb.org/3/search/movie", params)
    for result in data.get("results", []):
        if result.get("poster_path"):
            return f"https://image.tmdb.org/t/p/w342{result['poster_path']}"
    return None


def from_omdb(title: str, year: int | None, api_key: str) -> str | None:
    params = {"apikey": api_key, "t": title, "type": "movie"}
    if year:
        params["y"] = str(year)
    data = http_get_json("https://www.omdbapi.com/", params)
    poster = data.get("Poster")
    return poster if poster and poster.startswith("https://") else None


def find_poster(title: str, year: int | None) -> tuple[str | None, bool]:
    """Return (poster_url or None, definitive).

    Never raises: a poster is nice-to-have. `definitive` is False when a
    source errored (timeout, network down), so callers can retry later
    instead of remembering "no poster" forever.
    """
    key = (title.strip().lower(), year)
    with _cache_lock:
        if key in _cache:
            return _cache[key], True

    sources = []
    if tmdb_key := os.getenv("TMDB_API_KEY"):
        sources.append(("tmdb", lambda: from_tmdb(title, year, tmdb_key)))
    if omdb_key := os.getenv("OMDB_API_KEY"):
        sources.append(("omdb", lambda: from_omdb(title, year, omdb_key)))
    sources.append(("wikipedia", lambda: from_wikipedia(title, year)))

    url, had_error = None, False
    for name, source in sources:
        try:
            url = source()
        except Exception as exc:  # noqa: BLE001 - network errors must not break the app
            log.warning("poster lookup via %s failed for %r: %s", name, title, exc)
            had_error = True
            continue
        if url:
            log.info("poster for %r (%s) found via %s", title, year, name)
            break

    definitive = url is not None or not had_error
    if definitive:  # only cache real answers, not "the network was down"
        with _cache_lock:
            _cache[key] = url
    return url, definitive


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


# ---------- filling the database ----------


def fill_posters(session_factory, movie_ids: list[int] | None = None) -> int:
    """Look up posters for movies not checked yet. Returns how many were found.

    Runs in a background thread/task, so it opens its own DB session.
    """
    if not lookup_enabled():
        return 0
    found = 0
    with session_factory() as db:
        query = select(Movie).where(Movie.poster_checked.is_(False))
        if movie_ids is not None:
            query = query.where(Movie.id.in_(movie_ids))
        for movie in db.scalars(query).all():
            url, definitive = find_poster(movie.title, movie.year)
            movie.poster_url = url
            # Remember real misses too (don't retry forever), but if the
            # lookup errored leave it unchecked so the next startup retries.
            movie.poster_checked = definitive
            found += url is not None
            db.commit()
    return found
