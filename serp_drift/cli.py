"""Command line entry points. Every command resolves paths through one workspace directory."""

import argparse
from datetime import UTC, datetime
from functools import partial
import getpass
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
import json
import math
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time

from . import __version__, packs
from . import notify as notifications
from .client import ApiError, SearchApi
from .config import DEFAULTS, INTENTS, load_config, minimum_spacing_seconds, render_config, search_identity
from .engines import request_params, spec
from .importing import candidates as import_candidates
from .importing import candidates_from_rows
from .intent import page_profile
from .normalize import normalize
from .quality import query_check, retry_suspected
from .report import build_report, write_report
from .sources import ahrefs_keywords
from .storage import Store, collection_lock, parse_time, utc_now
from .workspace import Workspace


def collect(config: dict, database: Path, *, force: bool = False, client: SearchApi | None = None, api_key: str = "",
            only: set[str] | None = None, labeler=None) -> dict:
    packs.configure(Path(config["rules_dir"]) if config.get("rules_dir") else None)
    summary = {"collected": 0, "skipped": 0, "failed": 0, "requests": 0, "errors": {}}
    settings = config["settings"]
    if only is not None:
        config = config | {"targets": [target for target in config["targets"] if target["id"] in only]}
    with collection_lock(database), Store(database) as store:
        until = settings.get("collect_until")
        if until and datetime.now(UTC) >= parse_time(until):
            summary["skipped"] = len(config["targets"])
            summary["ended"] = until
            print(f"Collection window ended at {until}; nothing collected.", file=sys.stderr)
            return summary
        cap = settings.get("max_total_requests", 0)
        remaining = cap - store.total_requests() if cap else None
        if remaining is not None and remaining <= 0:
            # A study cap is a hard stop, not a failure to retry every few minutes; panels become overdue in the report.
            summary["skipped"] = len(config["targets"])
            summary["budget"] = {"cap": cap, "used": cap - remaining, "exhausted": True}
            print(f"Total request cap reached ({cap - remaining}/{cap}); nothing collected.", file=sys.stderr)
            return summary
        if client is None:
            try:
                client = SearchApi(api_key, settings)
            except ApiError as error:
                # No key: record a failed attempt per panel so the report shows a collection error instead of silence.
                for target in config["targets"]:
                    store.attempt(target, False, error.code, 0)
                    summary["errors"][target["id"]] = error.code
                summary["failed"] = len(config["targets"])
                print(f"Error: {error}", file=sys.stderr)
                return summary
        if remaining is not None:
            client.settings = client.settings | {"max_requests_per_run": min(client.settings["max_requests_per_run"], client.requests + remaining)}
        for target in config["targets"]:
            if store.get_setting(target, "paused") == "1" and not force:
                summary["skipped"] += 1
                continue
            history = store.history(target)
            if history and not force:
                elapsed = (datetime.now(UTC) - parse_time(history[-1]["captured_at"])).total_seconds()
                if elapsed < minimum_spacing_seconds(settings):
                    summary["skipped"] += 1
                    continue
            ledger = {"since": client.requests}
            try:
                # Validate/read local content before the billable request.
                page = page_profile(target.get("page", {}), target["search"]["hl"], utc_now(), allow_fetch=True)
                snapshot = capture(client, store, config, target, page, labeler, history=history, retries=settings.get("retry_query_mismatch", 0),
                                   on_retry=partial(record_attempt, store, client, target, ledger, "query_check_retry"))
                flagged = query_check([*history, snapshot])[snapshot["captured_at"]]["flagged"]
                record_attempt(store, client, target, ledger, "query_mismatch" if flagged else "ok" if snapshot["quality_ok"] else "sparse_results")
                summary["collected"] += 1
            except (ApiError, ValueError, OSError, UnicodeError) as error:
                code = error.code if isinstance(error, ApiError) else "invalid_response_or_page"
                record_attempt(store, client, target, ledger, code, success=False)
                summary["failed"] += 1
                summary["errors"][target["id"]] = code
                print(f"{target['id']}: {code}", file=sys.stderr)
                if code in {"budget_exhausted", "http_401", "http_403", "http_402", "http_429", "rate_limited", "missing_key"}:
                    # Halt the remaining panel on account-wide or rate-limit failures.
                    for remaining_target in config["targets"][config["targets"].index(target) + 1:]:
                        store.attempt(remaining_target, False, f"skipped_after_{code}", 0)
                        summary["failed"] += 1
                        summary["errors"][remaining_target["id"]] = f"skipped_after_{code}"
                    break
        if cap:
            used = store.total_requests()
            summary["budget"] = {"cap": cap, "used": used, "exhausted": used >= cap}
    summary["requests"] = client.requests
    return summary


