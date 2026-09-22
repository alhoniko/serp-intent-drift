# Roadmap

The monitor started as a collector plus a static report. It is becoming a small self-hosted app that keeps
history, compares periods, and runs unattended on a laptop, a server, or a scheduled GitHub Action, while
staying dependency-free. Items are ordered; each lands as one verified commit.

## 1. App foundation
- [x] Workspace directory with config, database, reports, key file, and logs; `init`, `run`, `key`
- [x] Schema v2: indexed result rows, run records, raw-response retention window
- [x] History: full capture timeline, URL trajectories, entered/exited log
- [x] Compare tool: any capture or period against any other, same five components
- [x] Re-anchor a baseline from a chosen date without losing history
- [x] `serve` becomes the app: scheduler thread, JSON API, dashboard, panel, history, compare, manage, settings
- [x] Notifications: one webhook on status change; weekly digest (Markdown + SVG card)
- [x] `schedule`: launchd, systemd, and cron generation with `--install`; Dockerfile and compose

## 1b. Projects and import (done 16 Sept)
- [x] Several projects behind one server, portfolio view, project creation from the app
- [x] Site detection: ranking URL, ranking-URL change, site citations without declared pages
- [x] Search Console CSV import wizard with candidates, filters, credit estimate, bulk create
- [x] Calm UI from the design canvas: sidebar, attention list, panel table, panel page states, matrix, compare, reader
- [ ] Ahrefs and DataForSEO import adapters
- [ ] Weekly digest mirroring the attention list; per-project quiet hours

## 2. SearchApi showcase
- [x] AI Overview expansion through the dedicated engine; citations stored and tracked over time
- [x] Insights across panels: AI Overview prevalence, daily top-10 turnover, feature volatility, intent stability
- [x] Dataset export for research and the 30-day benchmark
- [x] Multi-engine panels with one schema: Google Light, Bing, YouTube, Google News, Google Shopping
- [x] Location panels in the UI with Locations API lookup
- [x] Language packs: intent rules as TOML files, user packs in the workspace
- [x] The SearchApi client documented as a reusable module with a credit estimator

## 3. Distribution and community
- [x] GitHub Actions template: fork, add the key as a secret, collect on a schedule, publish to Pages
- [x] Release workflow: wheel on tag, PyPI trusted publishing
- [x] MCP server for querying history from an agent
- [x] Optional OpenAI-compatible labeling behind a flag, cached, off by default
- [x] README quickstart with screenshots, ARCHITECTURE, CONTRIBUTING, SECURITY, issue templates, lint

## 4. Evidence and decision workflow (0.5.0)
- [x] Provenance, quarantine, reversible exclusions and analysis audit records
- [x] Whole-baseline comparisons and repeated recovery
- [x] Query-aware model labels, content format/task evidence and explicit abstentions
- [x] Review decisions, rationale, follow-up dates and episode-aware notification deduplication
- [x] Guided setup, quality views, keyword groups, saved filters and native keyboard controls
- [x] Consistent backup, offline reanalysis and blind annotation export/scoring
- [ ] Independent human benchmark with precision, recall, delay and language breakdown
- [ ] Full WCAG 2.2 AA audit with assistive-technology testing

## Next
- Publish the first real dataset after thirty days of collection and write the benchmark piece on it
- Language packs beyond English and Finnish (Swedish, German, Spanish are the obvious first three)
- A Windows-friendly collector lock and Task Scheduler entry
- More engines that fit the ranked-row schema (Google Maps, Google Jobs, Bing News)
- Per-panel notification overrides and a quiet-hours window

Out of scope on purpose: a hosted SaaS, a JavaScript build step, and runtime dependencies.
