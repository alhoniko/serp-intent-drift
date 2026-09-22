"""Normalize only observed Google response fields, retaining unknowns explicitly."""

import math
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from . import packs
from .engines import MAX_POSITION, feature_key, row_fields, rows, spec
from .intent import classify

FEATURES = {
    "ai_overview": "AI Overview", "answer_box": "Answer box", "related_questions": "People also ask",
    "knowledge_graph": "Knowledge graph", "local_results": "Local results", "inline_videos": "Videos",
    "inline_shorts": "Short videos", "inline_images": "Images", "inline_shopping": "Shopping",
    "top_stories": "Top stories", "ads": "Ads", "discussions_and_forums": "Discussions",
}


def canonical_url(url: str) -> str | None:
    if not isinstance(url, str) or any(ord(char) < 32 for char in url):
        return None
    try:
        parts = urlsplit(url)
        if parts.scheme.lower() not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
            return None
        host = parts.hostname.lower().encode("idna").decode("ascii")
        if host.startswith("www."):
            host = host[4:]
        port = parts.port
        if ":" in host:
            host = f"[{host}]"
        if port and port != {"http": 80, "https": 443}[parts.scheme.lower()]:
            host += f":{port}"
        pairs = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True)
                 if not key.lower().startswith("utm_") and key.lower() not in {"gclid", "fbclid", "msclkid"}]
        # Keep meaningful query parameters (including product IDs and YouTube v=).
        return urlunsplit((parts.scheme.lower(), host, parts.path or "/", urlencode(sorted(pairs)), ""))
    except (ValueError, UnicodeError):
        return None


def distribution(results: list[dict], field: str) -> dict[str, float]:
    values: dict[str, float] = {}
    total = 0.0
    for result in results:
        weight = 1 / math.log2(result["position"] + 1)
        label = result[field]
        values[label] = values.get(label, 0.0) + weight
        total += weight
    return {key: value / total for key, value in values.items()} if total else {"unknown": 1.0}


def dominant(distribution_: dict) -> str:
    known = sorted(((k, v) for k, v in distribution_.items() if k != "unknown"), key=lambda item: item[1], reverse=True)
    if not known or 1 - distribution_.get("unknown", 0.0) < 0.6:
        return "unknown"
    if known[0][1] >= 0.55 and known[0][1] - (known[1][1] if len(known) > 1 else 0) >= 0.15:
        return known[0][0]
    return "mixed"


def has_content(value: object) -> bool:
    if isinstance(value, dict):
        return any(has_content(item) for key, item in value.items() if key not in {"page_token", "token", "status", "message"} and "error" not in key)
    if isinstance(value, list):
        return any(has_content(item) for item in value)
    return bool(value)


def ai_overview_summary(value: object, page_url: str | None) -> dict | None:
    """What an AI Overview cited, without keeping full text in the normalized record."""
    if not isinstance(value, dict) or not has_content(value):
        return None
    references = value.get("reference_links") if isinstance(value.get("reference_links"), list) else []
    urls, unresolved = [], 0
    for reference in references:
        link = reference.get("link", "") if isinstance(reference, dict) else ""
        url = canonical_url(link)
        if url and urlsplit(url).hostname in {"google.com", "www.google.com"} and urlsplit(url).path == "/goto":
            unresolved += 1
            continue
        if url and url not in urls:
            urls.append(url)
    hosts = []
    for url in urls:
        host = (urlsplit(url).hostname or "").lower().removeprefix("www.")
        if host and host not in hosts:
            hosts.append(host)
    blocks = value.get("text_blocks") if isinstance(value.get("text_blocks"), list) else []
    excerpt = next((block.get("answer", "") for block in blocks if isinstance(block, dict) and block.get("type") == "paragraph" and block.get("answer")), "")
    excerpt = excerpt or (value.get("markdown", "") if isinstance(value.get("markdown"), str) else "")
    page = canonical_url(page_url) if page_url else None
    page_host = (urlsplit(page).hostname or "").lower().removeprefix("www.") if page else None
    return {"references": len(references), "cited_urls": urls[:30], "cited_hosts": hosts[:30], "unresolved_links": unresolved,
            "blocks": len(blocks), "excerpt": excerpt[:400], "page_cited": bool(page and page in urls), "host_cited": bool(page_host and page_host in hosts)}


