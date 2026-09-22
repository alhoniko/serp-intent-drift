"""The app: one process serving projects (workspaces), a JSON API, and the scheduler. Standard library only."""

from datetime import UTC, datetime
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
import json
import mimetypes
from pathlib import Path
import re
import secrets
import sqlite3
import threading
from urllib.parse import parse_qs, unquote, urlencode, urlsplit

from . import __version__, analysis_version, packs
from . import insights as insights_module
from . import notify as notifications
from .analysis import analyze
from .client import ApiError, SearchApi
from .config import DEFAULTS, INTENTS, append_target, load_config, remove_target, replace_target, update_labeling, update_notify, update_project, update_settings
from .engines import ENGINES
from .history import change_log, citations, compare_specs, intent_stability, timeline, url_trajectories
from .importing import candidates as import_candidates
from .importing import candidates_from_rows
from .normalize import canonical_url
from .report import build_report, write_report
from .scheduler import Scheduler, budget_exhausted
from .sources import AHREFS_LIMITS, ahrefs_keywords, ahrefs_units_per_row
from .storage import Store, parse_time, utc_now
from .workspace import Workspace

COOKIE = "serp_drift_token"
CSRF_HEADER = "X-Requested-With"
CSRF_VALUE = "serp-drift"
LOOPBACK = {"127.0.0.1", "::1", "localhost"}
ATTENTION_ORDER = {"review": 0, "error": 1, "stale": 2, "config": 3}


def slugify(value: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:56]
    return base or "project"


