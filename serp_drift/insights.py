"""Cross-panel insights and a research dataset export. Descriptive statistics over stored captures, nothing inferred."""

import csv
from datetime import UTC, datetime, timedelta
import io
from itertools import pairwise
import json
from statistics import mean, median
import zipfile

from . import __version__, analysis_version
from .analysis import jaccard_distance
from .history import page_position
from .normalize import FEATURES
from .report import csv_cell
from .storage import Store, parse_time, utc_now


def panel_metrics(target: dict, snapshots: list[dict]) -> dict:
    usable = [snapshot for snapshot in snapshots if snapshot["quality_ok"]]
    page_url = (target.get("page") or {}).get("url")
    turnover, rank_moves, feature_changes = [], [], []
    for previous, current in pairwise(usable):
        old = {result["url"]: result["position"] for result in previous["results"]}
        new = {result["url"]: result["position"] for result in current["results"]}
        turnover.append(jaccard_distance(set(old), set(new)))
        common = old.keys() & new.keys()
        if common:
            rank_moves.append(mean(abs(old[url] - new[url]) for url in common))
        feature_changes.append(jaccard_distance(set(previous["features"]), set(current["features"])))
    observed = [snapshot for snapshot in snapshots if snapshot.get("ai_overview_status") == "observed"]
    cited = [snapshot for snapshot in observed if (snapshot.get("ai_overview") or {}).get("page_cited")]
    labels = [snapshot["dominant_intent"] for snapshot in usable]
    modal = max(set(labels), key=labels.count) if labels else "unknown"
    positions = [page_position(snapshot, page_url) for snapshot in usable] if page_url else []
    seen = [position for position in positions if position]
    return {
        "id": target["id"], "query": target["query"], "search": target["search"], "captures": len(snapshots), "usable": len(usable),
        "ai_overview_observed": len(observed), "ai_overview_share": round(len(observed) / len(snapshots), 3) if snapshots else None,
        "page_cited": len(cited), "page_url": page_url,
        "turnover": round(mean(turnover), 3) if turnover else None, "rank_movement": round(mean(rank_moves), 2) if rank_moves else None,
        "feature_volatility": round(mean(feature_changes), 3) if feature_changes else None,
        "intent": modal, "intent_stability": round(labels.count(modal) / len(labels), 3) if labels else None,
        "coverage": round(mean(snapshot["classified_coverage"] for snapshot in usable), 3) if usable else None,
        "page_position": positions[-1] if positions else None, "page_best": min(seen) if seen else None,
        "page_in_top_10": round(len(seen) / len(positions), 3) if positions else None,
        "features": sorted({feature for snapshot in snapshots for feature in snapshot["features"]}),
    }


def _share(values: list[float | None]) -> float | None:
    known = [value for value in values if value is not None]
    return round(mean(known), 3) if known else None


