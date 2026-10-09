"""Unit tests for the pure weighted-pick function. No web, no database."""

import random
from collections import Counter

from app.picker import weighted_pick


def test_empty_list_returns_none():
    assert weighted_pick([]) is None


def test_single_candidate_always_wins():
    assert weighted_pick([("Jaws", 5)]) == "Jaws"


def test_movies_without_votes_are_skipped_when_others_have_votes():
    rng = random.Random(42)
    picks = {weighted_pick([("Alien", 0), ("Jaws", 1)], rng) for _ in range(200)}
    assert picks == {"Jaws"}


def test_no_votes_at_all_falls_back_to_uniform_choice():
    rng = random.Random(1)
    picks = Counter(weighted_pick([("A", 0), ("B", 0), ("C", 0)], rng) for _ in range(3000))
    assert set(picks) == {"A", "B", "C"}
    for count in picks.values():  # each should be roughly 1/3 (1000)
        assert 850 < count < 1150


def test_more_votes_means_proportionally_more_likely():
    # 3 votes vs 1 vote -> expect about 75% / 25%.
    rng = random.Random(7)
    picks = Counter(weighted_pick([("Popular", 3), ("Niche", 1)], rng) for _ in range(10_000))
    share = picks["Popular"] / 10_000
    assert 0.72 < share < 0.78


def test_seeded_rng_is_repeatable():
    candidates = [("A", 1), ("B", 2), ("C", 3)]
    first = [weighted_pick(candidates, random.Random(99)) for _ in range(5)]
    second = [weighted_pick(candidates, random.Random(99)) for _ in range(5)]
    assert first == second