class ProjectState:
    """Everything the app can do with one workspace. Also the unit the scheduler iterates."""

    def __init__(self, workspace: Workspace, project_id: str | None = None, *, token: str | None = None, poll_seconds: int = 60,
                 scheduler_enabled: bool = False, require_token: bool = False) -> None:
        self.workspace = workspace
        self.id = project_id or slugify(workspace.root.name)
        self.token = token
        self.require_token = require_token or bool(token)
        self.config: dict | None = None
        self.config_error: str | None = None
        self.config_mtime: float | None = None
        self.run_lock = threading.Lock()
        self.run_state = {"running": False, "started_at": None, "trigger": None, "last": None}
        self.account = {"fetched_at": None, "data": None, "error": None}
        self.location_cache: dict[str, list] = {}
        self.verbose = False
        self.scheduler = Scheduler(App.single(self), poll_seconds) if scheduler_enabled else None
        self.reload_config()

    # --- configuration ----------------------------------------------------------------------------------------------
    def reload_config(self) -> None:
        path = self.workspace.config
        try:
            mtime = path.stat().st_mtime
        except OSError:
            self.config, self.config_error, self.config_mtime = None, f"{path} does not exist. Run `serp-drift init`.", None
            return
        if mtime == self.config_mtime and self.config is not None:
            return
        try:
            self.config = load_config(path)
            self.config_error = None
        except ValueError as error:
            self.config, self.config_error = None, str(error)
        self.config_mtime = mtime

    def current_config(self) -> dict | None:
        self.reload_config()
        packs.configure(self.workspace.rules)
        return self.config

    @property
    def name(self) -> str:
        config = self.current_config()
        return (config or {}).get("project", {}).get("name") or self.id

    @property
    def site(self) -> str | None:
        config = self.current_config()
        return (config or {}).get("project", {}).get("site") or None

    def target(self, identifier: str) -> dict:
        config = self.current_config()
        if not config:
            raise ValueError(self.config_error or "No configuration loaded.")
        for target in config["targets"]:
            if target["id"] == identifier:
                return target
        raise KeyError(identifier)

    # --- collection -------------------------------------------------------------------------------------------------
    def run(self, trigger: str, *, force: bool = False, only: set[str] | None = None) -> dict:
        from .cli import run_once
        if not self.run_lock.acquire(blocking=False):
            return {"error": "A collection is already running."}
        try:
            self.run_state.update(running=True, started_at=utc_now(), trigger=trigger)
            try:
                summary = run_once(self.workspace, force=force, trigger=trigger, only=only)
            except (ApiError, ValueError, OSError, sqlite3.Error) as error:
                summary = {"error": str(error), "collected": 0, "skipped": 0, "failed": 0, "requests": 0}
            summary["finished_at"] = utc_now()
            summary["trigger"] = trigger
            self.run_state.update(running=False, last=summary)
            return summary
        finally:
            self.run_state["running"] = False
            self.run_lock.release()

    def run_in_background(self, trigger: str, *, force: bool = False, only: set[str] | None = None) -> bool:
        if self.run_state["running"]:
            return False
        threading.Thread(target=self.run, args=(trigger,), kwargs={"force": force, "only": only}, name=f"serp-drift-run-{self.id}", daemon=True).start()
        return True

    def refresh_account(self) -> dict:
        try:
            data = SearchApi(self.workspace.api_key(), DEFAULTS).account()
            self.account = {"fetched_at": utc_now(), "data": data, "error": None}
        except (ApiError, ValueError) as error:
            self.account = {"fetched_at": utc_now(), "data": None, "error": str(error)}
        return self.account

    # --- views -------------------------------------------------------------------------------------------------------
    def credits_per_day(self) -> int:
        config = self.current_config()
        if not config:
            return 0
        expand = config["settings"].get("ai_overview") == "expand"
        with Store(self.workspace.database) as store:
            active = [target for target in config["targets"] if store.get_setting(target, "paused") != "1"]
        import math
        return math.ceil(sum(2 if expand and ENGINES[target["search"]["engine"]]["ai_overview"] else 1 for target in active) * 24 / config["settings"]["interval_hours"])

    def budget(self) -> dict:
        """Requests recorded by this workspace against its optional cap and collection end date."""
        config = self.current_config()
        settings = config["settings"] if config else {}
        with Store(self.workspace.database) as store:
            used = store.total_requests()
            stopped = bool(config) and budget_exhausted(config, store)
        return {"used": used, "cap": settings.get("max_total_requests", 0), "until": settings.get("collect_until") or None, "stopped": stopped}

    def summary(self) -> dict:
        """One row for the portfolio: counts, health, cost. Cheap enough to compute per request."""
        config = self.current_config()
        row = {"id": self.id, "name": self.name, "site": self.site, "panels": 0, "market": None, "counts": {}, "health": "no config", "health_kind": "error",
               "credits_per_day": 0, "attention": 0, "last_run": self.run_state["last"], "running": self.run_state["running"], "config_error": self.config_error}
        if not config:
            return row
        search = config.get("search") or {}
        row["market"] = f"{ENGINES.get(search.get('engine', 'google'), {}).get('label', 'Google')} · {search.get('gl', '').upper()} · {search.get('hl', '')}".strip(" ·")
        row["panels"] = len(config["targets"])
        row["credits_per_day"] = self.credits_per_day()
        report = self.report()
        counts: dict[str, int] = {}
        for query in report["queries"]:
            counts[query["status"]] = counts.get(query["status"], 0) + 1
        row["counts"] = counts
        row["attention"] = len(self.attention(report))
        row["budget"] = self.budget()
        with Store(self.workspace.database) as store:
            runs = store.runs(20)
        today = datetime.now(UTC).date()
        if not self.workspace.api_key():
            row["health"], row["health_kind"] = "No API key", "error"
        elif runs and runs[0]["error"]:
            row["health"], row["health_kind"] = runs[0]["error"][:60], "error"
        elif runs and runs[0]["failed"]:
            row["health"], row["health_kind"] = f"{runs[0]['failed']} failed in the last run", "error"
        elif (budget := self.budget())["stopped"]:
            row["health"], row["health_kind"] = f"Collection ended · {budget['used']} requests", "muted"
        elif counts.get("stale"):
            row["health"], row["health_kind"] = f"Stale · {counts['stale']} panels", "stale"
        elif runs and parse_time(runs[0]["finished_at"]).date() == today:
            collected_today = sum(run["collected"] for run in runs if parse_time(run["finished_at"]).date() == today)
            row["health"], row["health_kind"] = (f"{min(collected_today, row['panels'])} / {row['panels']} today" if collected_today else "Up to date"), "ok"
        elif runs:
            row["health"], row["health_kind"] = f"Last run {runs[0]['finished_at'][:10]}", "muted"
        else:
            row["health"], row["health_kind"] = "Never collected", "muted"
        return row

    def status(self) -> dict:
        config = self.current_config()
        with Store(self.workspace.database) as store:
            snapshots = store.snapshot_count()
            overviews = store.ai_overview_count()
            runs = store.runs(5)
        return {
            "version": __version__, "analysis_version": analysis_version(), "workspace": self.workspace.describe(), "project": {"id": self.id, "name": self.name, "site": self.site},
            "config_error": self.config_error, "panels": len(config["targets"]) if config else 0, "credits_per_day": self.credits_per_day(),
            "labeling": config["labeling"] if config else None,
            "settings": config["settings"] if config else None, "search": config.get("search") if config else None, "snapshots": snapshots, "ai_overviews": overviews,
            "run": self.run_state, "recent_runs": runs, "budget": self.budget() if config else None, "scheduler": self.scheduler.describe() if self.scheduler else {"enabled": False},
            "account": self.account, "packs": packs.registry().describe(), "engines": {name: spec["label"] for name, spec in ENGINES.items()},
            "intents": list(INTENTS), "auth": {"required": self.require_token},
            "notify": {**config["notify"], "webhook_url": "", "webhook_configured": bool(config["notify"]["webhook_url"])} if config else None,
            "integrations": {"ahrefs": {"key": self.workspace.key_source("ahrefs"), "per_row_units": ahrefs_units_per_row(False), "per_row_units_traffic": ahrefs_units_per_row(True), "limits": list(AHREFS_LIMITS)}},
        }

    def report(self) -> dict:
        config = self.current_config()
        if not config:
            raise ValueError(self.config_error or "No configuration loaded.")
        with Store(self.workspace.database) as store:
            return build_report(config, store)

    def attention(self, report: dict | None = None) -> list[dict]:
        """Only what needs a decision or a fix: unacknowledged reviews, collection errors, stale panels, a broken setup."""
        items = []
        if self.config_error:
            return [{"kind": "config", "panel": None, "title": "Configuration problem", "why": self.config_error, "action": "settings"}]
        if not self.workspace.api_key():
            items.append({"kind": "config", "panel": None, "title": "No SearchApi key", "why": "Collection cannot run. Add the key on the Settings page or with `serp-drift key set`.", "action": "settings"})
        report = report or self.report()
        budget = self.budget()
        if budget["stopped"]:
            # Deliberately ended collection is one fact, not one overdue warning per panel.
            used = f"{budget['used']} of {budget['cap']}" if budget["cap"] else str(budget["used"])
            end = f", end {budget['until']}" if budget["until"] else ""
            items.append({"kind": "config", "panel": None, "title": "Collection ended", "action": "settings",
                          "why": f"The workspace request cap or end date was reached ({used} requests{end}). Panels show their last observations."})
        for query in report["queries"]:
            latest = query["latest"] or {}
            followup = next((case for case in query.get("reviews", []) if case["status"] in {"decided", "monitoring"}
                             and case["review_on"] and case["review_on"] <= datetime.now(UTC).date().isoformat()), None)
            if followup:
                items.append({"kind": "review", "panel": query["id"], "title": query["query"], "why": f"Review date {followup['review_on']} reached. Check the outcome of your recorded decision.",
                              "score": query["score"], "action": "open", "at": followup["review_on"]})
            active = next((case for case in query.get("reviews", []) if case["active"] and case["signal_key"] == query.get("signal_key")), None)
            due = bool(active and active["status"] in {"decided", "monitoring"} and active["review_on"] and active["review_on"] <= datetime.now(UTC).date().isoformat())
            handled = bool(active and active["status"] in {"decided", "monitoring", "closed"} and not due)
            if query["status"] == "review" and not followup and not handled and not (query.get("acknowledged_at") and latest.get("captured_at") and query["acknowledged_at"] >= latest["captured_at"]):
                items.append({"kind": "review", "panel": query["id"], "title": query["query"], "why": " ".join(query["reasons"]), "score": query["score"], "action": "open", "at": latest.get("captured_at")})
            elif query["status"] in {"collection_error", "data_quality", "insufficient_data"}:
                items.append({"kind": "error", "panel": query["id"], "title": query["query"], "why": " ".join(query["reasons"]), "action": "open" if query["status"] == "data_quality" else "retry", "at": (query.get("last_attempt") or {}).get("attempted_at")})
            elif query["status"] == "stale" and not budget["stopped"]:
                items.append({"kind": "stale", "panel": query["id"], "title": query["query"], "why": " ".join(query["reasons"]), "action": "collect", "at": latest.get("captured_at")})
        items.sort(key=lambda item: (ATTENTION_ORDER[item["kind"]], -(item.get("score") or 0), item["title"]))
        return items

    def panel(self, identifier: str) -> dict:
        target = self.target(identifier)
        config = self.current_config()
        site = self.site
        with Store(self.workspace.database) as store:
            snapshots = store.history(target)
            settings = store.panel_settings(target)
            analysis = analyze(target, snapshots, config["settings"], last_attempt=store.last_attempt(target), baseline_from=settings.get("baseline_from"), site=site)
            analysis["reviews"] = store.cases(target)
            analysis["group"] = settings.get("group", "")
            analysis["paused"] = settings.get("paused") == "1"
            analysis["acknowledged_at"] = settings.get("acknowledged_at")
            page_url = (target.get("page") or {}).get("url")
            described = [snapshot for snapshot in snapshots if (snapshot.get("quality") or {}).get("state") != "query_mismatch"]
            # Scores only make sense against a complete baseline; while it builds, the timeline shows captures without scores.
            scored_baseline = analysis["baseline"] if analysis["status"] not in {"building_baseline", "awaiting_data"} else []
            return {
                "project": {"id": self.id, "name": self.name, "site": site},
                "target": {key: target[key] for key in ("id", "query", "search", "identity", "page") if key in target},
                # Captures of another query stay visible in the timeline and the data-quality view, never in URL or citation history.
                "analysis": analysis, "timeline": timeline(snapshots, scored_baseline, page_url, site), "trajectories": url_trajectories(described, site),
                "changes": change_log(described, page_url, site), "citations": citations(described, site), "stability": intent_stability(described),
                "attempts": store.attempts(target, 30), "events": store.events(target, 30), "settings": settings,
                "observations": [{"captured_at": s["captured_at"], "quality": s.get("quality"), "review": s.get("observation_review"), "results": len(s["results"]), "intent": s["dominant_intent"]} for s in reversed(snapshots)],
                "captures": [snapshot["captured_at"] for snapshot in snapshots], "weights": config and __import__("serp_drift.analysis", fromlist=["WEIGHTS"]).WEIGHTS,
            }

    def review_observation(self, identifier: str, body: dict) -> dict:
        target = self.target(identifier)
        if not isinstance(body.get("excluded"), bool):
            raise ValueError("excluded must be true or false.")
        with Store(self.workspace.database) as store:
            store.review_observation(target, str(body.get("captured_at", "")), body["excluded"], str(body.get("reason", "")))
        return self.panel(identifier)

    def decide(self, identifier: str, body: dict) -> dict:
        target = self.target(identifier)
        query = self.panel(identifier)["analysis"]
        with Store(self.workspace.database) as store:
            current = store.sync_case(query)
            case_id = body.get("case_id") or (current or {}).get("id")
            if not case_id:
                raise ValueError("There is no confirmed change to review yet.")
            return store.decide(target, int(case_id), str(body.get("status", "investigating")), str(body.get("decision", "")),
                                str(body.get("note", "")), body.get("review_on") or None)

    def set_group(self, identifier: str, value: str) -> dict:
        target = self.target(identifier)
        if not isinstance(value, str) or len(value) > 80:
            raise ValueError("Group names must be 80 characters or fewer.")
        with Store(self.workspace.database) as store:
            store.set_setting(target, "group", value.strip() or None)
            store.add_event("panel_group", {"group": value.strip()}, target)
        return {"group": value.strip()}

    def change_labeling(self, body: dict) -> dict:
        result = update_labeling(self.workspace.config, body)
        self.config_mtime = None
        self.reload_config()
        return result

    def capture(self, identifier: str, captured_at: str) -> dict:
        target = self.target(identifier)
        with Store(self.workspace.database) as store:
            snapshots = [snapshot for snapshot in store.history(target) if snapshot["captured_at"] == captured_at]
            if not snapshots:
                raise KeyError(captured_at)
            return {"snapshot": snapshots[0], "raw": store.raw_subset(target, captured_at), "ai_overview": store.ai_overview(target, captured_at)}

    def compare(self, identifier: str, left: dict, right: dict) -> dict:
        target = self.target(identifier)
        config = self.current_config()
        with Store(self.workspace.database) as store:
            snapshots = store.history(target)
            analysis = analyze(target, snapshots, config["settings"], baseline_from=store.get_setting(target, "baseline_from"))
            return compare_specs(snapshots, analysis["baseline"], left, right)

    def set_baseline(self, identifier: str, value: str | None) -> dict:
        target = self.target(identifier)
        if value:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            if len(value) == 10:
                value = f"{value}T00:00:00Z"
        with Store(self.workspace.database) as store:
            before = store.get_setting(target, "baseline_from")
            store.set_setting(target, "baseline_from", value)
            store.add_event("baseline_moved", {"from": before, "to": value}, target)
        return {"baseline_from": value}

    def acknowledge(self, identifier: str) -> dict:
        target = self.target(identifier)
        with Store(self.workspace.database) as store:
            latest = store.last_capture_time(target) or utc_now()
            store.set_setting(target, "acknowledged_at", latest)
            store.add_event("acknowledged", {"through": latest}, target)
        return {"acknowledged_at": latest}

    def set_paused(self, identifier: str, paused: bool) -> dict:
        target = self.target(identifier)
        with Store(self.workspace.database) as store:
            store.set_setting(target, "paused", "1" if paused else None)
            store.add_event("paused" if paused else "resumed", {}, target)
        return {"paused": paused}

    def set_page(self, identifier: str, page_url: str | None, intent: str | None) -> dict:
        """Rewrite one target's page profile in monitor.toml: remove and re-append keeps the file valid and the identity unchanged."""
        target = self.target(identifier)
        page = {}
        if page_url:
            if not canonical_url(page_url):
                raise ValueError("page_url must be an HTTP(S) URL.")
            page["url"] = page_url.strip()
            if intent:
                if intent not in INTENTS:
                    raise ValueError("Unknown intent.")
                page["intent"] = intent
            else:
                page["intent"] = "informational"
            if (target.get("page") or {}).get("fetch"):
                page["fetch"] = True
        search = {key: value for key, value in target["search"].items() if key in {"engine", "gl", "hl", "device", "location"}}
        replace_target(self.workspace.config, {"id": identifier, "query": target["query"], "search": search, "page": page})
        self.reload_config()
        return {"page": page or None}

    def _build_target(self, body: dict) -> dict:
        query = str(body.get("query", "")).strip()
        if not query:
            raise ValueError("query is required.")
        search = {key: str(body[key]).strip() for key in ("engine", "gl", "hl", "device", "location") if body.get(key) not in (None, "")}
        identifier = str(body.get("id") or "").strip() or self.slug(query, search)
        target = {"id": identifier, "query": query, "search": search}
        page_url = str(body.get("page_url") or "").strip()
        if page_url:
            if not canonical_url(page_url):
                raise ValueError("page_url must be an HTTP(S) URL.")
            page = {"url": page_url}
            if body.get("intent"):
                if body["intent"] not in INTENTS:
                    raise ValueError("Unknown intent.")
                page["intent"] = body["intent"]
            if body.get("fetch"):
                page["fetch"] = True
            if not page.get("intent") and not page.get("fetch"):
                page["intent"] = "informational"
            target["page"] = page
        return target

    def add_panel(self, body: dict) -> dict:
        target = self._build_target(body)
        added = append_target(self.workspace.config, target)
        self.reload_config()
        with Store(self.workspace.database) as store:
            store.add_event("panel_added", {"id": target["id"], "query": target["query"], "search": added["search"]}, added)
        return {key: added[key] for key in ("id", "query", "search", "identity", "page") if key in added}

    def add_panels(self, items: list[dict], *, source: str = "import") -> dict:
        """Bulk add; duplicates (same id or same panel identity) are skipped, never overwritten."""
        created, skipped, errors = [], [], []
        for item in items[:500]:
            try:
                created.append(self.add_panel(item))
            except ValueError as error:
                if "unique kebab-case id" in str(error) or "Duplicate search panel" in str(error):
                    skipped.append(str(item.get("query", "")).strip())
                else:
                    errors.append({"query": str(item.get("query", "")).strip(), "error": str(error)})
        with Store(self.workspace.database) as store:
            store.add_event("import", {"source": source, "created": len(created), "skipped": len(skipped), "errors": len(errors)})
        return {"created": created, "skipped": skipped, "errors": errors}

    def import_preview(self, text: str) -> dict:
        config = self.current_config()
        if not config:
            raise ValueError(self.config_error or "No configuration loaded.")
        if len(text) > 20_000_000:
            raise ValueError("The file is larger than 20 MB.")
        existing = {target["query"].lower() for target in config["targets"]}
        language = (config.get("search") or {}).get("hl", "en")
        return import_candidates(text, existing=existing, language=language)

    def import_fetch(self, body: dict) -> dict:
        """Fetch keyword candidates from an API source (Ahrefs). Same result shape as import_preview plus a source block."""
        config = self.current_config()
        if not config:
            raise ValueError(self.config_error or "No configuration loaded.")
        if str(body.get("source") or "ahrefs") != "ahrefs":
            raise ValueError("Only the ahrefs source can be fetched; export other tools as CSV.")
        target = str(body.get("target") or self.site or "").strip()
        if not target:
            raise ValueError("Set the project site first (Settings → Project), or give a target.")
        search = config.get("search") or {}
        country = str(body.get("country") or search.get("gl") or "us").strip().lower()
        fetched = ahrefs_keywords(self.workspace.api_key("ahrefs"), target, country=country, limit=int(body.get("limit") or 500), traffic=bool(body.get("traffic")))
        existing = {item["query"].lower() for item in config["targets"]}
        result = candidates_from_rows(fetched["rows"], fetched["detected"], existing=existing, language=search.get("hl", "en"))
        result["source"] = fetched["source"]
        with Store(self.workspace.database) as store:
            store.add_event("import_fetch", {"source": "ahrefs", "target": fetched["source"]["target"], "country": country, "rows": fetched["source"]["rows"], "units": fetched["source"]["units"]})
        return result

    def remove_panel(self, identifier: str) -> dict:
        target = self.target(identifier)
        remove_target(self.workspace.config, identifier)
        self.reload_config()
        with Store(self.workspace.database) as store:
            store.add_event("panel_removed", {"id": identifier, "query": target["query"]}, target)
        return {"removed": identifier, "history_kept": True}

    def change_settings(self, body: dict) -> dict:
        allowed = {"interval_hours", "baseline_size", "confirmations", "min_results", "drift_threshold", "max_requests_per_run",
                   "request_delay_seconds", "timeout_seconds", "max_retries", "raw_retention_days", "ai_overview", "resolve_links"}
        changes = {key: value for key, value in body.items() if key in allowed}
        if not changes:
            raise ValueError("No supported settings supplied.")
        settings = update_settings(self.workspace.config, changes)
        self.reload_config()
        return settings

    def change_notify(self, body: dict) -> dict:
        allowed = {"webhook_url", "format", "on", "digest", "digest_day"}
        changes = {key: value for key, value in body.items() if key in allowed}
        if not changes:
            raise ValueError("No supported notify fields supplied.")
        result = update_notify(self.workspace.config, changes)
        self.reload_config()
        return result

    def change_project(self, body: dict) -> dict:
        changes = {key: str(body[key]) for key in ("name", "site") if key in body}
        if not changes:
            raise ValueError("Supply name and/or site.")
        result = update_project(self.workspace.config, changes)
        self.reload_config()
        with Store(self.workspace.database) as store:
            store.add_event("project_changed", result)
        return result

    def save_key(self, value: str, service: str = "searchapi") -> dict:
        path = self.workspace.save_key(value, service)
        if service == "searchapi":
            self.account = {"fetched_at": None, "data": None, "error": None}
        return {"saved": str(path), "service": service}

    def mcp_info(self) -> dict:
        from . import connect  # local: connect imports mcp, which imports this module

        return connect.describe(self.workspace)

    def mcp_check(self) -> dict:
        from . import connect

        return connect.self_test(self.workspace)

    def activity(self, limit: int = 100) -> dict:
        with Store(self.workspace.database) as store:
            return {"events": store.events(None, limit), "runs": store.runs(limit)}

    def digest(self, days: int, fmt: str) -> tuple[bytes, str]:
        config = self.current_config()
        with Store(self.workspace.database) as store:
            report = build_report(config, store)
            data = notifications.digest(config, store, report, days=days)
        if fmt == "svg":
            return notifications.digest_svg(data).encode("utf-8"), "image/svg+xml; charset=utf-8"
        if fmt == "markdown":
            return notifications.digest_markdown(data).encode("utf-8"), "text/markdown; charset=utf-8"
        return json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8"

    def test_webhook(self) -> dict:
        config = self.current_config()
        notify = config["notify"]
        if not notify["webhook_url"]:
            raise ValueError("notify.webhook_url is not configured.")
        outcome = notifications.send(notify["webhook_url"], notify["format"], "serp-drift test", "The webhook is configured correctly.", {"event": "test", "at": utc_now()})
        with Store(self.workspace.database) as store:
            store.add_event("notification", {"kind": "test", **outcome})
        return outcome

    def locations(self, query: str) -> list[dict]:
        query = query.strip()
        if len(query) < 2:
            return []
        if query.lower() not in self.location_cache:
            rows = SearchApi(self.workspace.api_key(), DEFAULTS).locations(query, 10)
            self.location_cache[query.lower()] = [{key: row.get(key) for key in ("canonical_name", "name", "target_type", "country_code", "reach")} for row in rows]
        return self.location_cache[query.lower()]

    def insights(self, days: int | None) -> dict:
        config = self.current_config()
        with Store(self.workspace.database) as store:
            return insights_module.compute(config, store, days=days)

    def dataset(self, days: int | None) -> bytes:
        config = self.current_config()
        with Store(self.workspace.database) as store:
            return insights_module.dataset_zip(insights_module.dataset(config, store, days=days))

    def export_report(self) -> str:
        config = self.current_config()
        with Store(self.workspace.database) as store:
            write_report(build_report(config, store), self.workspace.reports)
        return str(self.workspace.reports / "index.html")

    @staticmethod
    def slug(query: str, search: dict) -> str:
        base = re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-")[:56] or "query"
        extras = [search[key] for key in ("engine", "gl", "device") if search.get(key) and search[key] not in {"google", "us", "desktop"}]
        return "-".join([base, *extras])[:80]


