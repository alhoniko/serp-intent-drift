# SearchApi integration notes

Documentation reviewed on 5 September 2026 using SearchApi's primary documentation and its Context7 index. The first authenticated requests were made on 16 September 2026; the observations are recorded at the end of this note.

## Implemented endpoints

| Endpoint | Purpose | Notes |
| --- | --- | --- |
| `GET https://www.searchapi.io/api/v1/search?engine=google` | Recurring Google SERP captures | `q`, `gl`, `hl`, `device`, optional `location`, `page=1`, `link=resolved` |
| `GET …/search?engine=google_ai_overview&page_token=…` | Expand a deferred AI Overview | One extra request per capture that returned a token |
| `GET …/search?engine=google_light\|bing\|google_news\|youtube\|google_shopping` | Alternative panels with one schema | See the engine table |
| `GET https://www.searchapi.io/api/v1/me` | Operator-requested account check | Remaining credits and hourly usage/limits |

### Engines

Every engine is normalized to the same ranked-row schema (`position`, `url`, `title`, `snippet`, intent, type), so a Bing panel and a Google panel of the same query can be compared with the same five components. Only the first ten ranked rows are kept; engines that return more (YouTube, Shopping) record how many were returned beyond the top ten.

| Engine | Ranked rows | Parameters | AI Overview | Result type |
| --- | --- | --- | --- | --- |
| `google` | `organic_results` | gl, hl, device, location | expanded through `google_ai_overview` | from rules |
| `google_light` | `organic_results` | gl, hl, device, location | no | from rules |
| `bing` | `organic_results` | gl, hl, device | observed when present | from rules |
| `google_news` | `organic_results` | gl, hl, location | no | `news` |
| `youtube` | `videos` (`shorts` counted as short videos) | gl, hl | no | `video` |
| `google_shopping` | `shopping_results` (`product_link`; price, seller, condition form the snippet) | gl, hl, location | no | `product` |

### AI Overview expansion

Google usually defers the Overview behind a `page_token`. With `ai_overview = "expand"` (the default), the collector spends one more request on `engine=google_ai_overview` and stores the text blocks, the Markdown, and the reference links in their own table. `link = "resolved"` is sent on Google requests so reference links are real URLs instead of encrypted `google.com/goto` redirects; it is a request parameter only and never part of a panel identity. The normalized record keeps a summary: number of references, cited hosts and URLs, whether the monitored page or its host was cited, and the first paragraph as an excerpt. Set `ai_overview = "skip"` to save the extra credit.

Authentication uses `Authorization: Bearer SEARCHAPI_API_KEY`. API keys are not placed in query parameters. The client does not follow HTTP redirects.

