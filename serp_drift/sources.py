"""Keyword sources beyond CSV. Discovery only: the list of keywords a site ranks for. Every capture still comes from SearchApi.

Ahrefs API v3, `GET /v3/site-explorer/organic-keywords`. One request per fetch, bounded by the caller's limit; the token
goes in the Authorization header, never in a URL, log, or error message. Units: max(50, per-row field cost x rows).
"""

from datetime import UTC, datetime
import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

try:
    from . import __version__
except ImportError:  # copied out of the package as a standalone module
    __version__ = "standalone"

AHREFS_URL = "https://api.ahrefs.com/v3/site-explorer/organic-keywords"
AHREFS_FIELDS = ("keyword", "volume", "best_position", "best_position_url", "best_position_kind", "is_informational", "is_commercial", "is_transactional", "is_navigational", "is_branded")
AHREFS_TRAFFIC_FIELD = "sum_traffic"
AHREFS_FIELD_UNITS = {"volume": 10, "sum_traffic": 10, "keyword_difficulty": 10}  # every other field costs 1 unit per row
AHREFS_LIMITS = (100, 250, 500, 1000)
AHREFS_MIN_UNITS = 50
INTENT_FLAGS = (("is_informational", "informational"), ("is_commercial", "commercial"), ("is_transactional", "transactional"), ("is_navigational", "navigational"))


class SourceError(ValueError):
    """A problem the user can act on: missing token, bad target, provider refusal."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def ahrefs_fields(traffic: bool = False) -> tuple[str, ...]:
    return AHREFS_FIELDS + ((AHREFS_TRAFFIC_FIELD,) if traffic else ())


def ahrefs_units_per_row(traffic: bool = False) -> int:
    return sum(AHREFS_FIELD_UNITS.get(field, 1) for field in ahrefs_fields(traffic))


def ahrefs_units(rows: int, traffic: bool = False) -> int:
    """The units one fetch should consume; the response header reports the real figure."""
    return max(AHREFS_MIN_UNITS, ahrefs_units_per_row(traffic) * max(0, rows))


def clean_target(value: str) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"^https?://", "", text).rstrip("/")
    if not text or " " in text or not re.match(r"^[a-z0-9.-]+(/[^\s]*)?$", text):
        raise SourceError("The target must be a hostname such as example.com (a path is allowed).")
    return text


def _number(value) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _row(keyword: dict) -> dict | None:
    query = re.sub(r"\s+", " ", str(keyword.get("keyword") or "")).strip()
    if not query:
        return None
    intent = next((label for flag, label in INTENT_FLAGS if keyword.get(flag)), None)
    position = _number(keyword.get("best_position"))
    return {"query": query, "impressions": None, "clicks": None, "volume": _number(keyword.get("volume")), "traffic": _number(keyword.get(AHREFS_TRAFFIC_FIELD)),
            "position": position, "url": keyword.get("best_position_url") or None, "kind": keyword.get("best_position_kind") or None,
            "intent_hint": intent, "branded": bool(keyword.get("is_branded"))}


def ahrefs_keywords(token: str, target: str, *, country: str | None, limit: int = 500, traffic: bool = False, mode: str = "subdomains",
                    date: str | None = None, opener=None, timeout: float = 60.0) -> dict:
    """Fetch the organic keywords of a target as normalized rows plus the units the request cost."""
    if not token or any(char.isspace() for char in token):
        raise SourceError("No Ahrefs API token. Add one under Settings → Integrations, or set AHREFS_API_TOKEN.")
    target = clean_target(target)
    country = str(country or "").strip().lower() or None
    if country is not None and not re.match(r"^[a-z]{2}$", country):
        raise SourceError("country must be a two-letter code such as us or fi.")
    limit = int(limit)
    if not 1 <= limit <= max(AHREFS_LIMITS):
        raise SourceError(f"limit must be between 1 and {max(AHREFS_LIMITS)}.")
    if mode not in {"exact", "prefix", "domain", "subdomains"}:
        raise SourceError("mode must be exact, prefix, domain, or subdomains.")
    date = date or datetime.now(UTC).strftime("%Y-%m-%d")
    fields = ahrefs_fields(traffic)
    params = {"target": target, "date": date, "select": ",".join(fields), "limit": limit, "mode": mode, "output": "json",
              "order_by": f"{AHREFS_TRAFFIC_FIELD}:desc" if traffic else "volume:desc"}
    if country:
        params["country"] = country
    request = Request(f"{AHREFS_URL}?{urlencode(params)}", headers={"Authorization": f"Bearer {token}", "Accept": "application/json", "User-Agent": f"serp-intent-drift/{__version__}"})
    opener = opener or build_opener(NoRedirect())
    try:
        with opener.open(request, timeout=timeout) as response:
            body = response.read(20_000_001)
            headers = response.headers
    except HTTPError as error:
        status = error.code
        detail = ""
        try:
            payload = json.loads(error.read(100_000))
            detail = str(payload.get("error") or payload.get("message") or "") if isinstance(payload, dict) else ""
        except (ValueError, UnicodeError, OSError):
            detail = ""
        finally:
            error.close()
        if status in {401, 403}:
            raise SourceError(f"Ahrefs rejected the token (HTTP {status}). Check the token and that your plan includes API access.") from None
        if status == 429:
            raise SourceError("Ahrefs rate limit reached (HTTP 429). Try again in a minute.") from None
        raise SourceError(f"Ahrefs HTTP {status}{': ' + detail[:200] if detail else ''}.") from None
    except URLError as error:
        raise SourceError(f"Could not reach Ahrefs: {getattr(error, 'reason', error)}") from None
    if len(body) > 20_000_000:
        raise SourceError("Ahrefs response exceeds 20 MB; lower the limit.")
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeError):
        raise SourceError("Ahrefs returned invalid JSON.") from None
    if not isinstance(payload, dict) or not isinstance(payload.get("keywords"), list):
        raise SourceError(f"Ahrefs returned an unexpected payload{': ' + str(payload.get('error'))[:200] if isinstance(payload, dict) and payload.get('error') else ''}.")
    rows = [row for row in (_row(item) for item in payload["keywords"] if isinstance(item, dict)) if row]
    units = _number(headers.get("x-api-units-cost-total")) if headers else None
    return {"rows": rows, "detected": {"rows": len(rows), "columns": "Ahrefs organic keywords"},
            "source": {"name": "ahrefs", "target": target, "country": country, "date": date, "limit": limit, "mode": mode, "traffic": traffic,
                       "rows": len(rows), "units": int(units) if units is not None else None, "estimated_units": ahrefs_units(len(rows), traffic), "fields": list(fields)}}