AppState = ProjectState  # backwards-compatible name


class App:
    """Several projects behind one server and one scheduler."""

    def __init__(self, projects: list[ProjectState], *, token: str | None = None, require_token: bool = False, poll_seconds: int = 60,
                 scheduler_enabled: bool = True, projects_root: Path | None = None) -> None:
        if not projects:
            raise ValueError("At least one project is required.")
        self.projects: dict[str, ProjectState] = {}
        for project in projects:
            identifier = project.id
            suffix = 2
            while identifier in self.projects:
                identifier = f"{project.id}-{suffix}"
                suffix += 1
            project.id = identifier
            self.projects[identifier] = project
        self.default_id = next(iter(self.projects))
        self.token = token
        self.require_token = require_token or bool(token)
        self.projects_root = projects_root
        self.verbose = False
        self.scheduler = Scheduler(self, poll_seconds) if scheduler_enabled else None

    @classmethod
    def single(cls, state: ProjectState) -> "App":
        app = cls.__new__(cls)
        app.projects = {state.id: state}
        app.default_id = state.id
        app.token = state.token
        app.require_token = state.require_token
        app.projects_root = None
        app.verbose = False
        app.scheduler = None
        return app

    @property
    def default(self) -> ProjectState:
        return self.projects[self.default_id]

    def project(self, identifier: str) -> ProjectState:
        try:
            return self.projects[identifier]
        except KeyError:
            raise KeyError(identifier) from None

    def status(self) -> dict:
        base = self.default.status()
        base["projects"] = [project.summary() for project in self.projects.values()]
        base["multi_project"] = len(self.projects) > 1 or self.projects_root is not None
        base["projects_root"] = str(self.projects_root) if self.projects_root else None
        base["scheduler"] = self.scheduler.describe() if self.scheduler else {"enabled": False}
        base["auth"] = {"required": self.require_token}
        return base

    def portfolio(self) -> dict:
        rows, attention = [], []
        for project in self.projects.values():
            try:
                rows.append(project.summary())
                for item in project.attention():
                    attention.append({**item, "project": project.id, "project_name": project.name})
            except (ValueError, OSError) as error:
                rows.append({"id": project.id, "name": project.name, "site": project.site, "panels": 0, "counts": {}, "health": str(error)[:80], "health_kind": "error",
                             "credits_per_day": 0, "attention": 1, "market": None, "last_run": None, "running": False, "config_error": str(error)})
                attention.append({"kind": "config", "panel": None, "title": "Configuration problem", "why": str(error), "action": "settings", "project": project.id, "project_name": project.name})
        attention.sort(key=lambda item: (ATTENTION_ORDER[item["kind"]], -(item.get("score") or 0), item["title"]))
        return {"projects": rows, "attention": attention, "panels": sum(row["panels"] for row in rows), "credits_per_day": sum(row["credits_per_day"] for row in rows),
                "running": any(project.run_state["running"] for project in self.projects.values())}

    def run_all(self, trigger: str) -> dict:
        started = [project.id for project in self.projects.values() if project.run_in_background(trigger)]
        return {"started": started}

    def create_project(self, body: dict) -> dict:
        from .cli import init_workspace
        if not self.projects_root:
            raise ValueError("This server was started with fixed --dir workspaces. Start it with --projects <root> to create projects from the app.")
        site = str(body.get("site") or "").strip()
        name = str(body.get("name") or "").strip() or site
        if not name:
            raise ValueError("name or site is required.")
        identifier = slugify(str(body.get("id") or name))
        if identifier in self.projects or (self.projects_root / identifier).exists():
            raise ValueError(f"A project named {identifier!r} already exists.")
        workspace = Workspace(self.projects_root / identifier)
        init_workspace(workspace, query=None, page=None, intent=None, gl=str(body.get("gl") or "us"), hl=str(body.get("hl") or "en"), device=str(body.get("device") or "desktop"))
        update_project(workspace.config, {"name": name, "site": site})
        if body.get("api_key"):
            workspace.save_key(str(body["api_key"]))
        project = ProjectState(workspace, identifier, require_token=self.require_token)
        self.projects[identifier] = project
        return project.summary()