def compute(config: dict, store: Store, *, days: int | None = None, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    since = now - timedelta(days=days) if days else None
    panels, feature_counts, host_counts, host_panels, captures_total = [], {key: 0 for key in FEATURES}, {}, {}, 0
    groups: dict[str, dict[str, list]] = {"language": {}, "device": {}, "engine": {}}
    for target in config["targets"]:
        snapshots = store.history(target)
        if since:
            snapshots = [snapshot for snapshot in snapshots if parse_time(snapshot["captured_at"]) >= since]
        if not snapshots:
            continue
        metrics = panel_metrics(target, snapshots)
        panels.append(metrics)
        captures_total += len(snapshots)
        for snapshot in snapshots:
            for feature in snapshot["features"]:
                feature_counts[feature] = feature_counts.get(feature, 0) + 1
            for host in (snapshot.get("ai_overview") or {}).get("cited_hosts", []):
                host_counts[host] = host_counts.get(host, 0) + 1
                host_panels.setdefault(host, set()).add(target["id"])
        search = target["search"]
        for name, key in (("language", search.get("hl", "").split("-")[0]), ("device", search.get("device", "n/a")), ("engine", search.get("engine", "google"))):
            groups[name].setdefault(key, []).append(metrics)
    def summarize(items: list[dict]) -> dict:
        return {"panels": len(items), "captures": sum(item["captures"] for item in items), "ai_overview_share": _share([item["ai_overview_share"] for item in items]),
                "turnover": _share([item["turnover"] for item in items]), "coverage": _share([item["coverage"] for item in items]),
                "intent_known": round(sum(1 for item in items if item["intent"] not in {"unknown", "mixed"}) / len(items), 3) if items else None}
    intents: dict[str, int] = {}
    for item in panels:
        intents[item["intent"]] = intents.get(item["intent"], 0) + 1
    hosts = sorted(({"host": host, "citations": count, "panels": len(host_panels[host])} for host, count in host_counts.items()), key=lambda item: (-item["citations"], item["host"]))
    return {
        "generated_at": utc_now(), "version": __version__, "analysis_version": analysis_version(), "days": days,
        "panels": len(panels), "captures": captures_total, "overall": summarize(panels), "intents": intents,
        "coverage_median": round(median([item["coverage"] for item in panels if item["coverage"] is not None]), 3) if any(item["coverage"] is not None for item in panels) else None,
        "features": sorted(({"feature": key, "captures": count, "share": round(count / captures_total, 3) if captures_total else None} for key, count in feature_counts.items() if count), key=lambda item: -item["captures"]),
        "hosts": hosts[:25], "by": {name: {key: summarize(items) for key, items in sorted(values.items())} for name, values in groups.items()},
        "most_volatile": sorted([item for item in panels if item["turnover"] is not None], key=lambda item: -item["turnover"])[:10],
        "most_stable": sorted([item for item in panels if item["turnover"] is not None], key=lambda item: item["turnover"])[:10],
        "your_pages": {"tracked": sum(1 for item in panels if item["page_url"]), "in_top_10_now": sum(1 for item in panels if item["page_position"]),
                       "cited_captures": sum(item["page_cited"] for item in panels)},
        "panel_metrics": panels,
    }


def dataset(config: dict, store: Store, *, days: int | None = None, now: datetime | None = None) -> dict[str, str]:
    """CSV/JSON files for research: one row per capture, per ranked result, and per citation, plus panel metadata."""
    now = now or datetime.now(UTC)
    since = now - timedelta(days=days) if days else None
    captures, results, citations, panels = io.StringIO(newline=""), io.StringIO(newline=""), io.StringIO(newline=""), []
    c_writer, r_writer, ci_writer = csv.writer(captures), csv.writer(results), csv.writer(citations)
    c_writer.writerow(["panel", "query", "engine", "gl", "hl", "device", "location", "captured_at", "results", "dominant_intent", "classified_coverage", "features", "ai_overview_status", "ai_references", "ai_cited_hosts", "page_position", "page_cited", "quality_ok", "quality_state"])
    r_writer.writerow(["panel", "captured_at", "position", "url", "host", "title", "intent", "type", "confidence"])
    ci_writer.writerow(["panel", "captured_at", "host", "url"])
    for target in config["targets"]:
        snapshots = store.history(target)
        if since:
            snapshots = [snapshot for snapshot in snapshots if parse_time(snapshot["captured_at"]) >= since]
        search = target["search"]
        page_url = (target.get("page") or {}).get("url")
        panels.append({"id": target["id"], "query": target["query"], "search": search, "page": target.get("page"), "identity": target["identity"], "captures": len(snapshots)})
        for snapshot in snapshots:
            summary = snapshot.get("ai_overview") or {}
            c_writer.writerow(map(csv_cell, [target["id"], target["query"], search.get("engine"), search.get("gl"), search.get("hl"), search.get("device", ""), search.get("location", ""),
                                             snapshot["captured_at"], len(snapshot["results"]), snapshot["dominant_intent"], snapshot["classified_coverage"], "|".join(snapshot["features"]),
                                             snapshot.get("ai_overview_status"), summary.get("references", ""), "|".join(summary.get("cited_hosts", [])),
                                             page_position(snapshot, page_url) or "", summary.get("page_cited", ""), snapshot["quality_ok"],
                                             (snapshot.get("quality") or {}).get("state", "legacy")]))
            for result in snapshot["results"]:
                r_writer.writerow(map(csv_cell, [target["id"], snapshot["captured_at"], result["position"], result["url"], result["url"].split("/")[2].removeprefix("www."), result["title"], result["intent"], result["type"], result.get("confidence", "")]))
            for url in summary.get("cited_urls", []):
                ci_writer.writerow(map(csv_cell, [target["id"], snapshot["captured_at"], url.split("/")[2].removeprefix("www."), url]))
    readme = (f"# serp-drift dataset\n\nGenerated {utc_now()} by serp-drift {__version__} (rules {analysis_version()}).\n\n"
              "- captures.csv: one row per stored capture.\n- results.csv: one row per ranked result (top 10) with the rule-based intent and type.\n"
              "- citations.csv: one row per URL cited by an expanded AI Overview.\n- panels.json: the panel definitions.\n- insights.json: the cross-panel summary.\n\n"
              "Intent labels are lexical estimates, not measured user intent. Read docs/methodology.md before drawing conclusions.\n")
    return {"captures.csv": captures.getvalue(), "results.csv": results.getvalue(), "citations.csv": citations.getvalue(),
            "panels.json": json.dumps(panels, indent=2, ensure_ascii=False) + "\n",
            "insights.json": json.dumps(compute(config, store, days=days, now=now), indent=2, ensure_ascii=False) + "\n", "README.md": readme}


def dataset_zip(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(f"serp-drift-dataset/{name}", content)
    return buffer.getvalue()
