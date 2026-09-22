# Methodology · drift-v4 / rules-en-fi-v2

This monitor measures changes in **observed search results**. Dominant intent is an estimate from visible text, not an observation of the searcher's mind. The system prioritizes human review; it never rewrites a page automatically.

## Comparable observations

A panel is identified by the exact query, engine, page, country (`gl`), interface language (`hl`), device, optional location, and analysis version. The panel hash segregates SQLite history. Synthetic and SearchApi observations are stored/read separately. No cross-device, cross-locale, or synthetic/live comparisons occur.

Only the first result page is collected. Supported engines are listed in `engines.py`; Google, Bing, News, Shopping and YouTube use the same normalized panel schema. Organic positions must be integers from 1 through 10. Duplicated URLs, duplicated positions, invalid links, and unresolved `google.com/goto` redirects are discarded with warnings. Failed/malformed provider responses are attempts, never snapshots. Successful but sparse responses remain visible; fewer than the configured minimum (default five) cannot trigger alerts.

URL normalization lowercases the hostname, removes a leading `www.`, removes fragments and common ad/tracking parameters, and sorts retained query parameters. It preserves HTTP versus HTTPS, case-sensitive paths, trailing slashes, and meaningful parameters such as product IDs or YouTube `v`. This is a documented heuristic, not canonical-tag discovery.

## Intent and result type

Each result is evaluated against explicit English/Finnish lexical rules in `serp_drift/intent.py`.

| Intent | Example evidence |
| --- | --- |
| Informational | what is, how to, why, guide, tutorial, explained, step by step, examples, using, scripts, automating, checklist, template, opas/oppaan, ohje/ohjeet, miten, kuinka, vinkit, esimerkki |
| Commercial investigation | best (not "best practices"), top N, compare/comparison, review, rated, vs, alternatives, parhaat, vertailu, kokemuksia, arvostelu |
| Transactional | pricing, price, buy, shop, order now/online, book a demo, free trial, sign up, discount, coupon, hinta/hinnat/hinnasto, osta, tilaa/tilaus, tarjous, alennus, verkkokauppa |
| Navigational | login, sign in, official site, kirjaudu, omat sivut |

Finnish rules match word stems so inflected forms such as *oppaan*, *ohjeet*, or *hinnat* count. A rule matched in a title contributes three points; the same rule in a snippet contributes two; a rule matched in the words of the URL path contributes two. A leading site-section path adds two more points: `/blog/`, `/docs/`, `/help-center/`, `/learn/` and similar count as informational, `/pricing/`, `/shop/`, `/products/` as transactional, and `/login/` as navigational. A title match therefore decides on its own, while snippet or URL evidence needs a second agreeing hit. A decisive category needs at least three points and a margin of two over the runner-up. Otherwise the result remains `unknown`. The per-result `confidence` field is the winning share of lexical points, **not calibrated accuracy**. It is not used as a probability or multiplied into the drift score.

Result types use recognizable video, code-repository, and forum hosts plus documentation URL paths, then intent-derived labels: guide, comparison, product, navigation, or unknown. They describe a proxy for content format. The classifier does not crawl competitor pages, interpret structured data, detect local pack intent, or semantically understand the topic. For languages other than English/Finnish, both lexical intent and result type remain unknown in this version.

## Dominant intent

Organic rank `r` has weight `w(r) = 1 / log2(r + 1)`. The intent distribution sums each category's weights and divides by the sum for **all** usable results, including unknowns. The result-type distribution uses the same weighting.

A dominant intent needs:

1. At least 60% of total rank weight classified.
2. At least 55% of total rank weight assigned to the leading intent.
3. A lead of at least 15 percentage points over the next known intent.

Insufficient classified coverage produces `unknown`; competing known intents produce `mixed`. These are engineering thresholds chosen for a conservative first release. No labeled SERP benchmark has established their precision or recall yet.

## Fixed baseline and confirmation

