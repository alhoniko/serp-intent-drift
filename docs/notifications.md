# Notifications and digests

Configure one webhook in `monitor.toml` (or on the Panels page of the app):

```toml
[notify]
webhook_url = "https://hooks.slack.com/services/…"
format = "slack"           # json | slack | discord | ntfy
on = ["review", "watch", "collection_error", "stale"]
digest = "weekly"          # none | daily | weekly
digest_day = "monday"
```

## Status changes

After every run the app compares each panel's status with the last one it recorded. Panels whose status *changed into* one of the listed states are collected into one message per run, so a bad morning produces one notification, not forty. The first status a panel ever gets is recorded silently. Every change is also stored as an event, and every delivery attempt is stored with its HTTP status.

`format = "json"` posts `{title, text, event, changes: [...], at}` to any endpoint you own. `slack` and `discord` post the text field those services expect. `ntfy` posts plain text with a `Title` header, so `https://ntfy.sh/<topic>` works directly.

The webhook request never contains the API key. It is a plain POST with a ten-second timeout, no redirects, and no retries; a failed delivery is recorded and the next run tries again if something else changes.

## Digest

`serp-drift digest --days 7` prints a Markdown summary across panels: status counts, the biggest changes against each baseline, AI Overview prevalence, how often your pages were cited, and the most cited hosts. `--format svg` renders a 1200×630 share card in the report's palette; `--format json` gives the data. `--out` writes to a file, `--send` posts it to the webhook. The app serves the same at `/api/digest.md`, `/api/digest.svg`, and `/api/digest?days=7`.

With `digest = "weekly"` the scheduler posts the digest on `digest_day` after that day's first run; `daily` posts it once per day. The last delivery time is stored in the database, so restarting the app does not repeat it.