QUERY_RETRY_PAUSE_SECONDS = 30


def record_attempt(store: Store, client: SearchApi, target: dict, ledger: dict, code: str, success: bool = True) -> None:
    """Each attempt row carries only the requests spent since the previous row, so retries are never counted twice."""
    store.attempt(target, success, code, client.requests - ledger["since"])
    ledger["since"] = client.requests


def capture(client: SearchApi, store: Store, config: dict, target: dict, page: dict | None, labeler=None, *, history: list[dict] | None = None,
            retries: int = 0, on_retry=None) -> dict:
    """One capture of record: search, a local query check, optional AI Overview expansion, normalization, labels, storage.

    When the organic results miss the query terms (observed live: results for one query word), that response is stored as an
    observation without spending an Overview expansion, and after a short pause the search is repeated, at most `retries` times."""
    settings = config["settings"]
    history = list(history or [])
    params = request_params(target["search"], resolve_links=settings["resolve_links"])
    response = client.search(params)
    while retries:
        preview = normalize(response, target["search"], utc_now(), page, settings["min_results"])
        if not retry_suspected(history, preview):
            break
        store.add(target, preview | {"observation": json.loads(json.dumps(preview))}, response)
        if on_retry:
            on_retry()
        retries -= 1
        history.append(preview)
        client.sleep(QUERY_RETRY_PAUSE_SECONDS)
        response = client.search(params)
    expand_ai_overview(client, response, target["search"], settings)
    snapshot = normalize(response, target["search"], utc_now(), page, settings["min_results"])
    observation = json.loads(json.dumps(snapshot))
    if labeler is not None:
        from . import labeling
        labeling.apply(snapshot, labeler, store)
        snapshot["analysis_version"] = config.get("analysis_version", snapshot["analysis_version"])
    snapshot["observation"] = observation
    store.add(target, snapshot, response)
    return snapshot


def expand_ai_overview(client: SearchApi, response: dict, search: dict, settings: dict) -> bool:
    """Google defers most AI Overviews behind a page_token; spend one more request to store what it says and cites."""
    ai = response.get("ai_overview") if isinstance(response, dict) else None
    if settings.get("ai_overview") != "expand" or not spec(search["engine"])["ai_overview"] or not isinstance(ai, dict) or not ai.get("page_token"):
        return False
    try:
        expanded = client.ai_overview(ai["page_token"], resolve_links=settings.get("resolve_links", True))
    except ApiError as error:
        # Keep the token-only status; the organic capture is still valid.
        response["ai_overview"] = {"page_token": ai["page_token"], "expansion_error": error.code}
        return False
    if isinstance(expanded, dict) and expanded.get("text_blocks"):
        response["ai_overview"] = {key: value for key, value in expanded.items() if key != "page_token"}
        return True
    response["ai_overview"] = {key: value for key, value in (expanded if isinstance(expanded, dict) else {}).items()} | {"page_token": ai["page_token"]}
    return False


