# Collect with GitHub Actions

No server, no laptop that must stay awake: a fork of this repository can collect once a day, commit the SQLite database and the static report back to itself, and publish the report on GitHub Pages.

1. Fork the repository.
2. Create the workspace inside the fork and commit it:
   ```sh
   pip install .
   serp-drift init --dir workspace --no-prompt --query "your query" --page "https://your-site.example/page/" --intent informational
   git add workspace/monitor.toml && git commit -m "Add the panel" && git push
   ```
   Edit `workspace/monitor.toml` to add panels; the workspace `.gitignore` keeps the key out of git.
3. Add the repository secret `SEARCHAPI_API_KEY` under Settings → Secrets and variables → Actions.
4. Optional: Settings → Pages → Source: GitHub Actions. The report is then published after every run.

`.github/workflows/collect.yml` runs daily at 08:17 UTC and on demand from the Actions tab. It installs the package, runs `serp-drift run`, force-adds `workspace/data`, `workspace/reports`, and `workspace/logs`, commits, pushes, and uploads the report as a Pages artifact. In the upstream repository the job finds no workspace and exits without doing anything.

What to expect:

- The database grows by a few hundred kilobytes per day for forty panels with raw responses; `raw_retention_days` keeps that in check.
- A run that fails leaves a commit with the updated report, so the collection-error state is visible on the published page.
- Notifications work from Actions too: set `[notify]` in `monitor.toml`. The webhook URL is stored in the config, so keep the fork private if the URL should stay unknown.
- Period comparisons and URL history need the app: clone the fork, run `serp-drift serve --dir workspace`, and every view works on the committed database.
