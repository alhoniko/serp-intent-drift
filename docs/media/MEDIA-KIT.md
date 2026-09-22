# Media kit

**Version note:** these screenshots show 0.4.0. Capture fresh 0.5.0 evidence/review screens before publication; current facts and limits are in [the release notes](../release-v05.md).

Everything here may be reused when writing about serp-drift. Screenshots are 1440×1000 PNGs of the app on the example workspace from `examples/seo-blog-panel.toml` (fourteen SEO queries, ahrefs.com pages as the monitored page); no private data is shown.

**One line.** serp-drift is an open-source monitor that tells you when a search results page changes enough to deserve a content review, with the working shown.

**One paragraph.** serp-drift collects Google, Bing, YouTube, News, and Shopping results through SearchApi, keeps every capture in a local SQLite file, and scores change against a fixed baseline across five visible components: URL turnover, ranking moves, result types, SERP features, and estimated intent. It expands AI Overviews and resolves their citations, so you see which hosts Google cites and whether your page is among them. A small dependency-free app shows history, URL trajectories, period comparisons, and cross-panel insights; a webhook and a digest keep you informed; an MCP server lets an agent ask the same questions. Standard-library Python; runs on a laptop, a server, Docker, or GitHub Actions.

**Numbers from the first live run (16 September 2026, 40 panels).** AI Overview present in 73 % of captures overall, 83 % of English captures, 0 % of Finnish ones. People also ask in 95 %, ads in 35 %. Lexical rules classified a decisive intent for 19 of 40 panels. One credit per search, one per AI Overview expansion, none for link resolution or the Locations API.

**Files.** `portfolio.png`, `dashboard.png`, `dashboard-dark.png`, `panels.png`, `panel-overview.png`, `panel-history.png`, `panel-compare.png`, `panel-ai-overview.png`, `panel-settings.png`, `settings.png`, `import.png`, `insights.png`, `connect.png`, `digest-sample.svg`. All at 1440×1000 in the light theme unless named otherwise. Screenshots that show a workspace path (`settings.png`, `connect.png`) are captured from the Docker image with the example workspace mounted at `/home/you/serp-drift`, so no local paths appear in the repository. SearchApi logos are in `../assets/` and must be used unmodified.

**Links.** Repository: https://github.com/alhoniko/serp-intent-drift · Author: https://nikoalho.fi/ · SearchApi: https://www.searchapi.io/?utm_source=dev&utm_medium=ambassador&utm_campaign=nikoalho.fi

**Disclosure.** Developed for a paid collaboration with SearchApi. SearchApi provides the search data; the monitor's methodology and limitations are documented in this repository.