def run_once(workspace: Workspace, *, config_path: Path | None = None, database: Path | None = None, out: Path | None = None,
             force: bool = False, client: SearchApi | None = None, trigger: str = "cli", only: set[str] | None = None) -> dict:
    """Collect what is due, then always rebuild the report so health states stay visible."""
    config_path = config_path or workspace.config
    database = database or workspace.database
    out = out or workspace.reports
    config = load_config(config_path)
    started = utc_now()
    summary = {"collected": 0, "skipped": 0, "failed": 0, "requests": 0, "errors": {}, "error": None}
    try:
        from .labeling import Labeler
        labeler = Labeler.from_config(config, workspace)
        summary |= collect(config, database, force=force, client=client, api_key=workspace.api_key(), only=only, labeler=labeler)
        if labeler is not None:
            summary["labeling"] = {"requests": labeler.requests, "labelled": labeler.labelled, "errors": labeler.errors}
    except (ApiError, ValueError, OSError) as error:
        summary["error"] = str(error)
    if database.is_file():
        with Store(database) as store:
            store.record_run(started, summary, trigger)
            summary["raw_pruned"] = store.prune_raw(config["settings"]["raw_retention_days"])
            report = build_report(config, store)
            for query in report["queries"]:
                store.sync_case(query)
                store.record_analysis(query)
            report = build_report(config, store)
            write_report(report, out)
            summary["notify"] = notifications.after_run(config, store, report)
            if notifications.digest_due(config, store):
                summary["digest"] = notifications.send_digest(config, store, report)
        summary["report"] = str(out / "index.html")
    workspace.log("run", **{key: value for key, value in summary.items() if key != "report"})
    return summary


def demo(directory: Path) -> dict:
    dataset = json.loads(files("serp_drift").joinpath("assets", "example-data.json").read_text(encoding="utf-8"))
    targets = dataset["targets"]
    for target in targets:
        target["identity"] = search_identity(target["search"])
    config = {"settings": DEFAULTS.copy(), "targets": targets}
    with tempfile.TemporaryDirectory(prefix="serp-drift-demo-") as temporary, Store(Path(temporary) / "demo.sqlite") as store:
        for record in dataset["snapshots"]:
            target = next(target for target in targets if target["id"] == record["target_id"])
            profile = page_profile(target.get("page", {}), target["search"]["hl"], record["captured_at"])
            normalized = normalize(record["response"], target["search"], record["captured_at"], profile, source="synthetic")
            store.add(target, normalized, record["response"])
        report = build_report(config, store, "synthetic")
        write_report(report, directory)
        return report


def init_workspace(workspace: Workspace, *, query: str | None, page: str | None, intent: str | None, gl: str, hl: str, device: str,
                   force: bool = False) -> Path:
    if workspace.config.exists() and not force:
        raise ValueError(f"{workspace.config} already exists. Use --force to overwrite it, or edit the file.")
    workspace.ensure_layout()
    targets = []
    if query:
        target = {"id": slug(query, gl, hl, device), "query": query.strip(), "search": {}}
        if page:
            target["page"] = {"url": page.strip(), "intent": intent or "informational"}
        targets.append(target)
    settings = {"interval_hours": 24, "baseline_size": 3, "confirmations": 2, "min_results": 5, "drift_threshold": 35,
                "max_requests_per_run": 100, "request_delay_seconds": 1, "timeout_seconds": 45, "max_retries": 2}
    text = ("# serp-drift panel. One [[targets]] block per query/market/device. Docs: README.md\n"
            + render_config(settings, {"gl": gl, "hl": hl, "device": device}, targets))
    workspace.config.write_text(text, encoding="utf-8")
    load_config(workspace.config) if targets else None
    return workspace.config


def slug(query: str, gl: str, hl: str, device: str) -> str:
    import re
    base = re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-")[:60] or "query"
    suffix = "" if (gl, hl, device) == ("us", "en", "desktop") else f"-{gl}-{hl}-{device}"
    return (base + suffix)[:80]


