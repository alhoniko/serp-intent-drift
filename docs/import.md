# Import keywords

The import wizard (Settings → Import keywords, or `#/p/<project>/import`) turns the queries a site already ranks for into panels in three steps: pick a source, choose queries, confirm. Existing panels are never overwritten; duplicates are skipped. Every capture afterwards comes from SearchApi. The sources only supply the keyword list.

## Sources

**Search Console export (CSV, free).** Performance → Export → download the zip → use `Queries.csv`. Any CSV with a query column works, including Finnish headers and Ahrefs or Semrush keyword exports. Impressions, clicks, and position are read when the columns exist.

**Ahrefs API (organic keywords).** `GET /v3/site-explorer/organic-keywords` for the project site (or any target), one request per fetch. Needs an Ahrefs plan with API access (Lite and up) and a token stored under Settings → Integrations, `serp-drift key set --service ahrefs`, or `AHREFS_API_TOKEN`. Rows per request are capped by the plan (Lite 100, Standard 250, Advanced 500, Enterprise unlimited).

Each fetch returns keyword, search volume, best position, ranking URL, position kind, Ahrefs's intent flags, and the branded flag; ordering by traffic adds the traffic estimate. Cost in API units is `max(50, per-row cost × rows)`: 19 units per row by default, 29 with traffic, so 500 keywords cost about 9 500 units. The wizard shows the estimate before the fetch and the real figure (from the `x-api-units-cost-total` header) after it, and records it as an `import_fetch` event in Activity. The token travels only in the Authorization header; it is never written to a URL, a log, or an error message.

## Choosing queries

Filters: minimum impressions or volume, maximum position, a brand term to exclude (plus Ahrefs's branded flag), a text filter, and hide-already-monitored. `Select visible`, `Select top 50`, `Clear`, or `Import all visible` to skip the manual pick. The suggested intent comes from serp-drift's own rules; when Ahrefs disagrees, its label is shown next to it. Candidates are ranked by traffic, impressions, volume, clicks, then position.

## Confirm

Engine, country, language, and device default to the project's search block (country to the fetched Ahrefs country). Optionally collect the first capture right away; the credit estimate uses the project's AI Overview setting.

## Command line

```sh
serp-drift import --source ahrefs --country us --limit 500 --min-volume 50 --exclude-brand --dry-run
serp-drift import --source ahrefs --top 100            # append the first 100 candidates as panels
serp-drift import --file Queries.csv --min-volume 200  # the same filters over a CSV
```

`--dry-run` prints the filtered candidates as JSON and changes nothing. Without it, panels are appended to `monitor.toml` and are due on the next `serp-drift run`.

## API

- `POST /api/p/<project>/import/preview`, body: CSV text (or JSON `{"text": ...}`) → candidates.
- `POST /api/p/<project>/import/fetch`, JSON `{"source": "ahrefs", "target": "example.com", "country": "us", "limit": 500, "traffic": false}` → the same shape plus a `source` block with `units`, `rows`, `date`, `fields`.
- `POST /api/p/<project>/panels/bulk`, JSON `{"panels": [{"query": ...}], "source": "ahrefs", "collect": true}`.
- `POST /api/p/<project>/key`, JSON `{"key": "...", "service": "ahrefs"}`; `GET /api/p/<project>/status` reports `integrations.ahrefs.key` as `file`, `environment`, or `missing`.
