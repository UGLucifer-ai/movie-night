# Screenshots

Add these after running `docker compose up --build` locally, then reference
them from the main README:

Already captured (headless Chrome against a local run):

| File | Shows |
| --- | --- |
| `desktop-home.png` | Home page at 1440px: marquee, poster grid (20 Wikipedia posters + 1 fallback card), past picks, reviews |
| `pick-reveal.png` | The curtain + spotlight reveal after clicking "Roll the reel" |
| `mobile.png` | 390×844 mobile layout (iPhone-size) |

Still to add:

| File | What to capture |
| --- | --- |
| `grafana-dashboard.png` | Grafana → Dashboards → Movie Night folder → Movie Night (http://localhost:3000) |
| `prometheus-targets.png` | Prometheus → Status → Targets showing `movie-night` as UP (http://localhost:9090/targets) |
| `github-actions.png` | The green CI run on GitHub (Actions tab) |

Tip: generate some traffic first so graphs aren't flat:

```bash
for i in $(seq 1 50); do curl -s localhost:8000/api/movies > /dev/null; done
```
