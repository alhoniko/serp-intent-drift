# Changelog

## Unreleased · 0.7 · the triage redesign

- **Inbox replaces the dashboard.** One status sentence, a status bar for every panel, and a queue grouped as Needs a decision, Watching, Collection health, Seen and Settled in the last 24 hours, with a preview of the selected panel beside it. Panels where your site moved or left the top 10 sort first; J/K move and Enter opens. *Mark as seen* acknowledges a watch until the next capture. All projects has a merged inbox.
- **One panel, one story.** The panel page leads with a verdict and the next capture, then SERP change, intent, page fit and data as four measures, the score by capture (baseline window, threshold, rejected captures), the score as its five contributions, the intent mix and the top 10 against the baseline. Seven tabs become six: Review and Data quality merge into Evidence, an observation ledger with exclusions, decisions and the status trail.
- **Less chrome.** Activity and Runs merge into Log (status changes first, per-event flap counts, requests per day, flapping panels). Settings are split into General, Collection, Notifications, Keys and integrations, Classification and Workspace; the watch threshold previews how many panels it would watch today. Import and *Add a panel by hand* merge into Add keywords, with edge selection, range select and a cost estimate. The sidebar shows the collector, the next run and the request budget.
- **Tables say which market they mean.** Engine, device, country and location tags tell apart panels that share a query. The panels table adds the last twelve captures and flags flapping panels.
- ⌘K searches panels, projects, ranking pages and actions. Dark is the default theme; light and system use the same tokens. Geist is bundled (SIL Open Font License, `serp_drift/assets/OFL-Geist.txt`); the app still loads nothing from other hosts.
- A product mark in the sidebar and as the favicon: a rounded square cut along a fault line, its lower half drifted. The media kit has new screenshots of this interface with live data from 30 September 2026 (`docs/media/v0.7`); `capture.py` waits for the loading skeleton to clear.
- The report timeline now carries `site_position` and `site_url` for every capture, so lists can show when your page left the top 10 without loading each panel. No change to intent rules, panel identities, scores or the storage schema.

## 0.6.0 · 2026-09-23 · trustworthy collection (release candidate)

Changes found through real use: 400 live captures across 54 panels and a prospective 23-panel study.

- **Query-term check (drift-v4).** About one in four Google captures from 17 September on returned organic results for a single word of the query while the provider reported the requested query unchanged. A capture whose results miss the query terms far more than the panel's own best capture is marked `query_mismatch` in the analysis view. The observation is kept unchanged, the reason is shown, and a reviewer can keep it with a written reason. Before this, such captures caused most `watch` states in the live workspaces.
- **Invalid observations are not samples.** Quarantined, excluded and query-mismatched captures no longer occupy an interval slot or count toward a baseline. The status comes from the newest valid capture, rejected newer captures are disclosed, and staleness is measured from the valid capture. URL trajectories, the change log, citation history and stability use valid captures. The timeline and chart mark rejected captures.
- **Retry a rejected response** (`retry_query_mismatch = 1|2`, default off). The rejected response is stored without spending an AI Overview expansion, then the search is repeated after a 30-second pause. Attempt rows record requests since the previous row, so retries are never counted twice.
- **Bounded collection.** `max_total_requests` caps every request a workspace records, and `collect_until` ends collection at a UTC time. The scheduler stops, the dashboard shows the budget and one "Collection ended" notice, and panels keep final observations instead of reporting themselves overdue. `estimate` shows the cap, end date and maximum query-check retries.
- **Annotation samples.** `benchmark export --sample-results N --latest-windows` produces a manageable, deterministic human-review sample and skips rejected captures.
- Dataset export adds a `quality_state` column. The settings page edits the three new settings.
- The main column is centered and widens up to 1,600 px on large screens (was left-aligned at 1,200 px).
- Documentation: methodology describes whole-baseline comparison (the 0.5 text still described a final-capture anchor), the query-term check, bounded collection and live mismatch rates. New release notes: [docs/release-v06.md](docs/release-v06.md). An example workspace rule pack for free-tool SERPs is in `examples/rules/`.
- No change to intent rules (`rules-en-fi-v2`), panel identities, storage schema (6) or synthetic demo outcomes. Human-reviewed accuracy is still unmeasured.

## 0.5.0 · 2026-09-20 · evidence and decisions

- Returned search-context provenance, context quarantine, reversible observation exclusions and an audit trail; legacy data remains visibly unverified.
- Drift method `drift-v3`: frequency-weighted URL/features and mean ranks over the whole baseline, recent comparison and baseline variability, stricter confirmation and repeated recovery.
- Independent SERP change, intent, page fit and data quality measures across the app, JSON, static reports and MCP.
- Review episodes, recorded decisions/rationale, follow-up dates, keyword groups, saved filters and notification deduplication with failed-delivery retries.
- Query-aware optional model classification, independent format/task/evidence, full-review mode, rule disagreements, strict evidence validation, versioned endpoint/prompt/query cache, no transient-error cache poisoning.
- Guided first-run setup, responsive evidence views, native accessible controls, modal keyboard search, labeled switches, dark/light themes and explicit cost/data-sharing settings.
- Schema 6 separates original observations, analysis records and review state; atomic config edits and workspace-local rule registries.
- Consistent SQLite backups, offline versioned reanalysis, blind human-label exports and held-out metrics (precision, recall, coverage, false negatives and episode delay).
- No measured intent accuracy claim. Human benchmark, publication and independent accessibility audit remain release validation tasks.

