# Media kit

Screenshots of serp-drift **0.6.0**, captured on 22 September 2026 (UTC) from the author's local app with live workspace data. They are illustrative views as of that time, not live statistics. Every image is real data; none is synthetic. Per-image details (capture time, commit, view, case, caption, alt text, checksum) are in [`v0.6/manifest.json`](v0.6/manifest.json).

| Image | What it shows |
| --- | --- |
| [`00-cover`](v0.6/branded/00-cover.webp) (1200×630) | A watch panel's decision block and the four separate measures: SERP change, intent, page fit, data quality |
| [`01-portfolio`](v0.6/branded/01-portfolio.webp) | Three workspaces; four panels stale because their newest captures returned results for a different query |
| [`02-study-dashboard`](v0.6/branded/02-study-dashboard.webp) | The 23-panel ahrefs.com study after its first round: baselines building, 40 of 1,415 requests used |
| [`03-panel-watch`](v0.6/branded/03-panel-watch.webp) | `best crm software 2026`: change score 47, intent shift unconfirmed, two rejected captures marked |
| [`04-history`](v0.6/branded/04-history.webp) | The same panel's URL trajectories: a Reddit thread entered at #1, four listicles left |
| [`05-compare`](v0.6/branded/05-compare.webp) | Whole baseline (three captures, averaged) against the latest capture, component by component |
| [`06-ai-overview`](v0.6/branded/06-ai-overview.webp) | `canonical tags`: ahrefs.com cited in all 8 captured AI Overviews |
| [`07-review`](v0.6/branded/07-review.webp) | The review tab withholding a decision prompt when no change is confirmed |
| [`08-data-quality`](v0.6/branded/08-data-quality.webp) | `domain rating`: 4 of 8 captures returned results for a different query |
| [`09-example-dashboard-dark`](v0.6/branded/09-example-dashboard-dark.webp) | The Ahrefs example workspace in the dark theme |
| [`10-detail-data-quality`](v0.6/branded/10-detail-data-quality.webp) (1200×630) | Readable crop of 08 for article width |
| [`11-detail-history`](v0.6/branded/11-detail-history.webp) (1200×630) | Readable crop of 04 for article width |

**Formats.** In the repository: untouched originals (2880×1800 PNG, `v0.6/originals/`), branded web exports (1600×1000 WebP; cover 1200×630) and clickable HTML versions whose credits link to https://nikoalho.fi/ and https://github.com/alhoniko (`v0.6/branded/`). High-resolution masters (3200×2000 and 2400×1260 PNG) and 1600×1000 PNG exports are kept outside the repository by the author; regenerate them with the commands in [`compose/README.md`](compose/README.md).

**Evidence gap.** No real panel had a confirmed intent change or page-fit mismatch on the capture date, so the decision form of the review workflow is not shown with real data. Screenshot 07 shows what the workflow does instead.

**Rules.** The screenshots are genuine captures; they were cropped (cover only), scaled and framed, never retouched. Private data was avoided at capture time: no settings or connection pages (they show workspace paths), no credentials, no browser chrome.

**One line.** serp-drift is an open-source monitor that tells you when a search results page changes enough to deserve a content review, with the working shown.

**Links.** Repository: https://github.com/alhoniko/serp-intent-drift · Author: https://nikoalho.fi/ · SearchApi: https://www.searchapi.io/?utm_source=dev&utm_medium=ambassador&utm_campaign=nikoalho.fi

**Disclosure.** Developed for a paid collaboration with SearchApi. SearchApi provides the search data; the monitor's methodology and limitations are documented in this repository. SearchApi logos are in `../assets/` and must be used unmodified.

**Archive.** The 0.4.0 screenshots (1440×1000, example workspace) are in [`v0.4/`](v0.4/). They predate the evidence and review workflow and the query-term check.
