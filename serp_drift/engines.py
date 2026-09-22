"""SearchApi engine adapters: which parameters each engine accepts and where its ranked rows live."""

ENGINES = {
    "google": {"rows": "organic_results", "link": "link", "snippet": "snippet", "params": ("gl", "hl", "device", "location", "page"),
               "ai_overview": True, "resolve_links": True, "type": None, "aliases": {}, "label": "Google Search"},
    "google_light": {"rows": "organic_results", "link": "link", "snippet": "snippet", "params": ("gl", "hl", "device", "location", "page"),
                     "ai_overview": False, "resolve_links": False, "type": None, "aliases": {}, "label": "Google Light"},
    "bing": {"rows": "organic_results", "link": "link", "snippet": "snippet", "params": ("gl", "hl", "device", "page"),
             "ai_overview": True, "resolve_links": False, "type": None, "aliases": {}, "label": "Bing"},
    "google_news": {"rows": "organic_results", "link": "link", "snippet": "snippet", "params": ("gl", "hl", "location"),
                    "ai_overview": False, "resolve_links": False, "type": "news", "aliases": {}, "label": "Google News"},
    "youtube": {"rows": "videos", "link": "link", "snippet": "description", "params": ("gl", "hl"),
                "ai_overview": False, "resolve_links": False, "type": "video", "aliases": {"shorts": "inline_shorts"}, "label": "YouTube"},
    "google_shopping": {"rows": "shopping_results", "link": "product_link", "snippet": None, "params": ("gl", "hl", "location"),
                        "ai_overview": False, "resolve_links": False, "type": "product", "aliases": {}, "label": "Google Shopping"},
}
MAX_POSITION = 10


def spec(engine: str) -> dict:
    try:
        return ENGINES[engine]
    except KeyError:
        raise ValueError(f"Unsupported engine {engine!r}. Supported: {', '.join(ENGINES)}.") from None


def request_params(search: dict, *, resolve_links: bool = True) -> dict:
    """The exact query parameters sent for one panel. `link=resolved` is request-only and never part of the panel identity."""
    engine = search["engine"]
    details = spec(engine)
    params = {"engine": engine, "q": search["q"]}
    params |= {key: search[key] for key in details["params"] if key in search and search[key] not in (None, "")}
    if resolve_links and details["resolve_links"]:
        params["link"] = "resolved"
    return params


def rows(payload: dict, engine: str) -> list:
    value = payload.get(spec(engine)["rows"])
    if not isinstance(value, list):
        raise ValueError(f"{spec(engine)['rows']} is missing or is not an array.")
    return value


def row_fields(row: dict, engine: str) -> tuple[str, str, str]:
    """(link, title, snippet) for one ranked row, whatever the engine calls them."""
    details = spec(engine)
    link = row.get(details["link"], "")
    title = row.get("title", "")
    if details["snippet"]:
        snippet = row.get(details["snippet"], "")
    elif engine == "google_shopping":
        snippet = " · ".join(str(row[key]) for key in ("price", "seller", "condition") if row.get(key))
    else:
        snippet = ""
    return (link if isinstance(link, str) else "", title if isinstance(title, str) else "", snippet if isinstance(snippet, str) else "")


def feature_key(key: str, engine: str) -> str:
    return spec(engine)["aliases"].get(key, key)
