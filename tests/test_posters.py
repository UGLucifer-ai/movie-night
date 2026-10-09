"""Poster lookup tests. The network is ALWAYS mocked: we replace
app.posters.http_get_json with a fake that returns canned Wikipedia JSON."""

import pytest

from app import posters
from app.database import SessionLocal
from app.models import Movie

CASABLANCA_POSTER = "https://upload.wikimedia.org/casablanca.jpg"


def wiki_page(title, description, thumb=None):
    page = {"title": title, "description": description}
    if thumb:
        page["thumbnail"] = {"source": thumb}
    return {"query": {"pages": [page]}}


@pytest.fixture(autouse=True)
def clean_cache(monkeypatch):
    posters.clear_cache()
    monkeypatch.delenv("TMDB_API_KEY", raising=False)
    monkeypatch.delenv("OMDB_API_KEY", raising=False)
    yield
    posters.clear_cache()


@pytest.fixture()
def fake_wiki(monkeypatch):
    """Fake Wikipedia: answers by article title and records every call."""
    pages = {}
    calls = []

    def fake_get(url, params):
        calls.append(params.get("titles") or params)
        title = params.get("titles")
        return pages.get(title, {"query": {"pages": [{"title": title, "missing": True}]}})

    monkeypatch.setattr(posters, "http_get_json", fake_get)
    return pages, calls


def test_finds_poster_via_year_film_article(fake_wiki):
    pages, calls = fake_wiki
    pages["Casablanca (1942 film)"] = wiki_page(
        "Casablanca (film)", "1942 film by Michael Curtiz", CASABLANCA_POSTER
    )
    assert posters.find_poster("Casablanca", 1942) == (CASABLANCA_POSTER, True)
    assert calls == ["Casablanca (1942 film)"]


def test_falls_through_candidates_and_rejects_non_films(fake_wiki):
    pages, calls = fake_wiki
    # "(film)" article missing; plain title is the CITY -> must be rejected.
    pages["Casablanca"] = wiki_page("Casablanca", "City in Morocco", "https://x/city.jpg")
    assert posters.find_poster("Casablanca", 1942) == (None, True)
    assert calls == ["Casablanca (1942 film)", "Casablanca (film)", "Casablanca"]


def test_rejects_film_with_wrong_year(fake_wiki):
    pages, _ = fake_wiki
    pages["Psycho (film)"] = wiki_page("Psycho (1998 film)", "1998 film by Gus Van Sant", "x")
    assert posters.find_poster("Psycho", 1960) == (None, True)


def test_results_are_cached_in_memory(fake_wiki):
    pages, calls = fake_wiki
    pages["Jaws (1975 film)"] = wiki_page("Jaws", "1975 film by Steven Spielberg", "https://j")
    posters.find_poster("Jaws", 1975)
    posters.find_poster("  jaws ", 1975)  # same key after normalising
    assert len(calls) == 1


def test_network_error_is_swallowed_and_not_cached(monkeypatch):
    calls = []

    def broken(url, params):
        calls.append(1)
        raise TimeoutError("network down")

    monkeypatch.setattr(posters, "http_get_json", broken)
    assert posters.find_poster("Alien", 1979) == (None, False)  # not definitive
    posters.find_poster("Alien", 1979)
    assert len(calls) == 2  # retried, because errors aren't cached


def test_optional_tmdb_used_first_when_key_set(monkeypatch):
    monkeypatch.setenv("TMDB_API_KEY", "test-key")

    def fake_get(url, params):
        assert "themoviedb" in url
        assert params["api_key"] == "test-key"
        return {"results": [{"poster_path": "/abc.jpg"}]}

    monkeypatch.setattr(posters, "http_get_json", fake_get)
    url, _ = posters.find_poster("Alien", 1979)
    assert url == "https://image.tmdb.org/t/p/w342/abc.jpg"


def test_optional_omdb_rejects_non_https(monkeypatch):
    monkeypatch.setenv("OMDB_API_KEY", "k")
    monkeypatch.setattr(
        posters,
        "http_get_json",
        lambda url, params: {"Poster": "N/A"} if "omdb" in url else {"query": {"pages": []}},
    )
    assert posters.find_poster("Alien", 1979) == (None, True)


def test_http_get_json_refuses_non_https():
    with pytest.raises(ValueError):
        posters.http_get_json("file:///etc/passwd", {})


# ----- filling the database + API fallback -----


def test_fill_posters_saves_hits_and_misses(client, fake_wiki, monkeypatch):
    pages, _ = fake_wiki
    monkeypatch.setenv("POSTER_LOOKUP", "on")
    pages["Casablanca (1942 film)"] = wiki_page("Casablanca", "1942 film", CASABLANCA_POSTER)

    found = posters.fill_posters(SessionLocal)
    assert found == 1

    with SessionLocal() as db:
        movies = db.query(Movie).all()
        assert all(m.poster_checked for m in movies)  # misses remembered too
        assert {m.title for m in movies if m.poster_url} == {"Casablanca"}

    by_title = {m["title"]: m for m in client.get("/api/movies").json()}
    assert by_title["Casablanca"]["poster_url"] == CASABLANCA_POSTER
    assert by_title["Jaws"]["poster_url"] is None  # frontend draws its fallback card


def test_fill_posters_leaves_movie_unchecked_on_error(client, monkeypatch):
    monkeypatch.setenv("POSTER_LOOKUP", "on")

    def broken(url, params):
        raise OSError("offline")

    monkeypatch.setattr(posters, "http_get_json", broken)
    assert posters.fill_posters(SessionLocal) == 0
    with SessionLocal() as db:
        assert not any(m.poster_checked for m in db.query(Movie).all())


def test_lookup_disabled_does_nothing(client, monkeypatch):
    monkeypatch.setenv("POSTER_LOOKUP", "off")
    monkeypatch.setattr(posters, "http_get_json", lambda *a: pytest.fail("network used"))
    assert posters.fill_posters(SessionLocal) == 0


def test_adding_a_movie_looks_up_its_poster(client, fake_wiki, monkeypatch):
    pages, _ = fake_wiki
    monkeypatch.setenv("POSTER_LOOKUP", "on")
    pages["Spirited Away (2001 film)"] = wiki_page(
        "Spirited Away", "2001 film by Hayao Miyazaki", "https://sa.jpg"
    )
    created = client.post("/api/movies", json={"title": "Spirited Away", "year": 2001})
    assert created.status_code == 201
    # TestClient runs background tasks before returning, so it's already saved.
    by_title = {m["title"]: m for m in client.get("/api/movies").json()}
    assert by_title["Spirited Away"]["poster_url"] == "https://sa.jpg"


def test_movies_api_always_has_poster_field(client):
    for movie in client.get("/api/movies").json():
        assert "poster_url" in movie


def test_add_missing_columns_upgrades_old_table():
    """An 'old' movies table without poster columns gets them added."""
    from sqlalchemy import create_engine, inspect, text

    from app.database import add_missing_columns

    old = create_engine("sqlite://")
    with old.begin() as conn:
        conn.execute(text("CREATE TABLE movies (id INTEGER PRIMARY KEY, title VARCHAR(200))"))
    assert add_missing_columns(old) == ["movies.poster_url", "movies.poster_checked"]
    columns = {c["name"] for c in inspect(old).get_columns("movies")}
    assert {"poster_url", "poster_checked"} <= columns
    assert add_missing_columns(old) == []  # running again is a no-op
