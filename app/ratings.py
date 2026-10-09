"""The Movie Night rating scale.

Ratings are STORED as plain integers 1-5 (easy to average, validate and
query). The fun symbols are only how we DISPLAY them. Keeping the scale in
one place means the API and the frontend can never disagree.
"""

RATING_SCALE: dict[int, dict[str, str]] = {
    1: {"symbol": "💩", "label": "Crap"},
    2: {"symbol": "😴", "label": "Boring"},
    3: {"symbol": "🍿", "label": "Fine"},
    4: {"symbol": "🎬", "label": "Great"},
    5: {"symbol": "🎞️💥", "label": "Blew up"},
}


def describe(rating: float | None) -> dict[str, str] | None:
    """Symbol + label for a rating. Averages are rounded to the nearest step
    (4.3 -> 🎬 Great, 4.5 -> 🎞️💥 Blew up)."""
    if rating is None:
        return None
    step = min(5, max(1, int(rating + 0.5)))  # round half up, clamp to 1-5
    return RATING_SCALE[step]
