// Plain JavaScript, no framework: fetch() the API and redraw the list.
// User text is always inserted with textContent (never innerHTML) so a
// movie title like "<script>" can't run code in someone's browser (XSS).

const $ = (id) => document.getElementById(id);

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

async function loadMovies() {
  const movies = await api("/api/movies");
  const list = $("movie-list");
  list.replaceChildren();
  for (const movie of movies) {
    const li = document.createElement("li");

    const name = document.createElement("span");
    name.textContent = movie.year ? `${movie.title} (${movie.year})` : movie.title;

    const votes = document.createElement("span");
    votes.className = "votes";
    votes.textContent = `${movie.votes} vote${movie.votes === 1 ? "" : "s"}`;

    const btn = document.createElement("button");
    btn.textContent = "Vote";
    btn.addEventListener("click", () => vote(movie.id));

    li.append(name, votes, btn);
    list.append(li);
  }
}

// Rating scale: stored as 1-5, shown as themed symbols. Loaded from the API
// (GET /api/rating-scale) so the symbols live in one place: app/ratings.py.
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
  const label = $("rating-label");
  label.textContent = step ? `${step.symbol} ${step.value} – ${step.label}` : "Pick a rating";
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

    // Show the label while hovering, fall back to the selected one after.
    label.addEventListener("mouseenter", () => showRatingLabel(step));
    label.addEventListener("mouseleave", () => showRatingLabel(scaleFor(selectedRating())));
    input.addEventListener("change", () => {
      showRatingLabel(step);
      // Replay this symbol's CSS animation once on select (see style.css).
      label.classList.remove("play");
      void label.offsetWidth; // force reflow so the animation restarts
      label.classList.add("play");
      // Longest animation (the reel's spin + burst) is ~1.1s; then reset.
      clearTimeout(label.playTimer);
      label.playTimer = setTimeout(() => label.classList.remove("play"), 1200);
    });

    picker.append(input, label);
  }
}

async function loadHistory() {
  const picks = await api("/api/picks");
  const list = $("history");
  const select = $("review-pick");
  const previouslySelected = select.value;
  list.replaceChildren();
  select.replaceChildren();

  for (const p of picks) {
    const li = document.createElement("li");
    const when = new Date(p.picked_at).toLocaleString();
    const rating = p.average_rating === null
      ? "not rated yet"
      : `${p.average_symbol} ${p.average_label} – avg ${p.average_rating} (${p.review_count})`;
    const votes = `${p.votes_at_pick} vote${p.votes_at_pick === 1 ? "" : "s"}`;
    li.textContent = `${p.movie.title} — ${votes} — ${when} — ${rating}`;
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
  if (!pickId) {
    msg.textContent = "Pick a movie first, then review it.";
    msg.className = "message error";
    return;
  }
  if (!selectedRating()) {
    msg.textContent = "Choose a rating from 💩 to 🎞️💥 first.";
    msg.className = "message error";
    return;
  }
  if (!reviewer) {
    msg.textContent = "Enter your name at the top first.";
    msg.className = "message error";
    return;
  }
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
    msg.textContent = err.message;
    msg.className = "message error";
  }
});

async function vote(movieId) {
  const voter = voterName();
  if (!voter) return showMessage("Enter your name first so votes are counted fairly.", true);
  try {
    await api(`/api/movies/${movieId}/vote`, {
      method: "POST",
      body: JSON.stringify({ voter }),
    });
    showMessage("Vote counted!");
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
    showMessage(`Added "${title}".`);
    await loadMovies();
  } catch (err) {
    showMessage(err.message, true);
  }
});

$("pick-btn").addEventListener("click", async () => {
  try {
    const result = await api("/api/pick", { method: "POST" });
    const m = result.movie;
    $("pick-result").textContent =
      `🍿 Tonight: ${m.title}${m.year ? ` (${m.year})` : ""} — it had ${result.votes_at_pick} votes`;
    await Promise.all([loadMovies(), loadHistory()]);
  } catch (err) {
    $("pick-result").textContent = err.message;
  }
});

$("voter").value = localStorage.getItem("voter") || "";
loadMovies().catch((err) => showMessage(err.message, true));
// Load the scale first so history and reviews can show the right symbols.
loadRatingScale()
  .catch(() => {})
  .then(() => loadHistory())
  .catch(() => {});
