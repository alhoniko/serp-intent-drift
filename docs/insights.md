# Insights and the dataset

`serp-drift insights` and the Insights page summarise every stored capture across panels. Everything is descriptive: shares, means, and medians over what SearchApi returned, never a model of Google or a traffic estimate.

Per panel: captures, AI Overview share, how often your page was cited, mean top-10 turnover between consecutive captures (Jaccard distance), mean rank movement of URLs that stayed, feature volatility, the modal dominant intent and how stable it was, mean classified coverage, and your page's latest and best position.

Across panels: AI Overview and feature prevalence, dominant-intent counts, median coverage, the most cited hosts with the number of panels they appear in, the most volatile and most stable panels, and the same summary split by language, device, and engine. `--days N` limits everything to the last N days.

## Dataset

`serp-drift export` writes a directory (or `--zip` one archive) with:

- `captures.csv`: one row per capture with market, result count, dominant intent, coverage, features, AI Overview status and cited hosts, your page's position and whether it was cited.
- `results.csv`: one row per ranked result with URL, host, title, rule-based intent and type, and the rule confidence share.
- `citations.csv`: one row per URL an expanded AI Overview cited.
- `panels.json`, `insights.json`, and a README stating the rule version.

The app serves the same at `/api/export/dataset.zip` and `/api/insights`. Titles and snippets belong to their publishers; the dataset is for your own analysis, and publishing it is your call.
