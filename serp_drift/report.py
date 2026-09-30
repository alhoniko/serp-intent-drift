"""Self-contained HTML plus JSON/CSV exports. No live API in the browser."""

import csv
from importlib.resources import files
import json
import os
from pathlib import Path
import tempfile

from . import __version__, analysis_version
from .analysis import WEIGHTS, analyze
from .storage import Store, utc_now


def build_report(config: dict, store: Store, source: str = "searchapi") -> dict:
    from .scheduler import budget_exhausted
    site = (config.get("project") or {}).get("site") or None
    ended = source == "searchapi" and budget_exhausted(config, store)
    queries = []
    for target in config["targets"]:
        settings = store.panel_settings(target) if source == "searchapi" else {}
        query = analyze(target, store.history(target, source), config["settings"], last_attempt=store.last_attempt(target) if source == "searchapi" else None,
                        baseline_from=settings.get("baseline_from"), site=site, ended=ended)
        query["reviews"] = store.cases(target) if source == "searchapi" else []
        query["group"] = settings.get("group", "")
        query["paused"] = settings.get("paused") == "1"
        query["acknowledged_at"] = settings.get("acknowledged_at")
        if ended:
            # Collection stopped on purpose (request cap or end date): the last status stands and the observations are final, not overdue.
            query["collection_ended"] = True
            query["reasons"].append("Collection ended (request cap or end date reached); these are the final observations.")
            query["decision"] = query["decision"] | {"next_action": "Read the final observations; no new capture will arrive.", "reasons": query["reasons"]}
        queries.append(query)
    return {"schema_version": 1, "version": __version__, "analysis_version": config.get("analysis_version") or analysis_version(),
            "generated_at": utc_now(), "source": source, "synthetic": source == "synthetic", "weights": WEIGHTS,
            "project": config.get("project") or {"name": "", "site": ""}, "search": config.get("search"),
            "queries": queries, "disclosure": "Developed for a paid SearchApi collaboration. Synthetic examples demonstrate behavior, not measured search trends."}


def csv_cell(value: object) -> str:
    text = "" if value is None else str(value)
    # Prevent spreadsheet formula execution in query/page fields.
    return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r")) else text


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(text)
        os.replace(temporary, path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


def write_report(report: dict, directory: Path) -> None:
    import io
    assets = files("serp_drift").joinpath("assets")
    serialized = json.dumps(report, ensure_ascii=False, allow_nan=False)
    embedded = serialized.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    html = assets.joinpath("report.html").read_text(encoding="utf-8")
    html = html.replace("/* REPORT_STYLES */", assets.joinpath("report.css").read_text(encoding="utf-8"))
    html = html.replace("/* RENDER_SCRIPT */", assets.joinpath("render.js").read_text(encoding="utf-8"))
    html = html.replace("/* REPORT_SCRIPT */", assets.joinpath("report.js").read_text(encoding="utf-8"))
    html = html.replace("REPORT_DATA_JSON", embedded)
    atomic_write(directory / "index.html", html)
    atomic_write(directory / "report.json", json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(["query", "country", "language", "device", "status", "drift_score", "baseline_intent", "current_intent", "page_mismatch", "captured_at", "source"])
    for query in report["queries"]:
        latest = query["latest"] or {}
        writer.writerow(map(csv_cell, [query["query"], query["search"]["gl"], query["search"]["hl"], query["search"].get("device", ""), query["status"], query["score"], query["baseline_intent"], latest.get("dominant_intent"), query["confirmed_mismatch"], latest.get("captured_at"), report["source"]]))
    atomic_write(directory / "report.csv", buffer.getvalue())