## 0.4.0 · 2026-09-16 · projects and the calm redesign

- **Projects.** One `serve` hosts several workspaces (`--projects <root>`, or `--also <dir>` repeated); every API path takes `/api/p/<project>/…`; a portfolio view merges every project's status, health, cost, and attention items. Projects can be created from the app when a projects root is given.
- **Site detection.** `[project] site = "example.com"` makes every panel track whichever of your URLs ranks: position, ranking-URL changes (cannibalisation), and AI Overview citations of your site, without declaring a page per query. Declared pages still work and add a page-fit verdict.
- **Keyword import.** A three-step wizard turns a Search Console export (or any CSV with a query column) into panels: candidates with impressions, clicks, position, and a suggested intent; filters; a credit estimate; bulk creation without duplicates; optional first capture. `POST /api/p/<id>/import/preview` and `/panels/bulk` for scripts.
- **Connect agent.** A sidebar entry that opens a page with the project's MCP server command, ready-made configuration for Claude Code, Claude Desktop, Cursor, Codex CLI, VS Code, and any other stdio client (PYTHONPATH filled in for source checkouts), a connection test that runs the real handshake, the tool list, and example prompts. `GET /api/p/<id>/mcp`, `POST /api/p/<id>/mcp/check`.
- **Ahrefs import.** The wizard's second source: fetch the organic keywords of the project site (or any target) through Ahrefs API v3 with a token stored like the SearchApi key (`ahrefs.key`, `AHREFS_API_TOKEN`, or Settings → Integrations); volume, best position, ranking URL, Ahrefs's intent and branded flags; unit estimate before and the real cost after each fetch; `Import all visible`; `serp-drift import --source ahrefs` with the same filters for cron users. Keyword discovery only, every capture still comes from SearchApi. DataForSEO was left out on purpose.
- **The calm redesign.** New app UI from the design canvas: sidebar navigation with a project switcher and ⌘K palette, "Needs attention" as the first thing on every dashboard (unacknowledged reviews, errors, stale panels, broken setup, each with one action), a five-column panel table with segmented filters, a panel page whose top block always names the next expected event with a date instead of a dash, a score chart with the baseline window and the watch threshold, "What moved" meters, Your site and AI Overview cards, expandable results with evidence, a URL trajectory matrix with rank bands, a compare tool with presets and A/B side cards, an AI Overview reader with annotated references, panel settings with pause and type-to-confirm removal, project settings, activity, runs, insights, and a mobile layout. Light and dark themes (`?theme=light|dark` forces one).
- Shell components: the sidebar project switcher is a real menu (all projects, each project with health and attention, new project) with arrow-key navigation; search has its own field under it and an icon in the mobile top bar, both opening the ⌘K palette, whose rows now show the market so desktop and mobile twins are distinguishable. Scrollbars, selects, checkboxes, and native pickers are themed through tokens in both colour schemes (`color-scheme`, `scrollbar-color`, one chevron asset); selects are a shadcn-style component (trigger, portalled listbox with check mark, hover, arrow keys, type-ahead) over a hidden native element so forms keep working, and the remaining inline styles became utility classes.
- Panel actions: acknowledge a review, pause a panel, set or clear the declared page in place. Configs may have zero panels. Scheduler entries can include extra projects. The static HTML export keeps the field-tool style.

## 0.3.0 · 2026-09-16 · the app

- Screenshots in `docs/media/` come from the example workspace, where page positions, page fit, and citations are visible.
- Fix: scheduler entries generated from a source checkout now set PYTHONPATH (or use the installed `serp-drift` script), so a workspace outside the repository runs under launchd, systemd, and cron.
- `examples/seo-blog-panel.toml`: a live example panel on a publisher that ranks, so page position, page fit, and citations are visible from the first capture.

