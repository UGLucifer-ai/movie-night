# Movie Night — Walkthrough

This document explains **every file and every decision** in plain language,
so you can own this project and talk about it confidently in interviews.
Read it top to bottom once, then use it as a reference.

> Tip: for each section, open the file next to this doc and read along.

---

## 1. The big picture

Movie Night is a tiny app with a full DevOps setup around it:

1. **App** — FastAPI (Python) serves an API and a plain HTML/JS page.
2. **Database** — PostgreSQL in Docker Compose, SQLite when run alone.
3. **Container** — a multi-stage Dockerfile builds a small, non-root image.
4. **Monitoring** — the app exposes `/metrics`; Prometheus collects them;
   Grafana graphs them. All configured as files ("as code").
5. **CI** — GitHub Actions lints, tests, builds, smoke-tests, security-scans
   the image, and validates Terraform on every push.
6. **CD** — when CI passes on `main`, the image is pushed to GitHub Container
   Registry (GHCR).
7. **IaC** — Terraform describes a cheap AWS deployment (one EC2 instance).
   It is validated in CI but never applied automatically.

The user flow: suggest movies → vote → click **Pick** → the app chooses a
movie (more votes = better odds) → after watching, everyone rates it
💩 / 😴 / 🍿 / 🎬 / 🎞️💥 and writes a short review.

---

## 2. The application (`app/`)

### `app/__init__.py`
Marks `app` as a Python package and holds the version (`0.1.0`), which
`/health` reports. Handy to confirm which version is running after a deploy.

### `app/database.py`
- Reads `DATABASE_URL` from the environment. Default:
  `sqlite:///./movienight.db`. Compose sets it to Postgres.
- `make_engine()` creates the SQLAlchemy engine. SQLite needs
  `check_same_thread=False` (FastAPI may use the connection from another
  thread). An **in-memory** SQLite database (used by tests) uses `StaticPool`
  so every session shares one connection — otherwise each connection would see
  a different, empty database.
- `pool_pre_ping=True` for Postgres: checks a pooled connection is alive
  before using it (survives database restarts).
- `get_db()` is a **FastAPI dependency**: opens one session per request and
  always closes it (`try/finally`).

- `add_missing_columns()` — `create_all` only creates **new** tables; it never
  adds columns to tables that already exist. When the poster columns were
  added, existing databases (like the Postgres volume from docker compose)
  needed them too. This function checks the real columns with SQLAlchemy's
  `inspect()` and runs `ALTER TABLE ... ADD COLUMN` only for missing ones. It's
  **idempotent** (safe to run on every startup) and a mini version of what
  Alembic does properly.

