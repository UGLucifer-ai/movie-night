"""Prometheus metrics.

Prometheus scrapes GET /metrics every few seconds and stores the numbers.
Grafana then draws graphs from Prometheus.

Metric types used:
- Counter: only goes up (requests, votes, picks, reviews). Use rate() to graph it.
- Histogram: buckets of durations, lets us compute p50/p95 latency.
- Gauge: can go up and down (number of movies waiting to be watched).
"""

import time

from prometheus_client import Counter, Gauge, Histogram
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

REQUEST_COUNT = Counter(
    "movienight_http_requests_total",
    "HTTP requests handled",
    ["method", "path", "status"],
)
REQUEST_LATENCY = Histogram(
    "movienight_http_request_duration_seconds",
    "Time spent handling an HTTP request",
    ["method", "path"],
)
VOTES_CAST = Counter("movienight_votes_cast_total", "Votes cast")
PICKS_MADE = Counter("movienight_picks_made_total", "Movies picked for movie night")
REVIEWS_SUBMITTED = Counter("movienight_reviews_submitted_total", "Reviews submitted")
MOVIES_UNWATCHED = Gauge("movienight_movies_unwatched", "Movies still waiting to be watched")


class MetricsMiddleware(BaseHTTPMiddleware):
    """Time every request and count it by method, route and status code."""

    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        elapsed = time.perf_counter() - start

        # Use the route *template* (/api/movies/{movie_id}/vote), not the real
        # URL (/api/movies/17/vote). Otherwise every movie id would create a
        # new time series and blow up Prometheus ("high cardinality").
        route = request.scope.get("route")
        path = getattr(route, "path", "unmatched")

        if path != "/metrics":  # don't measure the scraper itself
            REQUEST_COUNT.labels(request.method, path, str(response.status_code)).inc()
            REQUEST_LATENCY.labels(request.method, path).observe(elapsed)
        return response