The first three eligible, interval-spaced captures form the default baseline. The whole baseline is the comparison side: intent and result-type distributions are averaged over its captures, URL and feature membership is the fraction of baseline captures that contained each item, and ranks are each URL's mean position across the baseline (see the table below). No single baseline capture anchors the comparison. The baseline never rolls forward automatically.

The interval sampler retains the first valid capture, then the next valid one after the configured interval. A tolerance of the smaller of 60 seconds or 1% of that interval accommodates timer/HTTP timing jitter; this same tolerance is used for collection due checks. Forced captures remain in storage and can be displayed as the latest observation, but cannot fabricate repeated evidence. If the displayed latest capture is not an eligible interval sample, confirmation is suppressed.

Captures that do not describe this panel are not samples: a provider-context quarantine, a human exclusion, or a query-term mismatch (next section). They stay in storage and in the timeline, but they neither count toward the baseline nor occupy an interval slot, so a valid capture taken shortly afterwards can fill it. Sparse captures are real observations of this panel and still occupy their slot.

After the baseline, two consecutive spaced captures must agree for a review alert. Sparse captures interrupt the sequence. A gap larger than 1.75 collection intervals breaks consecutive confirmation. Default first possible confirmation therefore needs five eligible captures in total.

## Query-term check (new in drift-v4)

Live collection in September 2026 showed Google captures whose organic results matched only one word of a multi-word query while the provider reported the requested query unchanged: `seo reporting tools` returned sustainability and football "reporting" pages, `domain rating` returned chess and film "ratings", `rank tracker` returned TV-series and baby "trackers". The AI Overview in the same response was usually on topic. Such a capture is a failed collection, not a SERP change.

For every capture of a query with at least two terms (stopwords removed), the check computes the rank-weighted share of organic results whose title, snippet or URL words contain every query term (terms of five or more letters match on a stem). The panel's reference is the best share any of its captures reached. A capture is flagged `query_mismatch` when the reference is at least 0.35 and the capture's share is at most 0.20 and at most 40% of the reference. Single-term queries and panels whose results rarely contain their own query terms abstain. The thresholds are engineering choices fitted to the bimodal pattern in 400 September captures (normal captures 0.35–1.00, affected ones 0.00–0.17); they are not a validated classifier.

The flag is an analysis overlay: the stored observation is unchanged, the reason is shown in the data-quality view, and a reviewer can keep a flagged capture with a written reason. Because the reference can rise later, a panel's first capture can become flagged retroactively once a matching capture exists.

Optional collection behavior: with `retry_query_mismatch = 1` or `2`, a response that fails the check (or, before the panel has a reference, one whose share is at most 0.10) is stored as an observation without an AI Overview expansion, and after a 30-second pause the search is repeated. Every request counts toward the run and workspace budgets. The replacement is the capture of record for that slot; the rejected one is never a sample.

## Status from the newest valid capture

When the newest captures were rejected by the query check, the status is computed from the newest capture that describes the panel, and the reasons state how many newer captures were not used. Staleness is measured from that valid capture: if no valid capture exists within 1.75 intervals, the panel is `stale` with an explanation. Only when every capture is invalid, or the newest is quarantined/excluded, does the panel show `data_quality`. Site and page positions always come from a valid capture. URL trajectories, the change log, citation history and intent stability use valid captures only.

## Bounded collection

`max_total_requests` caps every SearchApi request a workspace records (searches, retries, AI Overview expansions). `collect_until` ends collection at a UTC time. When either is reached the scheduler stops, `run` collects nothing, the dashboard shows one "Collection ended" notice, and panels keep their final observations instead of reporting themselves overdue.

## Comparing periods and re-anchoring

Any two capture sets can be compared with the same five components. Each side is a preset (`baseline`, `latest`, `last_7_days`, `previous_7_days`, `last_30_days`, `first_week`), one capture, or a closed date range. Intent and result-type distributions are averaged per side; URL and feature memberships are the fraction of eligible captures containing each item, compared using weighted Jaccard distance. Ranks use each URL's mean observed position across its period. Baseline-versus-latest is the special case where the right side has one capture, so a period comparison never uses different arithmetic from the alert path.

