"""Reviews: only picked movies can be rated, 1-5 stars, one review per person."""


def make_pick(client) -> dict:
    res = client.post("/api/pick")
    assert res.status_code == 200
    return res.json()


def review(client, pick_id, reviewer="uday", rating=5, comment="Loved it"):
    return client.post(
        f"/api/picks/{pick_id}/reviews",
        json={"reviewer": reviewer, "rating": rating, "comment": comment},
    )


def test_review_a_picked_movie(client):
    pick = make_pick(client)
    res = review(client, pick["id"], rating=4, comment="  Great ending  ")
    assert res.status_code == 201
    body = res.json()
    assert body["rating"] == 4
    assert body["comment"] == "Great ending"  # whitespace trimmed
    assert body["reviewer"] == "uday"


def test_cannot_review_something_that_was_never_picked(client):
    # No picks exist yet, so any pick id is invalid.
    assert review(client, 1).status_code == 404
    assert client.get("/api/picks/1/reviews").status_code == 404


def test_rating_must_be_between_1_and_5(client):
    pick_id = make_pick(client)["id"]
    assert review(client, pick_id, rating=0).status_code == 422
    assert review(client, pick_id, rating=6).status_code == 422
    assert review(client, pick_id, rating=1).status_code == 201
    assert review(client, pick_id, reviewer="priya", rating=5).status_code == 201


def test_comment_length_is_limited_and_optional(client):
    pick_id = make_pick(client)["id"]
    assert review(client, pick_id, comment="x" * 501).status_code == 422
    res = client.post(f"/api/picks/{pick_id}/reviews", json={"reviewer": "a", "rating": 3})
    assert res.status_code == 201
    assert res.json()["comment"] == ""


def test_one_review_per_person_per_pick(client):
    pick_id = make_pick(client)["id"]
    assert review(client, pick_id, reviewer="uday").status_code == 201
    assert review(client, pick_id, reviewer=" UDAY ").status_code == 409


def test_same_person_can_review_different_picks(client):
    first = make_pick(client)["id"]
    second = make_pick(client)["id"]
    assert review(client, first).status_code == 201
    assert review(client, second).status_code == 201


def test_list_reviews_with_average(client):
    pick_id = make_pick(client)["id"]
    for name, stars in [("a", 5), ("b", 4), ("c", 4)]:
        review(client, pick_id, reviewer=name, rating=stars)
    body = client.get(f"/api/picks/{pick_id}/reviews").json()
    assert body["review_count"] == 3
    assert body["average_rating"] == 4.3  # 13 / 3 = 4.33 -> 4.3
    assert len(body["reviews"]) == 3
    assert body["pick"]["id"] == pick_id


def test_no_reviews_means_no_average(client):
    pick_id = make_pick(client)["id"]
    body = client.get(f"/api/picks/{pick_id}/reviews").json()
    assert body["average_rating"] is None
    assert body["review_count"] == 0
    assert body["reviews"] == []


def test_pick_history_shows_average_rating(client):
    pick_id = make_pick(client)["id"]
    review(client, pick_id, reviewer="a", rating=2)
    review(client, pick_id, reviewer="b", rating=3)
    history = client.get("/api/picks").json()
    assert history[0]["average_rating"] == 2.5
    assert history[0]["review_count"] == 2


def test_review_counter_metric_increases(client):
    def reviews_total() -> float:
        for line in client.get("/metrics").text.splitlines():
            if line.startswith("movienight_reviews_submitted_total "):
                return float(line.split()[1])
        raise AssertionError("metric missing")

    before = reviews_total()
    pick_id = make_pick(client)["id"]
    review(client, pick_id)
    review(client, pick_id)  # duplicate -> 409, must NOT be counted
    assert reviews_total() == before + 1


# ----- the themed rating scale (💩 .. 🎞️💥) -----


def test_rating_scale_endpoint(client):
    scale = client.get("/api/rating-scale").json()
    assert [s["value"] for s in scale] == [1, 2, 3, 4, 5]
    assert [s["label"] for s in scale] == ["Crap", "Boring", "Fine", "Great", "Blew up"]
    assert scale[0]["symbol"] == "💩"
    assert scale[4]["symbol"] == "🎞️💥"


def test_review_is_stored_as_integer_but_shown_with_symbol(client):
    pick_id = make_pick(client)["id"]
    body = review(client, pick_id, rating=1).json()
    assert body["rating"] == 1
    assert body["symbol"] == "💩"
    assert body["label"] == "Crap"


def test_average_uses_matching_symbol(client):
    pick_id = make_pick(client)["id"]
    for name, value in [("a", 5), ("b", 4), ("c", 4)]:  # average 4.3 -> rounds to 4
        review(client, pick_id, reviewer=name, rating=value)
    body = client.get(f"/api/picks/{pick_id}/reviews").json()
    assert (body["average_symbol"], body["average_label"]) == ("🎬", "Great")
    assert client.get("/api/picks").json()[0]["average_symbol"] == "🎬"
