"""Unit tests for mapping numbers to the themed rating symbols."""

from app.ratings import RATING_SCALE, describe


def test_scale_has_five_steps():
    assert sorted(RATING_SCALE) == [1, 2, 3, 4, 5]


def test_describe_none_is_none():
    assert describe(None) is None


def test_describe_rounds_half_up_and_clamps():
    assert describe(1.0)["label"] == "Crap"
    assert describe(2.4)["label"] == "Boring"
    assert describe(2.5)["label"] == "Fine"
    assert describe(4.5)["label"] == "Blew up"
    assert describe(0.2)["label"] == "Crap"  # never below 1
    assert describe(9)["label"] == "Blew up"  # never above 5