**Why:** the same code runs against Postgres or SQLite. Config comes from the
environment — the [12-factor app](https://12factor.net/config) rule.

### `app/models.py` — the tables

| Table | Columns | Rules |
| --- | --- | --- |
| `movies` | id, title, year, added_by, watched, poster_url, poster_checked, created_at | title unique |
| `votes` | id, movie_id, voter, created_at | **UNIQUE(movie_id, voter)** — no double voting |
| `picks` | id, movie_id, votes_at_pick, picked_at | one row per movie night |
| `reviews` | id, pick_id, reviewer, rating, comment, created_at | **UNIQUE(pick_id, reviewer)**, **CHECK(rating BETWEEN 1 AND 5)** |

Key ideas:
- **Votes are rows, not a counter column.** We can see who voted, undo a
  vote, and the database itself blocks duplicates.
- **Reviews belong to a pick, not to a movie.** That is how "only movies that
  were actually picked can be reviewed" is enforced: no pick row, nothing to
  attach a review to. It also means if the same film were picked twice, each
  movie night gets its own reviews.
- **Rules live in the database too** (unique + check constraints), not only
  in Python. Even a buggy script talking straight to the DB can't break them.
- `votes_at_pick` stores the vote count at the moment of the pick, so history
  stays accurate later.

### `app/schemas.py` — request/response shapes
Pydantic models. FastAPI uses them to **validate input** before our code runs
(e.g. `rating` must be 1–5, `comment` ≤ 500 chars, `title` not empty) and
returns a `422` with details if invalid. They also shape the JSON output and
document the API at `/docs`.

### `app/picker.py` — the weighted pick
A **pure function**: no database, no web. Input is a list of
`(item, votes)` pairs.
1. Empty list → `None`.
2. Keep only movies with ≥ 1 vote; pick with `random.choices(..., weights=votes)`.
   3 votes = 3× the chance of 1 vote.
3. If nobody voted, pick uniformly at random.

The optional `rng` argument lets tests pass a **seeded** `random.Random`, so
results are repeatable. `random` (not `secrets`) is fine here: picking a film
isn't security-sensitive — Ruff's `S311` rule is ignored for this file with a
comment explaining why.

### `app/ratings.py` — the themed rating scale
Ratings are **stored as integers 1–5** and **displayed** as symbols:

| Value | Symbol | Label |
| --- | --- | --- |
| 1 | 💩 | Crap |
| 2 | 😴 | Boring |
| 3 | 🍿 | Fine |
| 4 | 🎬 | Great |
| 5 | 🎞️💥 | Blew up |

`describe(rating)` turns a number (including an average like 4.3) into a
symbol + label by rounding half up and clamping to 1–5 (4.3 → 🎬, 4.5 → 🎞️💥).

**Why integers?** Averages, sorting, validation and SQL all stay trivial.
The fun part is just presentation, kept in one place; the frontend reads it
from `GET /api/rating-scale`, so the API and UI can never disagree.

### `app/posters.py` — poster lookup and caching
**Source:** Wikipedia's public MediaWiki API (no key). We ask for the lead
image of the film's article (`prop=pageimages`, `pilicense=any` because most
posters are non-free "fair use" images, plus `prop=description`).

**Finding the right article.** Titles are ambiguous ("Casablanca" is a city,
"Psycho" has a 1998 remake), so we try, in order:
1. `"Casablanca (1942 film)"` 2. `"Casablanca (film)"` 3. `"Casablanca"`

and accept a page only if its short description contains "film" **and** the
year (e.g. "1942 film by Michael Curtiz"). `redirects=1` lets Wikipedia follow
renamed pages. Result for the 20 seed films: **20/20 posters found**.

**Optional sources.** If `TMDB_API_KEY` or `OMDB_API_KEY` is set, those are
tried first. Nothing is required for the demo.

**Caching — two layers:**
1. **In memory** (`_cache` dict keyed by normalised title + year, protected by
   a `threading.Lock` because lookups run in background threads). Repeat
   lookups never hit the network while the process runs.
2. **In the database**: `poster_url` (the URL or NULL) and `poster_checked`
   ("we already looked"). After a restart we skip films we've resolved.
   Misses are remembered too, so a film with no poster isn't looked up forever.

**Errors are not cached.** `find_poster()` returns `(url, definitive)`. If a
source timed out or the network was down, `definitive` is False: nothing is
cached and `poster_checked` stays False, so the next startup retries. A
poster is nice-to-have, so `find_poster` never raises.

**When lookups run (never on the request path):**
- At startup, a **daemon thread** backfills any unchecked movies (the 20 seeds
  on a fresh DB). Startup and `/health` aren't blocked — important on Render,
  which health-checks the app as soon as it boots.
- After `POST /api/movies`, FastAPI's **`BackgroundTasks`** looks up the new
  film after the response is sent, so adding a movie stays instant. The
  frontend re-fetches the list a few seconds later to show the poster.