- Documentation: README quickstart with screenshots, ARCHITECTURE, CONTRIBUTING, SECURITY, code of conduct, issue and pull request templates, and a media kit in `docs/media/`.
- Workspace directory (`--dir`, `SERP_DRIFT_DIR`): config, database, reports, logs, and a 0600 key file in one place.
- `serp-drift init` scaffolds a workspace and optionally the first panel and the key; `serp-drift key set|status|path`.
- `serp-drift run` replaces the shell wrapper: collects what is due, always rebuilds the report, appends a JSON log line, and returns the collection exit code for cron, launchd, and CI.
- `serp-drift where` prints resolved paths.
- Database schema 2: indexed result rows for URL history, run records, panel settings, and an event log. Version 1 databases migrate in place.
- `raw_retention_days` (default 90) drops the raw provider subset of old captures; normalized observations are kept forever.
- Period comparison with the same five components for any two captures or date ranges; presets for baseline, latest, last and previous 7 days, last 30 days, and the first week.
- Re-anchor a panel's baseline from a chosen date without deleting history.
- History views: capture timeline, URL trajectories, and a change log between consecutive captures.
- Optional LLM labeling (`[labeling]`, off by default): an OpenAI-compatible endpoint labels results the rules left unknown, batched and cached in the database (schema 5), marked in the evidence, and reflected in the analysis version so baselines stay separate.
- MCP server (`serp-drift mcp`): stdio JSON-RPC with tools for panels, history, comparisons, citations, insights, host search, and an explicit collect_now; works with Claude Code, Claude Desktop, and Cursor.
- Packaging: PyPI classifiers and project URLs, ruff configuration and a lint job, CI across Python 3.11–3.14, and a tag-triggered release workflow that builds, attaches to a GitHub Release, and publishes through PyPI trusted publishing. Fixed f-string syntax that only worked on Python 3.12+.
- Locations API lookup: `SearchApi.locations()`, `/api/locations?q=`, and a typeahead on the add-panel form; canonical strings only. `serp-drift estimate` now counts AI Overview expansions. `docs/client.md` documents the client as a standalone module with the observed credit costs.
- Insights across panels (`serp-drift insights`, `/api/insights`, Insights page): AI Overview and feature prevalence, turnover, rank movement, intent stability, cited hosts, your pages, split by language, device, and engine. Dataset export (`serp-drift export`, `/api/export/dataset.zip`): captures, ranked results, citations, panels, insights.
- `serp-drift schedule`: prints or installs a launchd LaunchAgent (macOS), user systemd units (Linux), or a crontab line, in `app` mode (keep `serve` alive) or `run` mode (daily job). Dockerfile and compose file, a system unit and Caddy example for servers, and a fork-and-run GitHub Actions workflow that collects daily, commits the database, and publishes the report to Pages.
- Notifications: one webhook (`[notify]` in `monitor.toml`), formats for JSON, Slack, Discord, and ntfy, one message per run listing panels that changed into chosen statuses, every attempt recorded as an event. Daily or weekly digest across panels as Markdown, JSON, or an SVG share card (`serp-drift digest`, `/api/digest.*`), posted automatically on the chosen day. Schema 4 adds a small meta table.
- The app: `serp-drift serve` runs a dashboard, a JSON API, and the scheduler in one process (standard library only). Views: dashboard with status cards and credits, panel overview, history with URL trajectories and a change log, compare tool for any two captures or periods, AI Overview citations with full text, panel management that edits `monitor.toml`, collection settings, runs and events. Token authentication when bound beyond loopback, CSRF header on every mutation, CSP and other hardening headers.
- Shared renderer (`render.js`) between the static report and the app; the static export now includes engine, AI Overview citation, and baseline-start details.
- Engines: `google_light`, `bing`, `google_news`, `youtube`, and `google_shopping` panels normalize to the same ranked-row schema; per-engine parameter validation; only the first ten rows are kept and the overflow is recorded.
- AI Overview expansion (`ai_overview = "expand"`, default): deferred Overviews are fetched through `google_ai_overview`, their text and resolved references are stored in a new table (schema 3), and each capture records cited hosts and whether the monitored page or host was cited. `link=resolved` is sent on Google requests without touching panel identities. Citation history per panel.
- Intent rules are language packs: `serp_drift/rules/<lang>.toml` built in, `rules/<lang>.toml` in a workspace to add or extend a language. `serp-drift rules` shows the loaded packs. Built-in packs keep the `rules-en-fi-v2` identity; workspace packs add a fingerprint so panels re-baseline deliberately.

## 0.2.0 · 2026-09-16 · first live run

- First authenticated SearchApi acceptance run (steps 1–4): one credit per Google search, eight organic results, repeat collection skipped without a request.
- Fix: an `ai_overview` object carrying only Google's "not available" message was counted as an observed AI Overview. It is now recorded as `not_available`, and error-only objects never count as feature content.
- Intent rules `rules-en-fi-v2`: technical informational titles, Finnish word stems, snippet evidence at two points, URL slug words and site-section paths as evidence, `best practices` and `in order to` no longer misfire, code hosts typed as `repository`. Panels started under v1 get a new baseline.
- SearchApi tracking link and logo in the README and report footer; live observations documented in `docs/searchapi.md`.
- CLI catches SQLite errors; the User-Agent follows the package version.

## 0.1.0 · 2026-09-05 · acceptance candidate

- SearchApi Google capture and account usage commands.
- Explicit locale/device panel identities and immutable SQLite snapshots.
- Fixed baselines, interval sampling, confirmation, collection-health states, and auditable change components.
- English/Finnish intent proxies and declared, exported, or fetched page profiles.
- Self-contained desktop/mobile HTML report with query filtering, evidence, and JSON/CSV export.
- Twenty-four synthetic fixtures spanning four distinct scenarios.
- Offline behavioral tests, CI workflow, timer wrapper, source archive, and static Astro handoff bundle.

Live API acceptance, operator review, public repository creation, and publication remain pending.

