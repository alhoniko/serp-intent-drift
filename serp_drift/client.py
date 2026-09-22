"""Bounded SearchApi HTTP client. No credentials in URLs, errors, or reports."""

from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
import json
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

try:
    from . import __version__
except ImportError:  # copied out of the package as a standalone module
    __version__ = "standalone"


class ApiError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class SearchApi:
    def __init__(self, api_key: str, settings: dict, *, opener=None, sleep=time.sleep, monotonic=time.monotonic) -> None:
        if not api_key or any(char.isspace() for char in api_key):
            raise ApiError("missing_key", "No API key. Set SEARCHAPI_API_KEY or run `serp-drift key set`.")
        self.api_key = api_key
        self.settings = settings
        self.opener = opener or build_opener(NoRedirect())
        self.sleep = sleep
        self.monotonic = monotonic
        self.requests = 0
        self.last_request: float | None = None

    def _retry_delay(self, value: str | None, attempt: int) -> float:
        if value:
            try:
                delay = max(0.0, float(value))
            except ValueError:
                try:
                    delay = max(0.0, (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds())
                except (ValueError, TypeError, OverflowError):
                    delay = float(2 ** attempt)
            if delay > 60:
                raise ApiError("rate_limited", "Provider requested a wait over 60 seconds. Retry in a later collection run.")
            return delay
        return float(2 ** attempt)

    def request(self, path: str, params: dict) -> dict:
        if path not in {"search", "me", "locations"}:
            raise ValueError("Unsupported SearchApi endpoint.")
        url = f"https://www.searchapi.io/api/v1/{path}"
        if params:
            url += "?" + urlencode(params)
        for attempt in range(self.settings["max_retries"] + 1):
            if self.requests >= self.settings["max_requests_per_run"]:
                raise ApiError("budget_exhausted", "Per-run request budget reached, including retries.")
            if self.last_request is not None:
                delay = self.settings["request_delay_seconds"] - (self.monotonic() - self.last_request)
                if delay > 0:
                    self.sleep(delay)
            self.requests += 1
            self.last_request = self.monotonic()
            request = Request(url, headers={"Authorization": f"Bearer {self.api_key}", "Accept": "application/json", "User-Agent": f"serp-intent-drift/{__version__}"})
            retry_after = None
            try:
                with self.opener.open(request, timeout=self.settings["timeout_seconds"]) as response:
                    body = response.read(10_000_001)
                if len(body) > 10_000_000:
                    raise ApiError("response_too_large", "Provider response exceeds 10 MB.")
                try:
                    payload = json.loads(body)
                except (ValueError, UnicodeError):
                    raise ApiError("invalid_json", "Provider returned invalid JSON.") from None
                if isinstance(payload, list) and path == "locations":
                    return {"locations": payload}
                if not isinstance(payload, dict) or payload.get("error") or payload.get("errors"):
                    raise ApiError("provider_error", "Provider returned an error payload; inspect the SearchApi account dashboard.")
                return payload
            except HTTPError as error:
                status = error.code
                retry_after = error.headers.get("Retry-After") if error.headers else None
                error.close()
                if status not in {408, 429, 500, 502, 503, 504}:
                    raise ApiError(f"http_{status}", f"SearchApi HTTP {status}; check credentials, credits, and request settings.") from None
                failure = ApiError(f"http_{status}", f"SearchApi HTTP {status}; retry limit reached.")
            except (URLError, TimeoutError, OSError):
                failure = ApiError("network_error", "SearchApi network request failed; retry limit reached.")
            if attempt == self.settings["max_retries"]:
                raise failure from None
            self.sleep(self._retry_delay(retry_after, attempt))
        raise AssertionError("unreachable")

    def search(self, params: dict) -> dict:
        return self.request("search", params)

    def ai_overview(self, page_token: str, *, resolve_links: bool = True) -> dict:
        """Fetch a deferred AI Overview through SearchApi's dedicated engine. One request, one credit."""
        params = {"engine": "google_ai_overview", "page_token": page_token}
        if resolve_links:
            params["link"] = "resolved"
        payload = self.request("search", params)
        return payload.get("ai_overview") if isinstance(payload.get("ai_overview"), dict) else payload

    def locations(self, query: str, limit: int = 10) -> list[dict]:
        """Canonical location strings for the `location` parameter. Free of charge in the first live check."""
        payload = self.request("locations", {"q": query[:80], "limit": max(1, min(50, limit))})
        rows = payload.get("locations") if isinstance(payload, dict) else payload
        return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []

    def account(self) -> dict:
        payload = self.request("me", {})
        fields = {"account": ("current_month_usage", "monthly_allowance", "remaining_credits"),
                  "api_usage": ("searches_this_hour", "hourly_rate_limit")}
        return {group: {key: payload.get(group, {}).get(key) for key in keys} for group, keys in fields.items()}

