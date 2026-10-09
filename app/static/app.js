// Movie Night frontend: plain JavaScript, no framework.
// - fetch() talks to the API, then we redraw parts of the page.
// - User text is always inserted with textContent (never innerHTML) so a
//   movie title like "<script>" can't run code in someone's browser (XSS).
// - Every animation is CSS; JS only toggles classes. Users who prefer
//   reduced motion get the same features with no animation.

const $ = (id) => document.getElementById(id);
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function showMessage(text, isError = false) {
  $("message").textContent = text;
  $("message").className = isError ? "message error" : "message";
}

function voterName() {
  const name = $("voter").value.trim();
  if (name) localStorage.setItem("voter", name);
  return name;
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const detail = typeof body.detail === "string" ? body.detail : res.statusText;
    throw new Error(detail);
  }
  return res.status === 204 ? null : res.json();
}

// ---------- posters ----------

// Same title -> same colours every time (simple string hash -> hue).
function hueFor(text) {
  let hash = 0;
  for (const ch of text) hash = (hash * 31 + ch.codePointAt(0)) % 360;
  return hash;
}

// Generated "poster card" used when there's no image or it fails to load.
function fallbackPoster(movie) {
  const card = document.createElement("div");
  card.className = "poster-fallback";
  const hue = hueFor(movie.title);
  card.style.setProperty("--h1", hue);
  card.style.setProperty("--h2", (hue + 50) % 360);

  const icon = document.createElement("span");
  icon.className = "fallback-icon";
  icon.textContent = "🎞️";
  const title = document.createElement("span");
  title.className = "fallback-title";
  title.textContent = movie.title;
  const year = document.createElement("span");
  year.className = "fallback-year";
  year.textContent = movie.year || "";

  card.append(icon, title, year);
  card.setAttribute("role", "img");
  card.setAttribute("aria-label", `${movie.title} (no poster available)`);
  return card;
}

// <div class="poster"> with a lazy-loaded image, or the fallback card.
function posterFor(movie, { eager = false } = {}) {
  const frame = document.createElement("div");
  frame.className = "poster";
  if (!movie.poster_url) {
    frame.append(fallbackPoster(movie));
    return frame;
  }
  const img = document.createElement("img");
  img.src = movie.poster_url;
  img.alt = `Poster for ${movie.title}${movie.year ? ` (${movie.year})` : ""}`;
  img.loading = eager ? "eager" : "lazy"; // browser only downloads it when near the screen
  img.decoding = "async";
  img.referrerPolicy = "no-referrer";
  img.addEventListener("error", () => img.replaceWith(fallbackPoster(movie)), { once: true });
  frame.append(img);
  return frame;
}

// Blurred, slowly drifting poster mosaic behind everything.
function paintMosaic(movies) {
  const mosaic = $("poster-mosaic");
  const urls = movies.map((m) => m.poster_url).filter(Boolean);
  if (!urls.length || mosaic.childElementCount) return;
  for (let i = 0; i < 24; i++) {
    const tile = document.createElement("div");
    tile.className = "mosaic-tile";
    // CSS url() with a JSON-quoted string: safe even with odd characters.
    tile.style.backgroundImage = `url(${JSON.stringify(urls[i % urls.length])})`;
    mosaic.append(tile);
  }
}

// ---------- the lineup ----------

let lineup = [];

async function loadMovies() {
  lineup = await api("/api/movies");
  const list = $("movie-list");
  list.replaceChildren();
  lineup.forEach((movie, index) => {
    const li = document.createElement("li");
    li.className = "movie-card";
    li.style.setProperty("--i", index); // staggered entrance animation

    const votes = document.createElement("span");
    votes.className = "vote-badge";
    votes.textContent = `${movie.votes} vote${movie.votes === 1 ? "" : "s"}`;

    const info = document.createElement("div");
    info.className = "movie-info";
    const name = document.createElement("h3");
    name.textContent = movie.title;
    const year = document.createElement("span");
    year.className = "movie-year";
    year.textContent = movie.year || "";
    info.append(name, year);

    const btn = document.createElement("button");
    btn.className = "vote-btn";
    btn.textContent = "Vote";
    btn.setAttribute("aria-label", `Vote for ${movie.title}`);
    btn.addEventListener("click", () => vote(movie.id));

    li.append(posterFor(movie), votes, info, btn);
    list.append(li);
  });
  paintMosaic(lineup);
  return lineup;
}

// Posters are fetched by the server in the background right after startup /
// after adding a film, so refresh a couple of times while some are missing.
async function refreshWhilePostersLoad(tries = 3) {
  for (let i = 0; i < tries; i++) {
    await sleep(3000);
    const movies = await api("/api/movies");
    const missingBefore = lineup.filter((m) => !m.poster_url).length;
    const missingNow = movies.filter((m) => !m.poster_url).length;
    if (missingNow < missingBefore) await loadMovies();
    if (missingNow === 0) return;
  }
}

