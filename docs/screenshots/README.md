# Screenshots

Add these after running `docker compose up --build` locally, then reference
them from the main README:

| File | What to capture |
| --- | --- |
| `app.png` | The Movie Night page at http://localhost:8000 after a few votes and one pick |
| `grafana-dashboard.png` | Grafana → Dashboards → Movie Night folder → Movie Night (http://localhost:3000) |
| `prometheus-targets.png` | Prometheus → Status → Targets showing `movie-night` as UP (http://localhost:9090/targets) |
| `github-actions.png` | The green CI run on GitHub (Actions tab) |

Tip: generate some traffic first so graphs aren't flat:

```bash
for i in $(seq 1 50); do curl -s localhost:8000/api/movies > /dev/null; done
```