A panel can be re-anchored from a chosen date. Captures before that date remain in history and in period comparisons, but the alert analysis, the baseline, and confirmation start from the chosen date. This is how a deliberate content change or a known Google update becomes a new starting point without deleting evidence.

URL trajectories list every URL ever observed in a panel with its position per capture. The change log records, between consecutive captures, which URLs entered or exited the top ten, which moved, which features appeared or disappeared, and whether the dominant intent or the monitored page's position changed.

## Five visible change components

| Component | Formula | Weight |
| --- | --- | ---: |
| Intent distribution | Total variation distance: `0.5 × Σ abs(p_i − q_i)` | 0.35 |
| Organic URL turnover | Frequency-weighted Jaccard: `1 − Σ min(p_i,q_i) / Σ max(p_i,q_i)` | 0.25 |
| Result-type distribution | Total variation distance | 0.20 |
| Ranking movement | Mean `abs(old_rank − new_rank) / 9` over shared URLs | 0.10 |
| Observed SERP features | Frequency-weighted Jaccard between feature memberships | 0.10 |

The score is `100 × Σ(weight × component)`, rounded to one decimal. It is a prioritization index. Intent and result type are correlated in this heuristic, so this is not five independent signals and cannot be interpreted statistically.

When fewer than two URLs are shared, ranking movement is `null` and contributes zero. The missing weight is not redistributed; turnover already describes the changed result set. Two empty feature sets have zero distance. Any disappearance is worded as **no longer observed**, not proof that Google universally removed that feature.

Tracked feature keys: `ai_overview`, `answer_box`, `related_questions`, `knowledge_graph`, `local_results`, `inline_videos`, `inline_shorts`, `inline_images`, `inline_shopping`, `top_stories`, `ads`, and `discussions_and_forums` when present in a response. A token-only Overview is marked `requires_followup`. An `ai_overview` object that only carries Google's message that no Overview is available is marked `not_available`; neither state counts as an observed feature. An Overview expansion request is made when enabled and the first response returns a deferred token, within the run budget.

## AI Overview citations

When a capture contains an AI Overview, the normalized record stores which URLs and hosts it cited, whether the monitored page or its host was among them, the number of references, and the first paragraph as an excerpt. The full text and reference list are kept in a separate table. A cited host is an observation about one capture; the citation history counts how many captures cited each host, which is a descriptive frequency and not a share-of-voice metric. Unresolved `google.com/goto` links are counted but never treated as hosts.

## Page-fit alert

A page can have a declared intent, a local content export, or an optional fresh public HTML fetch. The report records which basis was used. Explicit intent overrides the inferred text classification. Full page bodies are discarded from the public report; a SHA-256 text fingerprint enables comparison of supplied content versions.

A mismatch candidate requires a definite latest SERP intent that differs from the page intent, while the page's intent receives less than 25% of total result weight. Confirmation compares the latest page profile with the two most recent eligible SERPs. The next capture uses the updated page profile; earlier observations keep their original profile. Matching the latest profile to the observed SERP clears that mismatch; a separate historical intent-shift signal can remain.

`review` means a confirmed page mismatch and/or a confirmed dominant-intent shift. Either can trigger a review independently of the score. `watch` means an unconfirmed candidate or score >=35 by default. Everything else with enough data is `stable`.

Low quality, a collection failure newer than the displayed successful snapshot, or a snapshot older than 1.75 intervals suppresses current confirmation and shows a collection-health state. Synthetic fixtures are exempt from wall-clock staleness so the demo remains usable; real runs are not.

## Quality and classification evidence

New observations retain an allowlisted provenance trace: requested and returned query, engine, country, language, device, location, page, request ID and provider timestamp. Credentials and request URLs are excluded. A returned context mismatch or substituted query quarantines the capture. Missing provenance remains unverified; legacy metadata is not reconstructed or invented. Title-vocabulary changes are inspection hints, never automatic exclusions; the query-term check above is automatic but is an overlay a reviewer can override.

