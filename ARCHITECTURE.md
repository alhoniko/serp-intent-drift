# Architecture

One Python package, standard library only, one SQLite file per workspace. Everything below is in `serp_drift/`.

## Data flow

```
monitor.toml ──load_config──▶ targets (query, engine, market, page, identity)
                                   │
        SearchApi ◀──client.search─┤ collect()            ┌─ page_fetch (optional, SSRF-guarded)
        google_ai_overview ◀───────┤ expand_ai_overview   └─ intent.page_profile
                                   ▼
                              normalize()  ── engines.rows ── intent.classify (packs) ── ai_overview_summary
                                   ▼                                          ▲ optional labeling.apply
                              Store.add()  → snapshots, results index, ai_overviews
                                   ▼
        analysis.analyze() ── fixed baseline, confirmation, status ──▶ report.build_report()
        history.*          ── timeline, trajectories, change log, period compare
        insights.compute() ── cross-panel statistics ── dataset()
        notify.after_run() ── status changes → webhook; digest
                                   ▼
        server (HTTP + JSON API + scheduler thread) · report.write_report (static HTML) · mcp (stdio)
```

## Modules

| Module | Responsibility |
| --- | --- |
| `workspace.py` | Resolves the workspace directory, key file (0600), logs. |
| `config.py` | Validates `monitor.toml`, computes panel identities, edits targets/settings/notify in place. |
| `engines.py` | Which parameters each SearchApi engine accepts and where its ranked rows live. |
| `client.py` | Bounded HTTP client: bearer auth, no redirects, retries with `Retry-After`, per-run budget, `search`, `ai_overview`, `locations`, `account`. |
| `packs.py` / `rules/*.toml` | Per-language intent rules; registry, user packs, analysis version. |
| `intent.py` | Lexical classification of a result (title 3, snippet 2, URL 2, section 2 points) and page profiles. |
| `normalize.py` | Provider payload → normalized snapshot: canonical URLs, top-ten rows, features, AI Overview summary, aggregates. |
| `labeling.py` | Optional OpenAI-compatible labels for unknown results, cached. |
| `storage.py` | SQLite schema and migrations: snapshots, results, attempts, runs, panel_settings, events, ai_overviews, meta, labels. `history()` applies the analysis overlays (human exclusions, the query-term check) to every read. |
| `analysis.py` | Fixed baseline, interval sampling, confirmation, the five components, `compare_sets`. |
| `history.py` | Timeline, URL trajectories, change log, period resolution, citations, stability. |
| `insights.py` | Cross-panel metrics and the dataset export. |
| `notify.py` | Status-change detection, webhook formats, digest (Markdown, SVG). |
| `report.py` | Report dict and the self-contained HTML/JSON/CSV export. |
| `scheduler.py` | Due detection and the polling thread. |
| `importing.py` | Search Console / query CSV parsing and the shared candidate ranking used by every source. |
| `connect.py` | The Connect agent page's data: the stdio command for a workspace, per-client MCP configuration, and a self-test that runs the handshake in a subprocess. |
| `sources.py` | Ahrefs organic-keywords client: one bounded request, token only in the header, units reported. Keyword discovery only. |
| `server.py` | `ProjectState` (everything the app can do with one workspace), `App` (several projects, portfolio, project creation), and the HTTP handler with auth, CSRF, and security headers. `/api/p/<project>/…` selects a project; bare `/api/…` means the first one. |
| `mcp.py` | JSON-RPC over stdio exposing `AppState` to agents. |
| `schedule.py` | launchd / systemd / cron generation and installation. |
| `cli.py` | Commands. `collect()` and `run_once()` are the collection entry points used by the CLI, the app, and MCP. |

## Projects and the site

A project is one workspace directory. `App` holds several, the scheduler iterates them, and the portfolio merges their attention items. `[project] site` names the hostname the analysis looks for in every capture: `history.site_hit` finds the best-ranking URL on that host, `analyze()` reports its position, its previous URL, and whether the ranking URL changed, and `citations()` counts captures whose AI Overview cited the site. A declared page remains optional and adds the page-fit verdict.

## Identity and baselines