**Safety:** all network access goes through one function, `http_get_json()`,
which only allows `https://` URLs, sends a descriptive `User-Agent`
(Wikipedia's API etiquette), and uses a 5 s timeout. Having one choke point
also makes it trivial to mock in tests. `POSTER_LOOKUP=off` disables lookups
entirely (the test suite sets it).

**Licensing note:** posters are © their studios; we hot-link Wikimedia's
copy for identification and say so in the README and page footer.

### `app/metrics.py` — Prometheus metrics
- `movienight_http_requests_total{method,path,status}` — **Counter**
- `movienight_http_request_duration_seconds{method,path}` — **Histogram**
- `movienight_votes_cast_total`, `movienight_picks_made_total`,
  `movienight_reviews_submitted_total` — **Counters** (business metrics)
- `movienight_movies_unwatched` — **Gauge** (goes up and down)

`MetricsMiddleware` wraps every request: starts a timer, lets the request
run, then records count + duration. It labels by the **route template**
(`/api/movies/{movie_id}/vote`) instead of the real URL
(`/api/movies/17/vote`) — otherwise every id would create a new time series
("high cardinality"), which is the #1 way to overload Prometheus. It skips
`/metrics` itself so scrapes don't pollute the numbers.

Counters are only incremented **after** a successful commit, so a rejected
duplicate vote or review isn't counted (there's a test for this).

### `app/seed.py`
20 classic films. `seed_movies()` only inserts them if the table is empty, so
restarting the app never duplicates them.

### `app/main.py` — the API
- `lifespan` runs at startup: `create_all` makes any missing tables, then
  seeds. (`create_all` only creates **new** tables; it does not change
  existing ones. That's why a real project adds **Alembic** migrations —
  see "What I'd do next".)
- Middleware + static files mounted; `/` returns `index.html`.
- `vote_counts_query()` gets movies **and** their vote counts in one SQL
  query using `OUTER JOIN` + `GROUP BY` — avoids the **N+1 query problem**
  (1 query for the list + 1 per movie).
- `/health` runs `SELECT 1`. If the DB is down it returns **503**, so Docker,
  a load balancer, or monitoring can tell "process alive" from "app working".
- `/metrics` refreshes the unwatched-movies gauge, then returns Prometheus
  text.
- Voting: insert a `Vote`; if the unique constraint fires we catch
  `IntegrityError`, roll back and return **409 Conflict**. Voter names are
  trimmed and lower-cased so "Uday" and " uday " are the same person.
- `POST /api/pick`: loads unwatched movies with counts, calls
  `weighted_pick`, marks the winner watched, writes a `Pick` row, increments
  the counter.
- `GET /api/picks`: history newest-first, each with `average_rating`,
  `average_symbol`, `average_label`, `review_count`. Uses `selectinload` so
  movies and reviews are fetched in 2 extra queries total instead of per pick.
