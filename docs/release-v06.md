# 0.6.0 release notes, upgrade and verification

A beta release candidate built from real use. It is not an accuracy-certified or accessibility-certified release. The version is prepared in the repository; no tag has been pushed and nothing is published to PyPI.

## What changed and why

Running 54 live panels for a week showed that about one Google capture in four, from 17 September 2026 on, returned organic results for a single word of the query while the provider echoed the full query (see [SearchApi notes](searchapi.md#observed-from-17-september-2026-results-for-one-query-word)). drift-v3 treated those captures as real SERP changes: most `watch` states in both live workspaces came from them. 0.6.0 therefore:

- flags such captures (`query_mismatch`) in the analysis view and never uses them as samples, while keeping the observation and letting a reviewer override the flag;
- takes status, positions and staleness from the newest valid capture and says how many newer captures were not used;
- can retry a rejected response after a pause without spending an AI Overview expansion (`retry_query_mismatch`);
- bounds a workspace with `max_total_requests` and `collect_until`, and shows an ended workspace as final rather than overdue;
- exports a small deterministic human-review sample (`benchmark export --sample-results N --latest-windows`).

Effect on the two existing workspaces (reanalysis of the same observations, 22 September 2026): nikoalho.fi went from 16 stable / 24 watch to 31 stable / 3 watch / 4 stale / 2 building; the Ahrefs example from 10 stable / 4 watch to 12 stable / 2 baseline ready (4 of 8 captures of two panels were rejected, so their baselines completed later). No panel changed identity; intent rules stay `rules-en-fi-v2`; storage stays schema 6; synthetic demo outcomes are unchanged.

## Upgrade

No migration is needed from 0.5.0. Back up anyway (`serp-drift backup --out …`), stop the collector, install the new source or wheel, and restart. The first report after the restart recomputes every panel with drift-v4; `reanalyze` records it in `analysis_runs` without API calls. New settings default to off (`max_total_requests = 0`, `retry_query_mismatch = 0`, `collect_until = ""`), so existing workspaces keep their request volume.

Rollback: stop the collector, reinstall 0.5.0 and restart. The database needs no change; 0.5.0 will again show rejected captures as ordinary captures.

## Verification record

Filled in on 23 September 2026 (UTC) for commit `78d1544` and the documentation commit that follows it:

- 127 automated tests pass on Python 3.14 locally; the GitHub Check workflow runs 3.11–3.14 (link in the handoff).
- ruff 0.16.7 passes; JavaScript assets parse.
- Browser walkthrough on copies of the three live workspaces, without a scheduler: portfolio, study dashboard, panel overview, history, compare, data quality, review, AI Overview and panel settings at 1440×900 and 390×844 in light and dark themes. Fixed during the walkthrough: first-score dates a day early for 12-hour intervals, narrow-screen horizontal overflow on four views, row markers against the last baseline capture instead of the whole baseline, rejected captures labelled "sparse" in history, verbose stale reasons. No console errors.
- Package build, archive inspection and clean install: see the handoff for the exact commands and results.
- Live: the collector on the operator's Mac runs this code for three workspaces; the prospective study collected its first 23 panels at 22:30Z on 22 September with 12 query-check retries and 40 requests.

## Known limits

- The query-term check is lexical and fitted to one week of data from one market. It abstains for single-term queries and for panels whose results rarely contain their own query words; it cannot tell a genuine topic change that drops a query word from a collection fault without human review.
- The cause of the one-word results is unknown. Retries 30–80 seconds later usually, not always, return the full query's results.
- Decisions can be recorded only for confirmed changes (`review`); a `watch` panel shows its evidence but no decision form.
- Human-reviewed intent accuracy is still unmeasured. A 150-result, 54-window annotation sample is exported privately and awaits reviewers.