A panel identity is a hash of the exact search parameters (query, engine, gl, hl, device, location, page) and the analysis version (rule packs, plus an LLM tag when labeling is on). Every stored observation carries it, so changing any of those starts a new panel and never silently compares different things. Request-only parameters such as `link=resolved` are excluded on purpose.

The baseline is the first `baseline_size` usable, interval-spaced captures after the optional `baseline_from` date. It never rolls forward on its own. Alerts need `confirmations` consecutive spaced captures that agree. Period comparisons use the same arithmetic as the alert path (`compare_sets`), so nothing in the UI shows a number the alert could not produce.

## Security model

- The API key is read from the environment or a 0600 file, sent only as a bearer header, never placed in URLs, logs, reports, or the database; the client refuses redirects.
- Optional page fetches resolve DNS first, refuse private and non-global addresses, allow only ports 80/443, pin the connection to the validated IP, cap the body at 2 MB, and refuse HTTPS→HTTP redirects.
- The app binds to loopback by default. Any other bind requires a token (bearer header or HttpOnly cookie). Every mutation needs `X-Requested-With: serp-drift` and, when an `Origin` is present, it must match the host. Responses carry CSP, nosniff, no-referrer, and frame-deny headers. Assets are served from an allowlist; JSON fixtures and Python files are never served.
- Stored provider payloads are scrubbed of tokens, keys, and images; the raw subset is pruned after `raw_retention_days`.
- Exports escape spreadsheet formulas and HTML-embedded JSON.

## Extension points

- **Engine:** add an entry to `engines.ENGINES` with the rows key, link/snippet fields, accepted parameters, and default type.
- **Language:** add `rules/<lang>.toml`; see `docs/language-packs.md`.
- **Notification format:** add a branch to `notify.payload_for`.
- **Storage:** bump `SCHEMA_VERSION` and add `CREATE TABLE IF NOT EXISTS`; migrations run once on open.
- **UI view:** add a renderer in `assets/app.js` and a route in `render()`; the API is in `server.py`.

## Decisions

Standard library only, so `uv tool install` works everywhere and the client can be copied into other projects. TOML stays the source of truth for panels so a workspace is reviewable in version control; the app edits it rather than replacing it. Static export stays a first-class feature because a single HTML file is the easiest thing to share. The fixed baseline is a deliberate choice: slow drift must not normalize itself away.

## 0.5.0 evidence boundary

`quality.py` retains only allowlisted returned context and quarantines explicit mismatches. `observations` preserves the original normalized evidence before optional semantic classification. `snapshots` retains capture-time derived labels. `observation_reviews` overlays reversible exclusions; `analysis_runs` appends versioned drift results; `review_cases` and `events` retain decisions and signal episodes. The raw provider subset remains separately prunable.

`analysis.explain` supplies one decision contract to the app, JSON exports, static report and MCP. Whole-period membership is frequency-weighted. Review lifecycle never treats an unknown or failed collection as recovery. Reading a dashboard does not create a case or send a notification.

Workspace rules use a ContextVar instead of a process-wide mutable registry. Configuration mutations use an advisory lock, full validation and atomic replacement. SQLite collection locks remain per workspace. `maintenance` provides SQLite backup and offline reanalysis; `evaluation` exports blind annotation tasks and computes held-out human-label metrics.

## 0.6.0 query check and bounded collection

`quality.query_match` scores how much of a capture's rank weight contains every query term; `quality.apply_query_check` compares each capture with the panel's best one and marks outliers `query_mismatch`. It runs inside `Store.history()`, before any date filter, so the app, reports, exports, notifications, insights and MCP all see the same overlay; the stored observation never changes and a human review with `excluded = false` overrides it. `analysis.INVALID_STATES` (quarantined, excluded, query_mismatch) are skipped by the interval sampler; the newest valid capture is the analysed `latest`, and `rejected_after_latest` lists what was skipped.

`cli.capture()` performs one capture of record. With `retry_query_mismatch`, it normalizes the response locally first, stores a rejected response without an Overview expansion, pauses, and searches again. `record_attempt` writes the requests spent since the previous attempt row, which `Store.total_requests()` sums for the workspace cap. `scheduler.budget_exhausted()` (cap or `collect_until`) stops due detection; `report.build_report` turns overdue panels of an ended workspace into final observations and `ProjectState.attention` shows one notice.
