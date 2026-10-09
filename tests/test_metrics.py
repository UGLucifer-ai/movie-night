"""Check that /metrics exposes what the Grafana dashboard relies on."""


def metric_value(text: str, name: str) -> float:
    for line in text.splitlines():
        if line.startswith(name + " "):
            return float(line.split()[1])
    raise AssertionError(f"{name} not found in /metrics output")


def test_metrics_endpoint_format(client):
    res = client.get("/metrics")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/plain")
    for name in (
        "movienight_http_requests_total",
        "movienight_http_request_duration_seconds",
        "movienight_votes_cast_total",
        "movienight_picks_made_total",
        "movienight_reviews_submitted_total",
        "movienight_movies_unwatched",
    ):
        assert name in res.text


def test_vote_and_pick_counters_increase(client):
    before = client.get("/metrics").text
    votes_before = metric_value(before, "movienight_votes_cast_total")
    picks_before = metric_value(before, "movienight_picks_made_total")

    movie_id = client.get("/api/movies").json()[0]["id"]
    client.post(f"/api/movies/{movie_id}/vote", json={"voter": "uday"})
    client.post("/api/pick")

    after = client.get("/metrics").text
    assert metric_value(after, "movienight_votes_cast_total") == votes_before + 1
    assert metric_value(after, "movienight_picks_made_total") == picks_before + 1
    assert metric_value(after, "movienight_movies_unwatched") == 19


def test_request_metrics_use_route_template_not_raw_ids(client):
    movie_id = client.get("/api/movies").json()[0]["id"]
    client.post(f"/api/movies/{movie_id}/vote", json={"voter": "uday"})
    text = client.get("/metrics").text
    assert 'path="/api/movies/{movie_id}/vote"' in text
    assert f'path="/api/movies/{movie_id}/vote"' not in text