- Reviews:
  - `POST /api/picks/{pick_id}/reviews` → 404 if the pick doesn't exist
    (never picked = can't review), 422 if rating isn't 1–5, 409 if this person
    already reviewed this pick, else 201 + the review with its symbol/label.
  - `GET /api/picks/{pick_id}/reviews` → reviews newest-first, plus the
    average and its matching symbol.
  - `GET /api/rating-scale` → the 5 symbols/labels for the frontend.

**HTTP status codes used:** 200 OK, 201 Created, 204 No Content, 400 Bad
Request (voting for a watched movie), 404 Not Found, 409 Conflict, 422
validation error, 503 unhealthy.

### `app/static/` — the frontend
Plain HTML/CSS/JS, no framework, no build step, no external fonts or libraries.

- `index.html` — decorative background layers (marked `aria-hidden`), the
  marquee header, your name + the **Roll the reel** button, suggest form, the
  **lineup** poster grid, past picks strip, rate & review, and the hidden
  **reveal** dialog (curtains + spotlight).
- `app.js`:
  - `fetch()` calls the API and redraws lists. User text is always inserted
    with **`textContent`, never `innerHTML`**, so a movie titled `<script>…`
    can't run code (**XSS** protection). Your name is kept in `localStorage`.
  - **Posters:** `posterFor(movie)` returns an `<img>` with
    `loading="lazy"` (only downloaded when near the screen), `decoding="async"`
    and descriptive **alt text**. If `poster_url` is empty, or the image
    fires `error`, it's replaced by `fallbackPoster(movie)`: a gradient card
    with the title and year. The gradient colour comes from a hash of the
    title, so the same film always gets the same colours.
  - `refreshWhilePostersLoad()` re-fetches the list a few times while posters
    are still being looked up in the background.
  - `paintMosaic()` fills the blurred background mosaic with the posters.
  - **Pick reveal:** call the API first (so the result is real), then open
    the overlay with the curtains closed, flicker through posters behind them
    with a slowing "drumroll", then add `.open` — CSS slides the curtains
    apart, fades in the spotlight and pops the winner in. Close with the
    button, Escape, or clicking outside; focus returns to where you were.
    With reduced motion, the shuffle is skipped and the winner shows at once.
  - The rating picker is built from `/api/rating-scale`: real radio buttons
    (keyboard and screen-reader friendly) visually hidden, with a big symbol
    as each label. Hovering shows the label ("🍿 3 – Fine"); selecting keeps it.
- `style.css` — the theater look:
  - **Backdrop layers** (fixed, behind everything): blurred poster mosaic
    drifting slowly, an "aurora" of radial gradients moving over 28 s, two
    spotlight beams (`clip-path` triangles) sweeping, dust particles (one
    element with several tiny radial gradients, scrolling), film grain (an
    inline SVG `feTurbulence` noise texture jittered with `steps()`), and a
    vignette.
  - **Marquee:** neon text via stacked `text-shadow`s with an occasional
    flicker; chasing bulbs are a dotted border made of repeating radial
    gradients whose position steps back and forth.
  - **Poster grid:** CSS Grid `repeat(auto-fill, minmax(160px, 1fr))`; cards
    lift, scale and glow on hover with a glossy shine sweep, and fade in with
    a staggered delay (`--i` set per card).
  - **Performance:** only `transform`, `opacity` and `filter` animate — the
    browser can do these on the GPU without re-laying-out the page.
  - **Mobile** (`max-width: 640px`): single-column controls, a 2-column poster
    grid, full-width buttons, no hover-lift on touch, horizontally scrolling
    past picks with scroll-snap.
  - **Reduced motion:** a `prefers-reduced-motion: reduce` block stops every
    background animation, the marquee flicker, card entrances, the curtains
    and the rating animations. The reveal still appears, just instantly.

#### Rating animations (pure CSS)
No animation library — just CSS `@keyframes`. Each symbol animates on
**hover**, and replays once on **select** (JS adds a `.play` class, forces a
reflow so the animation restarts, then removes it after ~1.2 s):

| Symbol | Animation | How |
| --- | --- | --- |
| 💩 1 | wobbles with stink lines | `rotate` back and forth; `::after` shows "〰〰" drifting up and fading |
| 😴 2 | slow bob with floating z's | gentle `translateY`; `::after` "z z" floats up-right and fades |
| 🍿 3 | pops like popcorn | jump + squash/stretch with a bouncy `cubic-bezier` |
| 🎬 4 | clapperboard snaps shut | tilts open from the bottom-left corner, then snaps back |
| 🎞️💥 5 | reel spins then bursts | 360° spin + scale-up, then a ring (`::after`) expands and fades |

**Accessibility:** a `@media (prefers-reduced-motion: reduce)` block turns
**all** these animations off for people who ask their operating system for
less motion (motion can cause discomfort for some users). Only `transform`
and `opacity` are animated — they're cheap for the browser (GPU-friendly, no
layout recalculation).

---

## 3. Tests (`tests/`)

Run with `pytest -v`. 55+ tests, about a second.

- `conftest.py` sets `DATABASE_URL=sqlite://` (in-memory) and
  `POSTER_LOOKUP=off` **before** importing the app, then for each test drops/creates tables and re-seeds. Every test
  starts clean and nothing touches a real database.
- `test_picker.py` — unit tests of the pure pick function: empty list, single
  item, zero-vote movies skipped, uniform fallback, **3:1 votes ≈ 75%/25%**
  over 10,000 seeded picks, repeatability with a seed.
- `test_api.py` — through real HTTP calls (`TestClient`): health, seed data,
  add movie, duplicate title (case-insensitive) → 409, validation → 422,
  voting increments, **no double voting** (even with different case/spaces),
  unvote, sort by votes, pick only chooses voted movies, picked movie marked
  watched and hidden, can't vote for watched, history order, 404 when
  everything is watched.
