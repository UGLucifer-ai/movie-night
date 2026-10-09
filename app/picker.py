"""The heart of the app: pick a movie, weighted by votes.

Kept as a pure function (no database, no web) so it is easy to test and
easy to explain:

    A movie with 3 votes is 3x as likely to be picked as a movie with 1 vote.

Rules:
1. Only movies with at least one vote are considered.
2. If nobody has voted yet, every candidate gets an equal chance.
3. If there are no candidates at all, return None.
"""

import random
from collections.abc import Sequence


def weighted_pick[T](
    candidates: Sequence[tuple[T, int]], rng: random.Random | None = None
) -> T | None:
    """Pick one item from (item, votes) pairs.

    `rng` can be passed in so tests can use a seeded Random and get
    repeatable results.
    """
    if not candidates:
        return None

    rng = rng or random.Random()

    voted = [(item, votes) for item, votes in candidates if votes > 0]
    if not voted:
        # Nobody voted: fall back to a fair, uniform choice.
        return rng.choice([item for item, _ in candidates])

    items = [item for item, _ in voted]
    weights = [votes for _, votes in voted]
    return rng.choices(items, weights=weights, k=1)[0]