// ---------- rating scale (💩 .. 🎞️💥) ----------
// Stored as 1-5, shown as symbols. Loaded from GET /api/rating-scale so the
// symbols live in one place: app/ratings.py.
let ratingScale = [];

function scaleFor(rating) {
  if (rating === null || rating === undefined || !ratingScale.length) return null;
  const step = Math.min(5, Math.max(1, Math.floor(rating + 0.5)));
  return ratingScale.find((s) => s.value === step);
}

function selectedRating() {
  const checked = document.querySelector('input[name="rating"]:checked');
  return checked ? Number(checked.value) : null;
}

function showRatingLabel(step) {
  $("rating-label").textContent = step ? `${step.symbol} ${step.value} – ${step.label}` : "Pick a rating";
}

async function loadRatingScale() {
  ratingScale = await api("/api/rating-scale");
  const picker = $("review-rating");
  for (const step of ratingScale) {
    const id = `rating-${step.value}`;
    const input = document.createElement("input");
    input.type = "radio";
    input.name = "rating";
    input.id = id;
    input.value = step.value;

    const label = document.createElement("label");
    label.htmlFor = id;
    label.className = `rating-option rating-${step.value}`;
    label.title = `${step.value} – ${step.label}`; // native tooltip on hover
    label.setAttribute("aria-label", `${step.value} – ${step.label}`);
    label.textContent = step.symbol;

    label.addEventListener("mouseenter", () => showRatingLabel(step));
    label.addEventListener("mouseleave", () => showRatingLabel(scaleFor(selectedRating())));
    input.addEventListener("change", () => {
      showRatingLabel(step);
      // Replay this symbol's CSS animation once on select (see style.css).
      label.classList.remove("play");
      void label.offsetWidth; // force reflow so the animation restarts
      label.classList.add("play");
      clearTimeout(label.playTimer);
      label.playTimer = setTimeout(() => label.classList.remove("play"), 1200);
    });

    picker.append(input, label);
  }
}

// ---------- history + reviews ----------

async function loadHistory() {
  const picks = await api("/api/picks");
  const list = $("history");
  const select = $("review-pick");
  const previouslySelected = select.value;
  list.replaceChildren();
  select.replaceChildren();

  if (!picks.length) {
    const empty = document.createElement("li");
    empty.className = "history-empty";
    empty.textContent = "No picks yet. Roll the reel!";
    list.append(empty);
  }

  for (const p of picks) {
    const li = document.createElement("li");
    li.className = "history-card";

    const caption = document.createElement("div");
    caption.className = "history-caption";
    const title = document.createElement("strong");
    title.textContent = p.movie.title;
    const rating = document.createElement("span");
    rating.className = "history-rating";
    rating.textContent = p.average_rating === null
      ? "not rated yet"
      : `${p.average_symbol} ${p.average_label} · ${p.average_rating} (${p.review_count})`;
    const when = document.createElement("span");
    when.className = "history-when";
    when.textContent = new Date(p.picked_at).toLocaleDateString();
    caption.append(title, rating, when);

    li.append(posterFor(p.movie), caption);
    list.append(li);

    const option = document.createElement("option");
    option.value = p.id;
    option.textContent = `${p.movie.title} (${new Date(p.picked_at).toLocaleDateString()})`;
    select.append(option);
  }

  if (!picks.length) {
    const option = document.createElement("option");
    option.textContent = "Pick a movie first";
    option.value = "";
    select.append(option);
  } else if (previouslySelected) {
    select.value = previouslySelected;
  }
  await loadReviews();
}

async function loadReviews() {
  const pickId = $("review-pick").value;
  $("review-list").replaceChildren();
  $("review-summary").textContent = "";
  if (!pickId) return;

  const data = await api(`/api/picks/${pickId}/reviews`);
  $("review-summary").textContent = data.average_rating === null
    ? "No reviews yet. Be the first!"
    : `Average: ${data.average_symbol} ${data.average_label} – ${data.average_rating} / 5 from ${data.review_count} review(s)`;

  for (const r of data.reviews) {
    const li = document.createElement("li");
    const head = document.createElement("strong");
    head.textContent = `${r.symbol} ${r.label} · ${r.reviewer}`;
    const text = document.createElement("span");
    text.textContent = r.comment ? ` — ${r.comment}` : "";
    li.append(head, text);
    $("review-list").append(li);
  }
}

$("review-pick").addEventListener("change", () => loadReviews().catch(() => {}));

