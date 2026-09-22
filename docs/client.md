# The SearchApi client, on its own

`serp_drift/client.py` is a hundred lines of standard-library Python that you can copy into any project. It falls back to a standalone version string when imported outside the package.

```python
from client import SearchApi, ApiError

settings = {"max_requests_per_run": 50, "request_delay_seconds": 1, "timeout_seconds": 45, "max_retries": 2}
api = SearchApi(os.environ["SEARCHAPI_API_KEY"], settings)
page = api.search({"engine": "google", "q": "serp analysis python", "gl": "us", "hl": "en", "link": "resolved"})
overview = api.ai_overview(page["ai_overview"]["page_token"]) if page.get("ai_overview", {}).get("page_token") else page.get("ai_overview")
places = api.locations("Turku")
print(api.account()["account"]["remaining_credits"])
```

What it does for you:

- **Key safety.** The key travels only in `Authorization: Bearer`, never in a URL, error message, or log line. Redirects are refused, so the header cannot leak to another host.
- **Bounded retries.** HTTP 408, 429, 500, 502, 503, 504 and network errors retry with exponential backoff, honouring `Retry-After` in seconds or as an HTTP date. A requested wait over sixty seconds raises `rate_limited` so a scheduler can come back later. Authentication and credit errors never retry.
- **A per-run budget.** `max_requests_per_run` counts every attempt including retries; hitting it raises `budget_exhausted`. Combine it with `request_delay_seconds` to stay inside your account's hourly limit.
- **Fail-closed parsing.** Bodies over 10 MB, invalid JSON, provider error payloads, and unfinished searches raise `ApiError` with a short code (`http_401`, `provider_error`, `invalid_json`, …) you can branch on.
- **Three endpoints.** `search(params)` for any engine, `ai_overview(page_token)` for deferred Overviews through `engine=google_ai_overview`, `locations(q)` for canonical location strings, and `account()` for credits and hourly usage.

## Estimating credits

Observed in the first live runs of this project: one credit per search on every engine tried, one credit per AI Overview expansion, no credit for `link=resolved` or for the Locations API. So a panel of *P* Google queries collected once a day costs about *P × (1 + share of captures that return an Overview token)* credits per day. `serp-drift estimate --days 30` prints the scheduled requests, the maximum number of expansions, and the ceiling with retries for your own configuration. Treat it as arithmetic over your settings, not as a quote; SearchApi's pricing page and your account dashboard are authoritative.