The [Google Search API](https://www.searchapi.io/docs/google) documents `num` as fixed at ten following Google's September 2025 change. This implementation omits `num` and stays on the first page. It does not claim full top-100 rank tracking. [Google Rank Tracking](https://www.searchapi.io/docs/google-rank-tracking-api) is a separate engine and is outside this release.

The normalizer reads `organic_results[].position`, `title`, `link`, and `snippet`, plus the feature keys listed in the methodology. It treats encrypted unresolved Google redirects as unusable organic destinations rather than identities for comparison. SearchApi documents optional `link=resolved`; v0.1 does not enable that additional behavior.

Google response feature presence varies by query. Overview content, an answer box, videos, and related questions are separate observations. Overview follow-up tokens are retained only as a normalized status; the token itself is discarded from the stored response subset.

Use [Locations API](https://www.searchapi.io/docs/locations-api) canonical strings when pinning a location. Keep the exact setting stable across captures. `gl` is country targeting; `hl` is interface language. Neither guarantees every returned document is in that language.

The [Account API](https://www.searchapi.io/docs/account-api) documents `account.remaining_credits`, `account.current_month_usage`, `account.monthly_allowance`, `api_usage.searches_this_hour`, and `api_usage.hourly_rate_limit`. Account-specific numbers must be read after access is activated. The collaboration's credit allocation is not a public API rate-limit guarantee.

## Failure handling choices

The following are application decisions, not promises about SearchApi's service:

- Retry HTTP 408, 429, 500, 502, 503, 504 and network failures, default twice.
- Respect numeric or HTTP-date `Retry-After`; exit for delays over 60 seconds instead of retrying early.
- Fail closed on error JSON, unfinished provider status, malformed/missing organic arrays, invalid JSON, and payloads over 10 MB.
- Preserve HTTP error codes without echoing provider error bodies or request URLs into logs.
- Stop the remaining panel on authentication, credit, rate-limit, or local budget exhaustion.
- Successful responses with empty/sparse organic arrays remain auditable but cannot trigger alerts.
- Do not claim uncached behavior, fixed provider latency, credit cost per failed request, or a particular rate limit without the account's actual terms.


## Observed in the first live run (16 September 2026)

One `engine=google` panel, US/English/desktop, query `serp analysis python`:

- One Google search consumed one credit (`remaining_credits` 100000 → 99999). `/me` returned `account.current_month_usage`, `account.monthly_allowance` (0 on a credit-based account), `account.remaining_credits`, `api_usage.searches_this_hour`, and `api_usage.hourly_rate_limit`.
- `organic_results` held eight items with positions 1–8. Each item carried `position`, `title`, `link`, `snippet`, `date`, `displayed_link`, `domain`, `source`, and `snippet_highlighted_words`. Fewer than ten organic results on page 1 is normal when other modules are shown.
- `ai_overview` was `{"error": "An AI Overview is not available for this search"}`. The normalizer records this as `not_available`, not as an observed Overview.
- `related_questions` items carried `question`, `is_ai_overview: true`, and an `error` explaining that Google loads the answer asynchronously. The questions themselves remain usable evidence for the feature.
- `inline_videos` items carried `position`, `title`, `link`, `source`, `channel`, `length`, and `key_moments`.
- A second `collect` inside the interval spent no request and reported `skipped=1`.
- Later the same day: `link=resolved` returned real reference URLs (`business.com`, `g2.com`, `youtube.com`) instead of `google.com/goto` redirects, at no extra credit. Expanding a deferred Overview through `google_ai_overview` cost exactly one credit and returned four text blocks and eight resolved references.
- Engine probes (one request each): `google_light` returns `organic_results` with position, title, link, displayed_link, snippet, date; `bing` returns the same fields plus `domain`, `inline_videos`, and sometimes `ai_overview`; `google_news` returns `organic_results` with source and iso_date; `youtube` returns `videos` (19 items with `channel` and `key_moments`) and `shorts`; `google_shopping` returns 40 `shopping_results` with `product_link`, `price`, `extracted_price`, `rating`, `reviews`, `seller`.

## Observed from 17 September 2026: results for one query word

Between 17 and 22 September 2026, 25–35% of each day's applicable captures in two workspaces (87 of 348 Google desktop, 3 of 29 Google mobile, 0 of 8 Bing) returned organic results that matched only one word of the query. `search_parameters.q` echoed the full requested query, and no `search_information` correction was present. Examples: `content decay` returned general "content" pages, `domain rating` returned chess and film "ratings", `link building` returned "Link" payment and app pages. In several such responses the AI Overview still discussed the requested topic. On 16 September, 0 of 73 captures showed the pattern.

In a 22 September pilot, 6 of 22 first responses were affected. An immediate retry fixed 3; the others needed a retry 80 seconds or more later, one of them twice. In the first study round, 8 of 23 first responses were affected; retries after 30-second pauses fixed 6 and left 2 (`rank tracker`, `link building`) affected after two retries. During the first study run the same query sometimes returned an identical one-word result set for about 70 seconds across requests with different request IDs. SearchApi's documentation lists no cache-control parameter, so this tool cannot tell whether a cache, a proxy or Google causes the pattern. The collector's query-term check and optional retry treat it as a failed collection (see the methodology). Request IDs of affected captures are kept in each observation trace for a provider report.