class Handler(BaseHTTPRequestHandler):
    app: App
    server_version = f"serp-drift/{__version__}"
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        if self.app.verbose:
            super().log_message(format, *args)

    # --- helpers -------------------------------------------------------------------------------------------------------
    def send_json(self, payload: object, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_bytes(body, "application/json; charset=utf-8", status, {"Cache-Control": "no-store"})

    def send_bytes(self, body: bytes, content_type: str, status: int = 200, extra: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.security_headers()
        self.end_headers()
        self.wfile.write(body)

    def security_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; form-action 'self'; base-uri 'none'")

    def read_body(self, limit: int = 25_000_000) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        if length < 0 or length > limit:
            raise ValueError("Request body too large.")
        return self.rfile.read(length) if length else b""

    def read_json(self) -> dict:
        raw = self.read_body(2_000_000)
        if not raw:
            return {}
        try:
            body = json.loads(raw)
        except ValueError:
            raise ValueError("Body must be JSON.") from None
        if not isinstance(body, dict):
            raise ValueError("Body must be a JSON object.")
        return body

    def presented_token(self) -> str | None:
        header = self.headers.get("Authorization", "")
        if header.startswith("Bearer "):
            return header[7:].strip()
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        return cookie[COOKIE].value if COOKIE in cookie else None

    def authorized(self) -> bool:
        if not self.app.require_token:
            try:
                return urlsplit("http://" + self.headers.get("Host", "")).hostname in LOOPBACK
            except ValueError:
                return False
        presented = self.presented_token()
        return bool(presented and self.app.token and secrets.compare_digest(presented, self.app.token))

    def csrf_ok(self) -> bool:
        if self.headers.get(CSRF_HEADER) != CSRF_VALUE:
            return False
        origin = self.headers.get("Origin")
        if origin:
            return urlsplit(origin).netloc == self.headers.get("Host")
        return True

    def resolve(self, path: str) -> tuple[ProjectState, str]:
        """`/api/p/<project>/rest` selects a project; a bare `/api/rest` means the default project."""
        match = re.match(r"^/api/p/([^/]+)(/.*)?$", path)
        if match:
            return self.app.project(unquote(match.group(1))), "/api" + (match.group(2) or "/status")
        return self.app.default, path

    # --- routing --------------------------------------------------------------------------------------------------------
    def do_GET(self) -> None:
        parts = urlsplit(self.path)
        path, query = parts.path, parse_qs(parts.query)
        if path in {"/", "/index.html"} and "token" in query:
            token = query["token"][0]
            if self.app.token and secrets.compare_digest(token, self.app.token):
                rest = urlencode({key: values for key, values in query.items() if key != "token"}, doseq=True)  # keep ?theme= and friends
                self.send_response(HTTPStatus.SEE_OTHER)
                self.send_header("Location", f"/?{rest}" if rest else "/")
                self.send_header("Set-Cookie", f"{COOKIE}={token}; Path=/; HttpOnly; SameSite=Strict")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
        if not self.authorized():
            if path.startswith("/api/"):
                return self.send_json({"error": "Unauthorized. Open the app with ?token=… or send Authorization: Bearer."}, 401)
            return self.send_bytes(b"<!doctype html><title>serp-drift</title><p>This instance needs a token. Open the link printed by <code>serp-drift serve</code>.", "text/html; charset=utf-8", 401)
        try:
            if path in {"/", "/index.html"} or (not path.startswith("/api/") and not path.startswith("/assets/") and "." not in path.rsplit("/", 1)[-1]):
                return self.send_asset("app.html", "text/html; charset=utf-8")
            if path.startswith("/assets/"):
                return self.send_asset(path[len("/assets/"):])
            if path == "/api/portfolio":
                return self.send_json(self.app.portfolio())
            if path == "/api/projects":
                return self.send_json({"projects": [project.summary() for project in self.app.projects.values()], "projects_root": str(self.app.projects_root) if self.app.projects_root else None})
            state, path = self.resolve(path)
            if path == "/api/status":
                return self.send_json(self.app.status() if state is self.app.default else state.status() | {"projects": [p.summary() for p in self.app.projects.values()], "multi_project": True, "scheduler": self.app.scheduler.describe() if self.app.scheduler else {"enabled": False}, "auth": {"required": self.app.require_token}})
            if path == "/api/report":
                return self.send_json(state.report())
            if path == "/api/attention":
                return self.send_json({"attention": state.attention()})
            if path == "/api/mcp":
                return self.send_json(state.mcp_info())
            if path == "/api/activity":
                return self.send_json(state.activity(int(query.get("limit", ["100"])[0])))
            if path == "/api/runs":
                with Store(state.workspace.database) as store:
                    return self.send_json({"runs": store.runs(100), "events": store.events(None, 100)})
            if path == "/api/account":
                return self.send_json(state.account if state.account["fetched_at"] and "refresh" not in query else state.refresh_account())
            if path == "/api/locations":
                return self.send_json({"locations": state.locations(query.get("q", [""])[0][:80])})
            if path == "/api/insights":
                days = query.get("days", [""])[0]
                return self.send_json(state.insights(max(1, min(3650, int(days))) if days else None))
            if path == "/api/export/dataset.zip":
                days = query.get("days", [""])[0]
                body = state.dataset(max(1, min(3650, int(days))) if days else None)
                return self.send_bytes(body, "application/zip", extra={"Content-Disposition": 'attachment; filename="serp-drift-dataset.zip"', "Cache-Control": "no-store"})
            if path.startswith("/api/digest"):
                fmt = {"/api/digest.svg": "svg", "/api/digest.md": "markdown"}.get(path, "json")
                days = max(1, min(365, int(query.get("days", ["7"])[0])))
                body, content_type = state.digest(days, fmt)
                return self.send_bytes(body, content_type, extra={"Cache-Control": "no-store"})
            if path.startswith("/api/panels/"):
                rest = path[len("/api/panels/"):].split("/")
                identifier = unquote(rest[0])
                if len(rest) == 1:
                    return self.send_json(state.panel(identifier))
                if len(rest) == 3 and rest[1] == "captures":
                    return self.send_json(state.capture(identifier, unquote(rest[2])))
            if path == "/api/export/report.json":
                return self.send_json(state.report())
            return self.send_json({"error": "Not found."}, 404)
        except KeyError as error:
            return self.send_json({"error": f"Unknown project, panel, or capture: {error.args[0]}"}, 404)
        except (ValueError, OSError, ApiError) as error:
            return self.send_json({"error": str(error)}, 400)

    def do_POST(self) -> None:
        self.mutate("POST")

    def do_DELETE(self) -> None:
        self.mutate("DELETE")

    def mutate(self, method: str) -> None:
        path = urlsplit(self.path).path
        if not self.authorized():
            return self.send_json({"error": "Unauthorized."}, 401)
        if not self.csrf_ok():
            return self.send_json({"error": f"Missing {CSRF_HEADER}: {CSRF_VALUE} header or cross-origin request."}, 403)
        try:
            if method == "POST" and path == "/api/projects":
                return self.send_json(self.app.create_project(self.read_json()), 201)
            if method == "POST" and path == "/api/collect-all":
                return self.send_json(self.app.run_all("manual"), 202)
            state, path = self.resolve(path)
            if method == "POST" and path == "/api/import/preview":
                content_type = self.headers.get("Content-Type", "")
                if content_type.startswith("application/json"):
                    text = str(self.read_json().get("text", ""))
                else:
                    text = self.read_body().decode("utf-8", errors="replace")
                return self.send_json(state.import_preview(text))
            body = self.read_json() if method == "POST" else {}
            if method == "POST" and path == "/api/import/fetch":
                return self.send_json(state.import_fetch(body))
            if method == "POST" and path == "/api/mcp/check":
                return self.send_json(state.mcp_check())
            if method == "POST" and path == "/api/collect":
                only = set(body["ids"]) if isinstance(body.get("ids"), list) else None
                started = state.run_in_background("manual", force=bool(body.get("force")), only=only)
                return self.send_json({"started": started, "run": state.run_state}, 202 if started else 409)
            if method == "POST" and path == "/api/panels":
                return self.send_json(state.add_panel(body), 201)
            if method == "POST" and path == "/api/panels/bulk":
                items = body.get("panels")
                if not isinstance(items, list) or not items:
                    raise ValueError("panels must be a non-empty list.")
                result = state.add_panels(items, source=str(body.get("source") or "import"))
                if body.get("collect") and result["created"]:
                    result["collect_started"] = state.run_in_background("import", only={item["id"] for item in result["created"]})
                return self.send_json(result, 201)
            if method == "POST" and path == "/api/labeling":
                return self.send_json(state.change_labeling(body))
            if method == "POST" and path == "/api/settings":
                return self.send_json(state.change_settings(body))
            if method == "POST" and path == "/api/notify":
                return self.send_json(state.change_notify(body))
            if method == "POST" and path == "/api/notify/test":
                return self.send_json(state.test_webhook())
            if method == "POST" and path == "/api/project":
                return self.send_json(state.change_project(body))
            if method == "POST" and path == "/api/key":
                return self.send_json(state.save_key(str(body.get("key", "")), str(body.get("service") or "searchapi")))
            if method == "POST" and path == "/api/account/refresh":
                return self.send_json(state.refresh_account())
            if method == "POST" and path == "/api/export":
                return self.send_json({"written": state.export_report()})
            if path.startswith("/api/panels/"):
                rest = path[len("/api/panels/"):].split("/")
                identifier = unquote(rest[0])
                if method == "DELETE" and len(rest) == 1:
                    return self.send_json(state.remove_panel(identifier))
                if method == "POST" and len(rest) == 2:
                    action = rest[1]
                    if action == "observation-review":
                        return self.send_json(state.review_observation(identifier, body))
                    if action == "decision":
                        return self.send_json(state.decide(identifier, body))
                    if action == "group":
                        return self.send_json(state.set_group(identifier, body.get("group", "")))
                    if action == "compare":
                        return self.send_json(state.compare(identifier, body.get("left") or {"preset": "baseline"}, body.get("right") or {"preset": "latest"}))
                    if action == "baseline":
                        return self.send_json(state.set_baseline(identifier, body.get("from") or None))
                    if action == "acknowledge":
                        return self.send_json(state.acknowledge(identifier))
                    if action == "pause":
                        return self.send_json(state.set_paused(identifier, bool(body.get("paused", True))))
                    if action == "page":
                        return self.send_json(state.set_page(identifier, body.get("page_url") or None, body.get("intent") or None))
            return self.send_json({"error": "Not found."}, 404)
        except KeyError as error:
            return self.send_json({"error": f"Unknown project or panel: {error.args[0]}"}, 404)
        except (ValueError, OSError, ApiError) as error:
            return self.send_json({"error": str(error)}, 400)

    def send_asset(self, name: str, content_type: str | None = None) -> None:
        if "/" in name or name.startswith(".") or not name:
            return self.send_json({"error": "Not found."}, 404)
        resource = files("serp_drift").joinpath("assets", name)
        if not resource.is_file() or name.endswith((".json", ".py")):
            return self.send_json({"error": "Not found."}, 404)
        body = resource.read_bytes()
        self.send_bytes(body, content_type or mimetypes.guess_type(name)[0] or "application/octet-stream", extra={"Cache-Control": "no-cache"})


def make_server(app_or_state, host: str, port: int, *, verbose: bool = False) -> ThreadingHTTPServer:
    app = app_or_state if isinstance(app_or_state, App) else App.single(app_or_state)
    handler = type("BoundHandler", (Handler,), {"app": app})
    app.verbose = verbose
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    return server


def serve(workspaces: list[Workspace] | Workspace, *, host: str = "127.0.0.1", port: int = 8765, token: str | None = None, poll_seconds: int = 60,
          scheduler_enabled: bool = True, verbose: bool = False, projects_root: Path | None = None) -> None:
    workspaces = [workspaces] if isinstance(workspaces, Workspace) else list(workspaces)
    exposed = host not in LOOPBACK
    if exposed and not token:
        token = secrets.token_urlsafe(24)
    require = exposed or bool(token)
    projects = [ProjectState(workspace, require_token=require) for workspace in workspaces]
    app = App(projects, token=token, require_token=require, poll_seconds=poll_seconds, scheduler_enabled=scheduler_enabled, projects_root=projects_root)
    server = make_server(app, host, port, verbose=verbose)
    shown_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    link = f"http://{shown_host}:{port}/" + (f"?token={token}" if require else "")
    print(f"serp-drift {__version__} · {len(projects)} project{'s' if len(projects) != 1 else ''}: " + ", ".join(f"{p.id} ({p.workspace.root})" for p in projects), flush=True)
    print(f"Open {link}", flush=True)
    if exposed:
        print("Warning: the app is reachable from other machines; keep the token private and prefer a TLS proxy.", flush=True)
    if app.scheduler:
        app.scheduler.start()
    try:
        server.serve_forever()
    finally:
        if app.scheduler:
            app.scheduler.stop()
        server.server_close()