$("review-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const pickId = $("review-pick").value;
  const reviewer = voterName();
  const msg = $("review-message");
  const fail = (text) => {
    msg.textContent = text;
    msg.className = "message error";
  };
  if (!pickId) return fail("Pick a movie first, then review it.");
  if (!selectedRating()) return fail("Choose a rating from 💩 to 🎞️💥 first.");
  if (!reviewer) return fail("Enter your name at the top first.");
  try {
    await api(`/api/picks/${pickId}/reviews`, {
      method: "POST",
      body: JSON.stringify({
        reviewer,
        rating: selectedRating(),
        comment: $("review-comment").value.trim(),
      }),
    });
    $("review-comment").value = "";
    document.querySelectorAll('input[name="rating"]').forEach((i) => { i.checked = false; });
    showRatingLabel(null);
    msg.textContent = "Thanks for the review!";
    msg.className = "message";
    await loadHistory();
  } catch (err) {
    fail(err.message);
  }
});

// ---------- voting + adding ----------

async function vote(movieId) {
  const voter = voterName();
  if (!voter) {
    $("voter").focus();
    return showMessage("Enter your name first so votes are counted fairly.", true);
  }
  try {
    await api(`/api/movies/${movieId}/vote`, { method: "POST", body: JSON.stringify({ voter }) });
    showMessage("Vote counted! 🎟️");
    await loadMovies();
  } catch (err) {
    showMessage(err.message, true);
  }
}

$("add-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const title = $("title").value.trim();
  const year = $("year").value ? Number($("year").value) : null;
  try {
    await api("/api/movies", {
      method: "POST",
      body: JSON.stringify({ title, year, added_by: voterName() || "anonymous" }),
    });
    $("add-form").reset();
    showMessage(`Added "${title}" — finding its poster…`);
    await loadMovies();
    refreshWhilePostersLoad(2).catch(() => {});
  } catch (err) {
    showMessage(err.message, true);
  }
});

// ---------- the big reveal ----------

let lastFocus = null;

function closeReveal() {
  const reveal = $("reveal");
  reveal.classList.remove("open", "shuffling");
  reveal.hidden = true;
  document.body.classList.remove("no-scroll");
  if (lastFocus) lastFocus.focus();
}

async function playReveal(result, candidates) {
  const reveal = $("reveal");
  const m = result.movie;
  lastFocus = document.activeElement;

  $("reveal-title").textContent = m.title;
  $("reveal-meta").textContent =
    `${m.year ? `${m.year} · ` : ""}${result.votes_at_pick} vote${result.votes_at_pick === 1 ? "" : "s"}`;
  $("reveal-poster").replaceChildren(posterFor(m, { eager: true }));

  reveal.hidden = false;
  reveal.classList.remove("open");
  document.body.classList.add("no-scroll");

  if (!reducedMotion.matches) {
    // Drumroll: posters flicker behind the closed curtain, slowing down.
    reveal.classList.add("shuffling");
    const shuffle = $("reveal-shuffle");
    const pool = candidates.length ? candidates : [m];
    let delay = 60;
    for (let i = 0; i < 14; i++) {
      shuffle.replaceChildren(posterFor(pool[i % pool.length], { eager: true }));
      await sleep(delay);
      delay *= 1.17;
    }
    shuffle.replaceChildren();
    reveal.classList.remove("shuffling");
  }

  reveal.classList.add("open"); // curtains part, spotlight hits the winner
  $("reveal-close").focus();
}

$("reveal-close").addEventListener("click", closeReveal);
$("reveal").addEventListener("click", (e) => { if (e.target === $("reveal")) closeReveal(); });
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !$("reveal").hidden) closeReveal();
});

$("pick-btn").addEventListener("click", async () => {
  const button = $("pick-btn");
  button.disabled = true;
  try {
    const candidates = [...lineup].sort(() => Math.random() - 0.5);
    const result = await api("/api/pick", { method: "POST" });
    const m = result.movie;
    $("pick-result").textContent =
      `🍿 Tonight: ${m.title}${m.year ? ` (${m.year})` : ""} — it had ${result.votes_at_pick} vote${result.votes_at_pick === 1 ? "" : "s"}`;
    await playReveal(result, candidates);
    await Promise.all([loadMovies(), loadHistory()]);
  } catch (err) {
    $("pick-result").textContent = err.message;
  } finally {
    button.disabled = false;
  }
});

// ---------- start ----------

$("voter").value = localStorage.getItem("voter") || "";
loadMovies()
  .then((movies) => {
    if (movies.some((m) => !m.poster_url)) refreshWhilePostersLoad().catch(() => {});
  })
  .catch((err) => showMessage(err.message, true));
// Load the scale first so history and reviews can show the right symbols.
loadRatingScale()
  .catch(() => {})
  .then(() => loadHistory())
  .catch(() => {});