- `test_reviews.py` — review a picked movie, **can't review something never
  picked (404)**, rating must be 1–5, comment optional and ≤ 500 chars, one
  review per person per pick, average (4, 4, 5 → 4.3) and its symbol (🎬),
  history shows averages, rating stored as integer but returned with symbol,
  and the review counter only counts successful reviews.
- `test_ratings.py` — the symbol mapping: rounding half up, clamping.
- `test_posters.py` — **the network is always mocked** with pytest's
  `monkeypatch`, which swaps `http_get_json` for a fake that returns canned
  Wikipedia JSON. It covers: finding the poster via the "(1942 film)" article;
  falling through the candidates and **rejecting the city** of Casablanca;
  rejecting a film with the wrong year; the in-memory cache (one network call
  for two lookups); network errors swallowed and **not cached**; optional
  TMDB used first when its key is set; OMDb's "N/A" ignored; non-https URLs
  refused; `fill_posters` saving hits **and** misses, leaving movies unchecked
  after an error, doing nothing when disabled; adding a movie looks up its
  poster in the background; the API returns `poster_url: null` for the
  fallback; and `add_missing_columns` upgrading an old table (idempotently).
- `test_metrics.py` — `/metrics` contains every metric the dashboard uses;
  counters go up after a vote and pick; labels use route templates.

**Why test like this?** The pure function gets fast, precise unit tests; the
rules that matter to users (voting, picking, reviewing) get tested through the
API exactly as a browser would use them.

---

## 4. Container (`Dockerfile`, `.dockerignore`)

**Multi-stage build:**
1. `builder` stage: create a virtualenv and `pip install` requirements.
   `requirements.txt` is copied **before** the code, so Docker caches this
   layer — changing code doesn't reinstall everything.
2. `runtime` stage: fresh `python:3.12-slim`, copy only the virtualenv and
   the `app/` folder. Build leftovers stay behind → smaller image, smaller
   attack surface.

**Security:** runs as user `app` with a **fixed UID 10001**, not root. If
someone exploited the app, they wouldn't be root inside the container. The
fixed UID lets the EC2 host give that user ownership of the data folder.

**`HEALTHCHECK`** calls `/health` every 15 s using Python's `urllib` (no need
to install curl). `docker ps` then shows `healthy`/`unhealthy`.

`DATABASE_URL` defaults to SQLite at `/data/movienight.db`, so the image runs
on its own (as on EC2) and Compose overrides it for Postgres.

`.dockerignore` keeps `.git`, tests, docs, infra, venvs etc. out of the build
context — faster builds and no accidental secrets in the image.

---

## 5. Local stack (`docker-compose.yml`)

Four services on one Docker network (they reach each other by service name):
- **app** — built from the Dockerfile, port 8000. `depends_on: db:
  condition: service_healthy` waits for Postgres to be **ready**, not just
  started.
- **db** — `postgres:16-alpine`, data in the `pgdata` volume (survives
  restarts), `pg_isready` health check.
- **prometheus** — reads `monitoring/prometheus/prometheus.yml`, port 9090.
- **grafana** — mounts the provisioning folder and dashboards, port 3000.

Passwords use `${VAR:-default}` so they're simple locally and can be changed
via a `.env` file (see `.env.example`). Image versions are pinned
(`prom/prometheus:v2.54.1`, `grafana/grafana:11.2.0`) so the stack doesn't
change under you.

---

## 6. Monitoring (`monitoring/`)

- `prometheus/prometheus.yml` — scrape `app:8000/metrics` every 15 s (plus
  Prometheus itself). **Pull model:** Prometheus fetches metrics; the app just
  exposes them.
- `grafana/provisioning/datasources/prometheus.yml` — adds Prometheus as a
  data source with a fixed `uid` so the dashboard can reference it.
- `grafana/provisioning/dashboards/dashboards.yml` — load every JSON file in
  the dashboards folder at startup.
- `grafana/dashboards/movie-night.json` — the dashboard:
  - Stats: votes cast, movies picked, **reviews submitted**, movies left, app up
  - Requests/sec by route: `sum by (path) (rate(movienight_http_requests_total[1m]))`
  - Latency p50/p95: `histogram_quantile(0.95, sum by (le) (rate(..._bucket[5m])))`
  - Votes, picks and reviews per 5 min: `increase(...[5m])`
  - Error rate: 4xx and 5xx per second