def prompt(label: str, default: str = "") -> str:
    if not sys.stdin.isatty():
        return default
    value = input(f"{label}{f' [{default}]' if default else ''}: ").strip()
    return value or default


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="serp-drift", description="SERP Intent Drift Monitor — SearchApi collection, history, and explainable reports.")
    root.add_argument("--version", action="version", version=__version__)
    root.add_argument("--dir", type=Path, default=None, help="Workspace directory (default: $SERP_DRIFT_DIR or the current directory).")
    # --dir is accepted before or after the subcommand; SUPPRESS keeps the subcommand from clearing the global value.
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument("--dir", type=Path, default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    shared.add_argument("--also", dest="dirs", type=Path, action="append", default=argparse.SUPPRESS, help="serve only: an additional project workspace (repeatable).")
    commands = root.add_subparsers(dest="command", required=True, parser_class=lambda **kw: argparse.ArgumentParser(parents=[shared], **kw))

    command = commands.add_parser("backup", help="Consistent SQLite and config backup; excludes API keys.")
    command.add_argument("--out", type=Path, required=True)
    command = commands.add_parser("reanalyze", help="Apply the current drift method to stored observations; no API calls.")
    command.add_argument("--out", type=Path)
    command = commands.add_parser("benchmark", help="Export blind annotation tasks or score human ground truth.")
    command.add_argument("action", choices=["export", "score"])
    command.add_argument("--out", type=Path)
    command.add_argument("--holdout-after", help="YYYY-MM-DD; reserve later captures as temporal holdout.")
    command.add_argument("--sample-results", type=int, help="Keep a fixed, hash-ordered subset of this many result rows.")
    command.add_argument("--latest-windows", action="store_true", help="One window per panel (its newest capture) instead of every capture.")
    command.add_argument("--predictions", type=Path)
    command.add_argument("--labels", type=Path)

    command = commands.add_parser("init", help="Create a workspace: monitor.toml, data/, reports/, logs/, and an optional API key file.")
    command.add_argument("--query", help="First query to monitor.")
    command.add_argument("--page", help="URL of your own page for that query.")
    command.add_argument("--intent", choices=INTENTS, help="Declared intent of that page.")
    command.add_argument("--gl", default="us")
    command.add_argument("--hl", default="en")
    command.add_argument("--device", default="desktop", choices=["desktop", "mobile", "tablet"])
    command.add_argument("--force", action="store_true", help="Overwrite an existing monitor.toml.")
    command.add_argument("--no-prompt", action="store_true", help="Never ask questions; use flags only.")

    command = commands.add_parser("key", help="Store or inspect a key file (0600) used when the environment variable is not set: SearchApi, or Ahrefs for keyword import.")
    command.add_argument("action", choices=["set", "status", "path"])
    command.add_argument("--service", choices=["searchapi", "ahrefs", "labeling"], default="searchapi", help="Which key: searchapi (SEARCHAPI_API_KEY) or ahrefs (AHREFS_API_TOKEN).")

    command = commands.add_parser("import", help="Add panels from a keyword source: a Search Console or query CSV, or the Ahrefs organic-keywords API.")
    command.add_argument("--source", choices=["csv", "ahrefs"], default="csv")
    command.add_argument("--file", help="CSV path for --source csv (default: stdin).")
    command.add_argument("--target", help="Ahrefs target; defaults to the project site.")
    command.add_argument("--country", help="Two-letter country for Ahrefs; defaults to the project gl.")
    command.add_argument("--limit", type=int, default=500, help="Keywords to request from Ahrefs (your plan caps rows per request).")
    command.add_argument("--traffic", action="store_true", help="Also fetch the traffic estimate and order by it (+10 units per row).")
    command.add_argument("--min-volume", type=float, default=0, help="Skip candidates below this volume (Ahrefs) or impressions (CSV).")
    command.add_argument("--max-position", type=float, default=100, help="Skip candidates ranking worse than this.")
    command.add_argument("--exclude-brand", action="store_true", help="Skip branded keywords (the Ahrefs flag, or the site's first label).")
    command.add_argument("--top", type=int, help="Keep the first N candidates after filtering (ordered by traffic, impressions, volume).")
    command.add_argument("--dry-run", action="store_true", help="Print the candidates as JSON; change nothing.")

    command = commands.add_parser("run", help="Collect due panels, then rebuild the report. The command for cron, launchd, and CI.")
    command.add_argument("--force", action="store_true", help="Spend another request even if not due; does not bypass confirmation spacing.")

    for name in ("collect", "report", "watch", "validate", "estimate"):
        command = commands.add_parser(name)
        command.add_argument("--config", type=Path, default=None)
        if name in {"collect", "report", "watch"}:
            command.add_argument("--db", type=Path, default=None)
        if name == "collect":
            command.add_argument("--force", action="store_true", help="Spend another request even if not due; does not bypass confirmation spacing.")
        if name in {"report", "watch"}:
            command.add_argument("--out", type=Path, default=None)
        if name == "watch":
            command.add_argument("--poll-seconds", type=int, default=60)
        if name == "estimate":
            command.add_argument("--days", type=int, default=30)
    command = commands.add_parser("demo", help="Generate a complete synthetic report without an API key.")
    command.add_argument("--out", type=Path, default=Path("reports/demo"))
    commands.add_parser("account", help="Show remaining credits and hourly limits using one account request.")
    commands.add_parser("where", help="Print the resolved workspace paths as JSON.")
    commands.add_parser("rules", help="Show the loaded intent rule packs and the resulting analysis version.")
    command = commands.add_parser("schedule", help="Print or install the launchd (macOS), systemd (Linux), or cron entry that keeps this workspace collecting.")
    command.add_argument("--mode", choices=["app", "run"], default="app", help="app keeps `serve` running with its scheduler; run fires `serp-drift run` once a day.")
    command.add_argument("--time", default="08:17", help="Daily time for run mode (local time of the machine).")
    command.add_argument("--port", type=int, default=8765)
    command.add_argument("--install", action="store_true", help="Write the files and register them.")
    command.add_argument("--uninstall", action="store_true", help="Unregister and remove the files.")
    commands.add_parser("mcp", help="Serve the workspace to an agent over stdio (Model Context Protocol).")
    command = commands.add_parser("export", help="Write the research dataset (captures, results, citations, panels, insights) as CSV/JSON files or one zip.")
    command.add_argument("--out", type=Path, default=Path("exports/serp-drift-dataset"))
    command.add_argument("--days", type=int, default=None, help="Only captures from the last N days (default: everything).")
    command.add_argument("--zip", action="store_true", help="Write a single zip archive instead of a directory.")
    command = commands.add_parser("insights", help="Print cross-panel insights as JSON.")
    command.add_argument("--days", type=int, default=None)
    command = commands.add_parser("digest", help="Summarize the last N days across panels as Markdown, JSON, or an SVG card; optionally post it to the webhook.")
    command.add_argument("--days", type=int, default=7)
    command.add_argument("--format", choices=["markdown", "json", "svg"], default="markdown")
    command.add_argument("--out", type=Path, default=None, help="Write to a file instead of stdout.")
    command.add_argument("--send", action="store_true", help="Post the digest to notify.webhook_url.")
    command = commands.add_parser("serve", help="Run the app: dashboard, history, compare, panel management, and the scheduler in one process.")
    command.add_argument("--projects", type=Path, default=None, help="A directory whose subdirectories are project workspaces; the app can create new ones there.")
    command.add_argument("--host", default="127.0.0.1", help="Bind address. Anything but loopback requires a token and prints one.")
    command.add_argument("--port", type=int, default=8765)
    command.add_argument("--token", default=None, help="Access token; also read from SERP_DRIFT_TOKEN. Optional on loopback.")
    command.add_argument("--poll-seconds", type=int, default=60, help="How often the scheduler checks for due panels.")
    command.add_argument("--no-scheduler", action="store_true", help="Serve the UI without collecting automatically.")
    command.add_argument("--verbose", action="store_true", help="Log every request.")
    command.add_argument("--static", type=Path, default=None, help="Serve an exported report directory instead of the app (demo mode).")
    return root


def import_keywords(workspace: Workspace, args) -> int:
    """`serp-drift import`: fetch or read candidates, filter them, and append panels (or print them with --dry-run)."""
    from .server import ProjectState

    config = load_config(workspace.config)
    search = config.get("search") or {}
    site = (config.get("project") or {}).get("site") or ""
    existing = {target["query"].lower() for target in config["targets"]}
    try:
        if args.source == "ahrefs":
            target = args.target or site
            if not target:
                raise ValueError("Give --target or set [project] site in monitor.toml.")
            fetched = ahrefs_keywords(workspace.api_key("ahrefs"), target, country=args.country or search.get("gl"), limit=args.limit, traffic=args.traffic)
            result = candidates_from_rows(fetched["rows"], fetched["detected"], existing=existing, language=search.get("hl", "en"))
            result["source"] = fetched["source"]
        else:
            text = Path(args.file).read_text(encoding="utf-8") if args.file else sys.stdin.read()
            result = import_candidates(text, existing=existing, language=search.get("hl", "en"))
            result["source"] = {"name": "csv", "file": args.file or "stdin"}
    except ValueError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2
    brand = site.split(".")[0].lower() if site else ""
    picked = []
    for item in result["candidates"]:
        metric = item["volume"] if item["volume"] is not None else item["impressions"]
        if item["existing"] or (metric or 0) < args.min_volume or (item["position"] is not None and item["position"] > args.max_position):
            continue
        if args.exclude_brand and (item["branded"] or (brand and brand in item["query"].lower())):
            continue
        picked.append(item)
    if args.top:
        picked = picked[: args.top]
    if args.dry_run:
        print(json.dumps({"source": result["source"], "total_found": result["total"], "selected": len(picked), "candidates": picked}, indent=2, ensure_ascii=False))
        return 0
    outcome = ProjectState(workspace, workspace.root.name).add_panels([{"query": item["query"]} for item in picked], source=args.source)
    print(f"{len(outcome['created'])} created, {len(outcome['skipped'])} skipped, {len(outcome['errors'])} errors from {result['total']} found. Next: serp-drift run")
    for error in outcome["errors"]:
        print(f"  {error['query']}: {error['error']}", file=sys.stderr)
    return 0 if not outcome["errors"] else 1


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if not hasattr(args, "dirs"):
        args.dirs = []
    workspace = Workspace.resolve(args.dir)
    try:
        packs.configure(workspace.rules)
        if args.command == "backup":
            from .maintenance import backup
            print(json.dumps(backup(workspace, args.out), indent=2))
            return 0
        if args.command == "reanalyze":
            from .maintenance import reanalyze
            print(json.dumps(reanalyze(load_config(workspace.config), workspace, args.out), indent=2))
            return 0
        if args.command == "benchmark":
            from .evaluation import evaluate, export_annotation
            if args.action == "export":
                if not args.out:
                    raise ValueError("benchmark export requires --out <new-directory>.")
                config = load_config(workspace.config)
                with Store(workspace.database) as store:
                    result = export_annotation(config, store, args.out, args.holdout_after, sample_results=args.sample_results, latest_windows=args.latest_windows)
            else:
                if not args.predictions or not args.labels:
                    raise ValueError("benchmark score requires --predictions and --labels.")
                result = evaluate(args.predictions, args.labels)
            print(json.dumps(result, indent=2))
            return 0
        if args.command == "rules":
            print(json.dumps({"analysis_version": packs.registry().analysis_version(), "packs": packs.registry().describe()}, indent=2, ensure_ascii=False))
            return 0
        if args.command == "init":
            target = Workspace(args.dir) if args.dir else Workspace(Workspace.default_init_dir() if not Path("monitor.toml").exists() else Path.cwd())
            query, page, intent = args.query, args.page, args.intent
            if not args.no_prompt and sys.stdin.isatty():
                print(f"Workspace: {target.root}")
                query = query or prompt("First query to monitor (leave empty to add later)")
                if query:
                    page = page or prompt("Your page URL for this query (optional)")
                    if page:
                        intent = intent or prompt("Declared page intent", "informational")
            path = init_workspace(target, query=query, page=page, intent=intent, gl=args.gl, hl=args.hl, device=args.device, force=args.force)
            print(f"Created {path}")
            if not target.api_key() and not args.no_prompt and sys.stdin.isatty():
                value = getpass.getpass("SearchApi API key (hidden, leave empty to set later with `serp-drift key set`): ")
                if value.strip():
                    print(f"Saved {target.save_key(value)}")
            print(f"Next: serp-drift --dir {target.root} run")
            return 0
        if args.command == "key":
            label = {"searchapi": "SearchApi API key", "ahrefs": "Ahrefs API token", "labeling": "Labeling API key"}[args.service]
            if args.action == "set":
                value = getpass.getpass(f"{label} (hidden): ") if sys.stdin.isatty() else sys.stdin.readline()
                print(f"Saved {workspace.save_key(value, args.service)}")
            elif args.action == "path":
                print(workspace.key_path(args.service))
            else:
                print(json.dumps({"service": args.service, "source": workspace.key_source(args.service), "file": str(workspace.key_path(args.service))}))
            return 0
        if args.command == "import":
            return import_keywords(workspace, args)
        if args.command == "where":
            print(json.dumps(workspace.describe(), indent=2))
            return 0
        if args.command == "run":
            summary = run_once(workspace, force=args.force)
            print(json.dumps(summary))
            return 1 if summary["failed"] or summary["error"] else 0
        if args.command == "demo":
            report = demo(args.out)
            print(f"Synthetic demo: {(args.out / 'index.html').resolve()} ({len(report['queries'])} queries)")
            return 0
        if args.command == "serve":
            if not 1024 <= args.port <= 65535:
                raise ValueError("Choose a port between 1024 and 65535.")
            if args.static:
                directory = args.static.resolve()
                if not directory.is_dir() or not (directory / "index.html").is_file():
                    raise ValueError("--static needs a report directory containing index.html (run `serp-drift demo` first).")
                print(f"Report: http://127.0.0.1:{args.port}", flush=True)
                with ThreadingHTTPServer(("127.0.0.1", args.port), partial(SimpleHTTPRequestHandler, directory=str(directory))) as server:
                    server.serve_forever()
                return 0
            if not 5 <= args.poll_seconds <= 3600:
                raise ValueError("poll-seconds must be between 5 and 3600.")
            workspaces = []
            if args.projects:
                root = args.projects.expanduser().resolve()
                root.mkdir(parents=True, exist_ok=True)
                workspaces = [Workspace(child) for child in sorted(root.iterdir()) if (child / "monitor.toml").is_file()]
            elif workspace.exists():
                workspaces = [workspace]
            for extra in (args.dirs or []):
                candidate = Workspace(extra)
                if candidate.root not in {item.root for item in workspaces}:
                    workspaces.append(candidate)
            if not workspaces:
                raise ValueError(f"No monitor.toml in {workspace.root}. Run `serp-drift init --dir {workspace.root}` first, or pass --projects <root>.")
            for item in workspaces:
                if not item.exists():
                    raise ValueError(f"No monitor.toml in {item.root}.")
            from .server import serve as serve_app
            serve_app(workspaces, host=args.host, port=args.port, token=args.token or os.environ.get("SERP_DRIFT_TOKEN") or None,
                      poll_seconds=args.poll_seconds, scheduler_enabled=not args.no_scheduler, verbose=args.verbose, projects_root=args.projects.expanduser().resolve() if args.projects else None)
            return 0
        if args.command == "account":
            print(json.dumps(SearchApi(workspace.api_key(), DEFAULTS).account(), indent=2))
            return 0
        if args.command == "schedule":
            from . import schedule
            if not workspace.exists():
                raise ValueError(f"No monitor.toml in {workspace.root}. Run `serp-drift init` first.")
            plan_data = schedule.plan(workspace, args.mode, time=args.time, port=args.port, extra_dirs=args.dirs)
            if args.install or args.uninstall:
                for line in schedule.apply(plan_data, uninstall=args.uninstall):
                    print(line)
                print("Done. " + ("Check the app or logs/launchd.log." if args.install else "The schedule entry is gone; the workspace is untouched."))
                return 0
            print(f"# {plan_data['platform']} · mode {args.mode}")
            for path, body in plan_data["files"].items():
                print(f"\n# {path}\n{body}")
            if plan_data["install"]:
                print("# install commands:\n" + "\n".join("  " + " ".join(command) for command in plan_data["install"]))
            print(f"# {plan_data['note']}\n# Run again with --install to apply.")
            return 0
        if args.command == "mcp":
            from .mcp import McpServer
            if not workspace.exists():
                raise ValueError(f"No monitor.toml in {workspace.root}. Run `serp-drift init` first.")
            McpServer(workspace).serve()
            return 0
        if args.command in {"export", "insights"}:
            from . import insights as insights_module
            config = load_config(workspace.config)
            if not workspace.database.is_file():
                raise ValueError("No database yet. Run `serp-drift run` first.")
            if args.days is not None and args.days < 1:
                raise ValueError("days must be positive.")
            with Store(workspace.database) as store:
                if args.command == "insights":
                    print(json.dumps(insights_module.compute(config, store, days=args.days), indent=2, ensure_ascii=False))
                    return 0
                files = insights_module.dataset(config, store, days=args.days)
            out = args.out if args.out.is_absolute() else workspace.root / args.out
            if args.zip:
                target = out if out.suffix == ".zip" else out.with_suffix(".zip")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(insights_module.dataset_zip(files))
                print(f"Wrote {target}")
            else:
                out.mkdir(parents=True, exist_ok=True)
                for name, content in files.items():
                    (out / name).write_text(content, encoding="utf-8")
                print(f"Wrote {len(files)} files to {out}")
            return 0
        if args.command == "digest":
            if args.days < 1:
                raise ValueError("days must be positive.")
            config = load_config(workspace.config)
            if not workspace.database.is_file():
                raise ValueError("No database yet. Run `serp-drift run` first.")
            with Store(workspace.database) as store:
                report = build_report(config, store)
                data = notifications.digest(config, store, report, days=args.days)
                text = {"markdown": notifications.digest_markdown(data), "json": json.dumps(data, indent=2, ensure_ascii=False) + "\n", "svg": notifications.digest_svg(data)}[args.format]
                if args.out:
                    args.out.parent.mkdir(parents=True, exist_ok=True)
                    args.out.write_text(text, encoding="utf-8")
                    print(f"Wrote {args.out}")
                else:
                    print(text, end="")
                if args.send:
                    if not config["notify"]["webhook_url"]:
                        raise ValueError("notify.webhook_url is not configured.")
                    print(json.dumps(notifications.send_digest(config, store, report, days=args.days)), file=sys.stderr)
            return 0
        config_path = args.config or workspace.config
        config = load_config(config_path)
        if args.command == "validate":
            for target in config["targets"]:
                page_profile(target.get("page", {}), target["search"]["hl"], utc_now())
            print(f"Valid configuration: {len(config['targets'])} query panels." + ("" if config["targets"] else " Add a [[targets]] entry or import keywords."))
            return 0
        if args.command == "estimate":
            if args.days < 1:
                raise ValueError("days must be positive.")
            runs = math.ceil(args.days * 24 / config["settings"]["interval_hours"])
            requests = len(config["targets"]) * runs
            expandable = sum(1 for target in config["targets"] if spec(target["search"]["engine"])["ai_overview"]) if config["settings"]["ai_overview"] == "expand" else 0
            print(json.dumps({"days": args.days, "query_panels": len(config["targets"]), "runs": runs, "scheduled_search_requests": requests,
                              "ai_overview_expansions_max": expandable * runs, "expected_total_max": requests + expandable * runs,
                              "maximum_with_retries": requests * (config["settings"]["max_retries"] + 1) + expandable * runs,
                              "note": "One credit per request was observed live; expansions happen only when Google returns a token. Not a price guarantee."}, indent=2))
            return 0
        database = args.db or workspace.database
        if args.command == "collect":
            summary = collect(config, database, force=args.force, api_key=workspace.api_key())
            print(json.dumps(summary))
            return 1 if summary["failed"] else 0
        out = args.out or workspace.reports
        if args.command == "report":
            if not database.is_file():
                raise ValueError("Database does not exist. Run collect first, or use demo without an API key.")
            with Store(database) as store:
                write_report(build_report(config, store), out)
            print(f"Report: {(out / 'index.html').resolve()}")
            return 0
        if args.command == "watch":
            if not 5 <= args.poll_seconds <= 3600:
                raise ValueError("poll-seconds must be between 5 and 3600.")
            while True:
                summary = run_once(workspace, config_path=config_path, database=database, out=out)
                print(json.dumps({"at": utc_now(), **summary}), flush=True)
                # Avoid resetting the retry budget in a busy loop after a failure.
                if summary["failed"] or summary["error"]:
                    print("Collection failed; report updated. Fix the error before restarting watch.", file=sys.stderr)
                    return 1
                time.sleep(args.poll_seconds)
    except KeyboardInterrupt:
        print("Stopped.", file=sys.stderr)
        return 130
    except (ApiError, ValueError, OSError, sqlite3.Error) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0