An exclusion requires a written reason and overlays the analysis view. Restoring removes that overlay; it cannot override a provider-context quarantine. Original observations stay unchanged, and every exclusion/restore produces an audit event.

Optional semantic labels include query context, independent content format, task description and an excerpt that must occur in the supplied evidence. Full-review mode retains the original rule label and displays disagreements; abstention remains unknown. Invalid or incomplete model responses suppress confirmation and are not cached as successful unknown results. All confirmation captures must use the same classifier version.

The baseline's internal intent distance and a comparison against up to seven recent eligible captures are descriptive context, not statistical confidence. Confirmed intent change additionally requires at least 0.20 total variation distance, a known baseline intent and the same new dominant intent across spaced captures. A page mismatch also requires agreement on the new dominant intent. A high composite score alone cannot confirm either.

## Review episodes

`new → investigating → decided → monitoring → closed` records work status independently from analytical status. Decisions need a rationale; an optional UTC calendar review date puts the case back in the attention queue when due. A new signal replaces the active episode. Recovery requires the configured number of spaced stable observations with adequate intent coverage; a failed collection, unknown intent or one quiet capture cannot resolve an episode. A closed decision remains attached to a continuing signal and does not re-alert every day. Failed webhook deliveries are retained for retry on a later run.

## Reproducible synthetic observations

Regenerate with `python3 scripts/generate-fixtures.py`, then `python3 -m serp_drift demo`.

| Fixture | Baseline → latest | Score | Interpretation |
| --- | --- | ---: | --- |
| CRM automation | Informational → commercial | 76.7 | Eight comparison URLs displace eight guides; repeated page-fit mismatch |
| Technical SEO audit | Informational → informational | 0.2 | Positions four and five swap; no intent change |
| AI research tools | Commercial → commercial | 35.0 | All URLs and tracked features change; watch, no intent shift |
| Search workflow templates | Informational → sparse capture | — | Two usable results; alert suppressed |

The fixture dates (24–29 August 2026), titles, snippets, features, and URLs are invented. These rows describe deterministic software behavior. They provide no evidence about the actual market for CRM automation, Google trends, classifier accuracy, traffic loss, or ranking recovery.

## Live query-mismatch rates (September 2026)

Across the two existing workspaces, 90 of 385 applicable captures (23%) failed the check: none of 73 on 16 September 2026, then 25–35% of each day's captures from 17 to 22 September (23–46% per workspace and day). By engine and device: 87 of 348 Google desktop, 3 of 29 Google mobile, 0 of 8 Bing. In the 22 September pilot, 6 of 22 first responses failed; an immediate retry fixed 3, and retries about 80 seconds later fixed the rest (one needed two). In the first study round (30-second pause, up to two retries), 8 of 23 first responses failed; the first retry fixed 4, the second 2, and 2 stayed affected. Before drift-v4, these captures produced most of the `watch` states in both workspaces. The cause is outside this tool; provider request IDs of affected captures are kept in the observation trace.

## Limits to validate with real data

The first live capture (16 September 2026, `serp analysis python`, US/English/desktop, eight organic results) showed why the rules needed a second version: `rules-en-fi-v1` classified 18% of rank weight and left the dominant intent unknown on a plainly informational page, because technical titles such as "SERP analysis using 3 Python scripts" matched nothing. `rules-en-fi-v2` classifies 73% of the same capture as informational. One known false positive remains: "Compare Keyword SERP Similarity in Bulk with Python" is scored commercial because of *compare*. Rule versions are not comparable across a baseline, which is why the analysis version is part of the panel identity.

Titles can be misleading, snippets can be rewritten, mixed intent is common, localized results vary, and features are not equally extractable. Missing results can distort both the observed composition and rank-weighted distributions even above the minimum threshold. No click/pixel/share-of-voice metrics or causal claims are supported. Live API compatibility, local page fetch behavior, scheduling, and human-reviewed intent accuracy still require acceptance testing.