**Why provision as code?** Anyone running `docker compose up` gets the same
dashboard with zero clicking, and changes are reviewed in Git like code.

**PromQL basics:** counters always go up, so you graph `rate()` (per second)
or `increase()` (per window). Histograms store bucket counts, and
`histogram_quantile` estimates percentiles from them.

---

## 7. CI/CD (`.github/workflows/`)

### `ci.yml` — on every push and pull request
Three jobs:
1. **lint-and-test** — set up Python 3.12 (with pip cache), install
   `requirements-dev.txt`, `ruff check`, `ruff format --check`, `pytest -v`.
2. **docker-build-and-scan** (runs after tests pass) — build the image with
   Buildx (GitHub Actions layer cache), **smoke test** it (run the container,
   curl `/health` and `/metrics`), then **Trivy**:
   - a report of HIGH + CRITICAL (doesn't fail),
   - a gate that fails on **fixable CRITICAL** vulnerabilities.
   `ignore-unfixed` avoids failing on issues nobody can fix yet.
3. **terraform** — `fmt -check`, `init -backend=false`, `validate`. No AWS
   credentials and nothing is created.

`permissions: contents: read` — least privilege for the token.

**Supply-chain note (good interview story):** In March 2026 the Trivy GitHub
Action had its version tags hijacked to ship credential-stealing code. This
repo pins `aquasecurity/trivy-action` to a **full commit SHA** (v0.35.0) and
Trivy to **v0.69.3**, the versions Aqua confirmed safe. Tags can be moved;
commit SHAs can't. A next step is pinning *all* actions by SHA and letting
Dependabot update them.

### `cd.yml` — publish the image
- Triggered by `workflow_run` when **CI completes on `main`**, and runs only
  if CI **succeeded** (or someone triggers it manually).
- Checks out the **exact commit CI tested** (`workflow_run.head_sha`).
- Logs in to `ghcr.io` with the built-in `GITHUB_TOKEN` (`packages: write`
  permission) — **no secrets to set up**.
- `docker/metadata-action` creates tags `latest` and `sha-<short>`. The SHA
  tag is immutable and traceable to a commit; `latest` is just convenient.

---

## 8. Infrastructure as Code (`infra/`)

Terraform describing the cheapest sensible AWS deployment. **Never applied
by CI** — only `fmt` and `validate`.

- `versions.tf` — Terraform ≥ 1.6, AWS provider `~> 5.0`, `default_tags` so
  every resource is tagged Project/Owner/ManagedBy. Local state (fine for a
  demo; teams use an S3 backend with locking).
- `variables.tf` — region, owner, instance type (`t3.micro`), **container
  image** (required, validated by regex), **allowed CIDR** (validated; set it
  to your IP `/32`), disk size.
- `main.tf`:
  - Uses the **default VPC** and its subnets (no networking to build or pay for).
  - Finds the latest **Amazon Linux 2023** AMI from AWS's public SSM parameter
    (no hard-coded AMI IDs that go stale).
  - **Security group**: only port 80 in, from `allowed_cidr`. **No SSH port.**
  - **IAM role + instance profile** with `AmazonSSMManagedInstanceCore`, so you
    can get a shell via **SSM Session Manager** instead of SSH keys.
  - **EC2 instance**: **IMDSv2 required** (blocks a classic SSRF credential-theft
    trick), **encrypted gp3** root disk, `user_data` from the template.
- `user_data.sh.tftpl` — first boot: install Docker, create
  `/opt/movie-night/data` owned by UID 10001, pull the image, run it with
  `--restart unless-stopped`, mapping port 80 → 8000 and mounting the data
  folder (the app uses SQLite there).
- `outputs.tf` — instance id, public IP, app URL, health URL.
- `terraform.tfvars.example` — copy to `terraform.tfvars` (git-ignored).
- `.terraform.lock.hcl` — committed; pins exact provider versions/hashes so
  everyone gets the same provider.

**Why EC2 and not ECS Fargate/EKS?** Cost and clarity. Fargate needs a load
balancer or public task IPs plus more IAM; EKS has a control-plane fee. One
EC2 instance is cheap and easy to reason about. Fargate behind an ALB with
RDS is the "production" upgrade path.

**Cost:** roughly $7–8/month for `t3.micro` on-demand (Free Tier eligible on
many accounts) + ~$2.40 for 30 GB gp3 + ~$3.60 for the public IPv4. No load
balancer, NAT gateway or RDS (they bill hourly). Always `terraform destroy`
after demos.

---

## 9. Other files

- `requirements.txt` — runtime dependencies, pinned to exact versions so
  builds are reproducible. `requirements-dev.txt` adds pytest, httpx, ruff.
- `pyproject.toml` — project metadata + Ruff (lint rules `E,F,I,B,UP,S`,
  100-char lines) + pytest settings. `S` = Bandit-style security checks.
- `.gitignore` — venvs, caches, `*.db`, Terraform state (`*.tfstate` can hold
  secrets) and `*.tfvars`.
- `.env.example` — shows which env vars you can override.
- `LICENSE` — MIT, © Uday Charan Gopi.
- `docs/screenshots/README.md` — what screenshots to add.

---

## 10. Design decisions (and trade-offs)

| Decision | Why | Trade-off |
| --- | --- | --- |
| FastAPI | Typed, fast, auto docs at `/docs` | Less "batteries included" than Django |
| SQLAlchemy + `DATABASE_URL` | Postgres and SQLite with one codebase | Slightly more setup than raw SQL |
| Pure `weighted_pick` function | Easy to test and explain | — |
| Votes/reviews as rows + DB constraints | Integrity enforced at the source | More rows than a counter |
| Reviews tied to picks | "Only picked movies" enforced by the model | Need a pick id to review |
| Ratings as ints, symbols in one mapping | Simple math; UI reads `/api/rating-scale` | — |
| `create_all` (no Alembic) | Simple for a portfolio project | Only `add_missing_columns` for new columns; no renames/data migrations |
| Wikipedia posters, cached, background | Free, keyless, never blocks requests | Hot-linked images; a few films may not resolve (fallback card) |
| Pure CSS/vanilla JS UI | Fast, no build step, easy to explain | More hand-written CSS |
| Route-template metric labels | Avoid cardinality explosion | Lose per-id detail (use logs for that) |
| Non-root, multi-stage image | Smaller, safer | Slightly longer Dockerfile |
| CD gated on CI via `workflow_run` | Never publish untested code | Two workflows to understand |
| Single EC2 with SQLite | Cheapest, simplest | No HA; data lives on one disk |

### What I'd do next
1. Alembic migrations (replacing `add_missing_columns`).
2. Pin all GitHub Actions to SHAs + Dependabot.
3. Alert rules (e.g. 5xx rate > 1% for 5 min) and Alertmanager.
4. A deploy step that updates EC2 (or move to ECS Fargate + RDS) on new images.
5. Structured JSON logs and request IDs.
6. Remote Terraform state in S3 with locking.

---

## 11. Ten likely interview questions (with good answers)

**1. Walk me through what happens when you push to `main`.**
CI runs three jobs: Ruff lint + format check and pytest; then a Docker build,
a smoke test that runs the container and curls `/health` and `/metrics`, and a
Trivy scan that fails on fixable critical vulnerabilities; and Terraform
`fmt`/`validate`. If CI succeeds, the CD workflow (triggered by
`workflow_run`) checks out that exact commit, logs in to GHCR with the
built-in `GITHUB_TOKEN`, and pushes the image tagged `latest` and
`sha-<commit>`.

**2. Why a multi-stage Dockerfile, and why non-root?**
The builder stage installs dependencies; the runtime stage copies only the
virtualenv and app code, so the final image is smaller and has fewer packages
to exploit. Running as a non-root user (UID 10001) limits damage if the app
is compromised. I also added a `HEALTHCHECK` and ordered layers so
dependency installs are cached.

**3. How does the weighted pick work, and how did you test randomness?**
Only movies with at least one vote are candidates; `random.choices` uses the
vote counts as weights, so 3 votes is 3× as likely as 1. If nobody voted it
falls back to a uniform pick. It's a pure function that accepts an RNG, so
tests pass a seeded `Random`: I check edge cases exactly, and run 10,000
picks to confirm a 3:1 split lands around 75%/25%.

**4. How do you stop someone voting twice or reviewing a movie that wasn't picked?**
Both are enforced in the database. `votes` has a unique constraint on
(movie_id, voter); `reviews` has one on (pick_id, reviewer) and a check
constraint that rating is 1–5. The API catches the `IntegrityError` and
returns 409. Reviews link to a **pick** row, so if the movie was never picked
there's nothing to attach to and the API returns 404. Pydantic also validates
input first, returning 422 for a rating like 6.

**5. What metrics do you expose and why those?**
The "RED" metrics — request **R**ate, **E**rrors (status label) and
**D**uration (histogram) — plus business metrics: votes cast, picks made,
reviews submitted, and a gauge of unwatched movies. RED tells me if the
service is healthy; business metrics tell me if it's being used.

**6. What is label cardinality, and how did you handle it?**
Each unique combination of label values is a separate time series. If I
labelled requests with the raw URL, every movie id would create new series
and Prometheus memory would grow without bound. The middleware uses the route
template (`/api/movies/{movie_id}/vote`), and I have a test that checks the
raw id never appears in a label.

**7. How does Grafana get its dashboard — did you click it together?**
No — it's provisioned as code. A datasource YAML points at Prometheus with a
fixed UID, a dashboard-provider YAML tells Grafana to load JSON from a folder,
and the dashboard JSON is in Git. `docker compose up` gives everyone the same
dashboard, and changes go through code review.

**8. Why EC2 instead of ECS/EKS, and what does your Terraform do for security?**
For a demo, one `t3.micro` is cheapest and easiest to explain; Fargate would
need a load balancer and more IAM, and EKS has a control-plane fee. Security:
the security group only opens port 80 to a CIDR I choose, there's no SSH —
access is through SSM Session Manager via an IAM instance profile — IMDSv2 is
required, and the disk is encrypted. CI validates the Terraform but never
applies it; I'd apply manually and `destroy` afterwards to control cost.

**9. Your CI uses Trivy — what happened with Trivy in 2026 and what did you do about it?**
In March 2026 attackers force-pushed the `trivy-action` version tags to
malicious commits that stole CI secrets. Tags are mutable, so anyone using
`@0.x` got the malware. I pin the action to the full commit SHA of the
confirmed-safe v0.35.0 and Trivy itself to v0.69.3. More generally: pin
third-party actions by SHA, give workflows least-privilege permissions
(`contents: read`), and avoid long-lived secrets — CD uses the short-lived
`GITHUB_TOKEN`.

**10. What would you change to make this production-ready?**
Alembic migrations instead of `create_all`; Postgres on RDS and the app on
ECS Fargate behind an ALB across two AZs; remote Terraform state in S3 with
locking; alert rules (e.g. 5xx rate, p95 latency, target down) routed through
Alertmanager; automated deploys of the new image with a rollback path;
structured logs with request IDs; and Dependabot for dependency and action
updates.

**Bonus — "How do posters work without slowing the app down?"**
Wikipedia's API, no key. Lookups never run on the request path: a background
thread backfills at startup and FastAPI `BackgroundTasks` handles new films
after the response. Results are cached in memory and in the DB (including
"no poster" answers), but errors aren't cached so they get retried. All
network access goes through one https-only function with a timeout, which
also makes it easy to mock in tests. The frontend lazy-loads images and falls
back to a generated poster card if there's no URL or the image fails.

**Bonus — "Why are ratings emojis but stored as numbers?"**
Numbers make averages, validation and queries trivial; the symbols are pure
presentation. The mapping lives in one module and the frontend reads it from
`/api/rating-scale`, so there's a single source of truth. The UI animations
are pure CSS and switched off under `prefers-reduced-motion` for accessibility.
