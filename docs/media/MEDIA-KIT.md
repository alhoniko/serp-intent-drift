# Media kit

Screenshots of the serp-drift **1.0** interface (the triage redesign; captured just before the version number changed, so the sidebar still reads 0.6), captured on 30 September 2026 (UTC) from the author's local app with live workspace data. They are illustrative views as of that time, not live statistics. Every image is real data; none is synthetic. Per-image details (capture time, commit, route, theme, case, caption, alt text, checksums) are in [`v0.7/manifest.json`](v0.7/manifest.json).

| Image | What it shows |
| --- | --- |
| [`00-cover`](v0.7/branded/00-cover.webp) (1200×630) | A watch panel's verdict and the four separate measures: SERP change, intent, page fit, data |
| [`01-portfolio`](v0.7/branded/01-portfolio.webp) | All projects: three workspaces, 77 panels, 28 on watch and none confirmed; the study workspace has ended collection |
| [`02-inbox`](v0.7/branded/02-inbox.webp) | The Ahrefs example Inbox: five watched panels, those touching your site first, next to a preview of `search intent` |
| [`03-panel-summary`](v0.7/branded/03-panel-summary.webp) | `link building`: watch at 36, all 8 latest results new since the baseline, ahrefs.com's page from #5 to #3, intent shift unconfirmed |
| [`04-history`](v0.7/branded/04-history.webp) | The same panel's score by capture and the positions of 24 URLs across 15 captures |
| [`05-compare`](v0.7/branded/05-compare.webp) | The baseline window (three captures, averaged) against the latest capture, component by component |
| [`06-ai-overview`](v0.7/branded/06-ai-overview.webp) | `canonical tags`: an AI Overview in 15 of 15 captures, citing ahrefs.com in 13 |
| [`07-evidence`](v0.7/branded/07-evidence.webp) | Evidence for `link building`: every capture kept, a query-relevance notice instead of an automatic exclusion |
| [`08-data-quality`](v0.7/branded/08-data-quality.webp) | `domain rating`: 4 of 15 captures returned results for another query and never count as evidence |
| [`09-study-panels`](v0.7/branded/09-study-panels.webp) | The 23-panel ahrefs.com study after collection ended, in the light theme: 10 watch, 13 stable, no confirmed change |
| [`10-detail-data-quality`](v0.7/branded/10-detail-data-quality.webp) (1200×630) | Readable crop of 08 for article width |
| [`11-detail-history`](v0.7/branded/11-detail-history.webp) (1200×630) | Readable crop of 04 for article width |

**Repository cover.** [`../assets/social-preview.png`](../assets/social-preview.png) (1280×640) is the README banner and the GitHub social preview: the mark, one line, the author credit and the unmodified SearchApi logo next to a real panel capture from the same session.

**Formats.** In the repository: untouched originals (2880×1800 PNG, `v0.7/originals/`), branded web exports (1600×1000 WebP; cover and details 1200×630) and clickable HTML versions whose credits link to https://nikoalho.fi/ and https://github.com/alhoniko (`v0.7/branded/`). Dark captures sit on the Ink background, the light one on Paper. High-resolution masters (3200×2000 and 2400×1260 PNG) and 1600×1000 PNG exports are kept outside the repository by the author; regenerate them with the commands in [`compose/README.md`](compose/README.md).

**Evidence gap.** No real panel had a confirmed intent change or page-fit mismatch on the capture date, so the decision form in Evidence is not shown with real data. Screenshot 07 shows what Evidence does instead.

**Study caveat.** The study panels in 01 and 09 include the study's last run (29 September 22:24–22:40 UTC), whose result sets are unconfirmed: ahrefs.com was missing from 11 of 23 panels and there is no later capture. Their `watch` status records volatility above the threshold, not intent drift.

**Rules.** The screenshots are genuine captures; they were cropped (cover and the two detail images only), scaled and framed, never retouched. Private data was avoided at capture time: no settings or connection pages (they show workspace paths), no credentials, no browser chrome.

**One line.** serp-drift is an open-source monitor that tells you when a search results page changes enough to deserve a content review, with the working shown.

**Links.** Repository: https://github.com/alhoniko/serp-intent-drift · Author: https://nikoalho.fi/ · SearchApi: https://www.searchapi.io/?utm_source=dev&utm_medium=ambassador&utm_campaign=nikoalho.fi

**Disclosure.** Developed for a paid collaboration with SearchApi. SearchApi provides the search data; the monitor's methodology and limitations are documented in this repository. SearchApi logos are in `../assets/` and must be used unmodified.

**Archive.** The 0.6.0 screenshots (22 September 2026, the interface before the redesign) are in [`v0.6/`](v0.6/) with their own [manifest](v0.6/manifest.json). The 0.4.0 screenshots (1440×1000, example workspace) are in [`v0.4/`](v0.4/). They predate the evidence and review workflow and the query-term check.
