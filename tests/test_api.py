"""API tests: voting rules, picking, and error cases, through real HTTP calls."""

from app.seed import CLASSIC_FILMS


def vote(client, movie_id, voter):
    return client.post(f"/api/movies/{movie_id}/vote", json={"voter": voter})


# ----- health & seed -----


def test_health_reports_ok(client):
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"
    assert res.json()["database"] == "ok"


def test_seed_data_loaded(client):
    movies = client.get("/api/movies").json()
    assert len(movies) == len(CLASSIC_FILMS) == 20
    assert all(m["votes"] == 0 for m in movies)


def test_frontend_is_served(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "Movie Right!!" in res.text


# ----- adding movies -----


def test_add_movie(client):
    res = client.post("/api/movies", json={"title": "Spirited Away", "year": 2001})
    assert res.status_code == 201
    assert res.json()["title"] == "Spirited Away"
    titles = [m["title"] for m in client.get("/api/movies").json()]
    assert "Spirited Away" in titles


def test_duplicate_title_rejected_case_insensitive(client):
    res = client.post("/api/movies", json={"title": "  casablanca "})
    assert res.status_code == 409


def test_invalid_movie_rejected(client):
    assert client.post("/api/movies", json={"title": ""}).status_code == 422
    assert client.post("/api/movies", json={"title": "X", "year": 1500}).status_code == 422


# ----- voting -----


def test_vote_increments_count(client, first_movie_id):
    res = vote(client, first_movie_id, "uday")
    assert res.status_code == 201
    assert res.json()["votes"] == 1
    assert vote(client, first_movie_id, "priya").json()["votes"] == 2


def test_same_person_cannot_vote_twice(client, first_movie_id):
    assert vote(client, first_movie_id, "uday").status_code == 201
    assert vote(client, first_movie_id, "uday").status_code == 409
    # Names are normalised, so changing case doesn't get around it.
    assert vote(client, first_movie_id, "  UDAY ").status_code == 409


def test_one_person_can_vote_for_different_movies(client):
    movies = client.get("/api/movies").json()
    assert vote(client, movies[0]["id"], "uday").status_code == 201
    assert vote(client, movies[1]["id"], "uday").status_code == 201


def test_vote_for_missing_movie_returns_404(client):
    assert vote(client, 99999, "uday").status_code == 404


def test_vote_requires_voter_name(client, first_movie_id):
    res = client.post(f"/api/movies/{first_movie_id}/vote", json={"voter": ""})
    assert res.status_code == 422


def test_unvote(client, first_movie_id):
    vote(client, first_movie_id, "uday")
    assert client.delete(f"/api/movies/{first_movie_id}/vote/uday").status_code == 204
    assert client.delete(f"/api/movies/{first_movie_id}/vote/uday").status_code == 404


def test_movies_sorted_by_votes(client):
    movies = client.get("/api/movies").json()
    target = movies[-1]["id"]
    vote(client, target, "a")
    vote(client, target, "b")
    assert client.get("/api/movies").json()[0]["id"] == target


# ----- picking -----


def test_pick_only_chooses_voted_movie(client):
    movies = client.get("/api/movies").json()
    target = movies[5]
    vote(client, target["id"], "uday")
    res = client.post("/api/pick")
    assert res.status_code == 200
    assert res.json()["movie"]["id"] == target["id"]
    assert res.json()["votes_at_pick"] == 1


def test_picked_movie_is_marked_watched_and_hidden(client):
    picked = client.post("/api/pick").json()["movie"]
    remaining_ids = [m["id"] for m in client.get("/api/movies").json()]
    assert picked["id"] not in remaining_ids
    everything = client.get("/api/movies", params={"include_watched": True}).json()
    watched = [m for m in everything if m["id"] == picked["id"]]
    assert watched[0]["watched"] is True


def test_cannot_vote_for_watched_movie(client):
    picked = client.post("/api/pick").json()["movie"]
    assert vote(client, picked["id"], "uday").status_code == 400


def test_pick_history_newest_first(client):
    first = client.post("/api/pick").json()["movie"]["id"]
    second = client.post("/api/pick").json()["movie"]["id"]
    history = client.get("/api/picks").json()
    assert [h["movie"]["id"] for h in history] == [second, first]


def test_pick_returns_404_when_everything_watched(client):
    for _ in range(len(CLASSIC_FILMS)):
        assert client.post("/api/pick").status_code == 200
    assert client.post("/api/pick").status_code == 404