def aggregate(results: list[dict]) -> dict:
    """Rank-weighted intent and type distributions plus the dominant estimate; recomputed whenever a result label changes."""
    intents = distribution(results, "intent")
    return {"intent_distribution": intents, "type_distribution": distribution(results, "type"),
            "dominant_intent": dominant(intents), "classified_coverage": 1 - intents.get("unknown", 0.0)}


def normalize(payload: dict, search: dict, timestamp: str, page: dict | None, min_results: int = 5, source: str = "searchapi") -> dict:
    if not isinstance(payload, dict) or payload.get("error") or payload.get("errors"):
        raise ValueError("Provider returned an error payload.")
    metadata = payload.get("search_metadata", {})
    if not isinstance(metadata, dict):
        raise ValueError("Invalid search_metadata.")
    if str(metadata.get("status", "success")).lower() not in {"success", "completed"}:
        raise ValueError("Provider response is not a completed search.")
    engine = search.get("engine", "google")
    details = spec(engine)
    ranked = rows(payload, engine)
    seen = set()
    positions = set()
    results = []
    rejected = 0
    beyond = 0
    for row in ranked:
        if not isinstance(row, dict):
            rejected += 1
            continue
        link, title, snippet = row_fields(row, engine)
        url = canonical_url(link)
        position = row.get("position")
        if isinstance(position, int) and not isinstance(position, bool) and position > MAX_POSITION:
            beyond += 1
            continue
        if not url or isinstance(position, bool) or not isinstance(position, int) or position < 1:
            rejected += 1
            continue
        if url in seen or position in positions:
            rejected += 1
            continue
        parsed = urlsplit(url)
        if parsed.hostname in {"google.com", "www.google.com"} and parsed.path == "/goto":
            rejected += 1
            continue
        seen.add(url)
        positions.add(position)
        classified = classify(title[:1000], snippet[:3000], url, search["hl"])
        if details["type"]:
            classified["type"] = details["type"]
        results.append({"position": position, "url": url, "title": title[:1000], "snippet": snippet[:3000], **classified})
    results.sort(key=lambda result: result["position"])
    features = sorted({feature_key(key, engine) for key in payload if feature_key(key, engine) in FEATURES and has_content(payload.get(key))})
    warnings = []
    if rejected:
        warnings.append(f"Ignored {rejected} malformed, duplicate, out-of-range, or unresolved ranked results.")
    if len(results) < min_results:
        warnings.append(f"Only {len(results)} usable organic results; at least {min_results} are required for alerts.")
    if not packs.registry().supports(search["hl"]):
        warnings.append(f"No intent rule pack for {search['hl']!r} (available: {', '.join(packs.registry().languages())}); intent remains unclassified.")
    ai = payload.get("ai_overview")
    ai_status = "observed" if "ai_overview" in features else ("not_observed" if details["ai_overview"] else "not_applicable")
    if isinstance(ai, dict) and "ai_overview" not in features:
        if ai.get("page_token"):
            ai_status = "requires_followup"
            warnings.append("AI Overview returned a follow-up token only; content was not collected.")
        elif ai.get("error"):
            # Google reported that no Overview exists for this search; an error object is not an observation.
            ai_status = "not_available"
    from .quality import assess
    quality = assess(payload, search, results, min_results)
    warnings.extend(quality["reasons"])
    return {
        "quality": quality,
        "schema_version": 1, "analysis_version": packs.registry().analysis_version(), "source": source, "captured_at": timestamp,
        "search": search, "results": results, "features": features, "ai_overview_status": ai_status,
        **aggregate(results),
        "quality_ok": quality["eligible"], "warnings": warnings, "page": page,
        "ai_overview": ai_overview_summary(ai, page["url"] if page else None) if ai_status == "observed" else None,
        "returned_beyond_top": beyond,
    }

