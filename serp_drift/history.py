"""History views over stored captures: timelines, URL trajectories, change logs, and period comparisons."""

from datetime import timedelta
from itertools import pairwise

from .analysis import average_distribution, compare_sets
from .normalize import canonical_url, dominant
from .storage import parse_time

PRESETS = ("baseline", "latest", "last_7_days", "previous_7_days", "last_30_days", "first_week")


def page_position(snapshot: dict, page_url: str | None) -> int | None:
    if not page_url:
        return None
    url = canonical_url(page_url)
    return next((item["position"] for item in snapshot["results"] if item["url"] == url), None)


def host_of(url: str) -> str:
    from urllib.parse import urlsplit
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


def on_site(url: str, site: str | None) -> bool:
    if not site:
        return False
    host = host_of(url)
    return host == site or host.endswith("." + site)


def site_hit(snapshot: dict, site: str | None) -> dict | None:
    """The best-ranking result on the project's site in this capture, if any."""
    hits = [result for result in snapshot["results"] if on_site(result["url"], site)]
    if not hits:
        return None
    best = min(hits, key=lambda result: result["position"])
    return {"position": best["position"], "url": best["url"], "title": best["title"], "count": len(hits)}


def site_cited(snapshot: dict, site: str | None) -> bool:
    summary = snapshot.get("ai_overview") or {}
    return any(host == site or host.endswith("." + site) for host in summary.get("cited_hosts", [])) if site else False


def timeline(snapshots: list[dict], baseline: list[dict], page_url: str | None = None, site: str | None = None) -> list[dict]:
    """One row per capture. Scores compare against the supplied baseline once it exists."""
    anchor_time = parse_time(baseline[-1]["captured_at"]) if baseline else None
    rows = []
    for snapshot in snapshots:
        after = anchor_time is not None and parse_time(snapshot["captured_at"]) > anchor_time
        hit = site_hit(snapshot, site)
        rows.append({
            "captured_at": snapshot["captured_at"], "intent": snapshot["dominant_intent"], "coverage": snapshot["classified_coverage"],
            "quality_ok": snapshot["quality_ok"], "results": len(snapshot["results"]), "features": snapshot["features"],
            "ai_overview_status": snapshot.get("ai_overview_status"), "page_position": page_position(snapshot, page_url),
            "site_position": hit["position"] if hit else None, "site_url": hit["url"] if hit else None,
            "site_cited": site_cited(snapshot, site), "ai_references": (snapshot.get("ai_overview") or {}).get("references"),
            "score": compare_sets(baseline, [snapshot])["score"] if after and snapshot["quality_ok"] else None,
            "phase": "monitoring" if after else "baseline",
        })
    return rows


def url_trajectories(snapshots: list[dict], site: str | None = None) -> dict:
    """Every URL ever observed in the panel with its position per capture (null when absent)."""
    captures = [snapshot["captured_at"] for snapshot in snapshots]
    urls: dict[str, dict] = {}
    for index, snapshot in enumerate(snapshots):
        for result in snapshot["results"]:
            entry = urls.setdefault(result["url"], {"url": result["url"], "title": result["title"], "positions": [None] * len(captures),
                                                    "intent": result["intent"], "type": result["type"], "first_seen": snapshot["captured_at"],
                                                    "mine": on_site(result["url"], site)})
            entry["positions"][index] = result["position"]
            entry["title"] = result["title"] or entry["title"]
            entry["intent"], entry["type"] = result["intent"], result["type"]
            entry["last_seen"] = snapshot["captured_at"]
    rows = []
    for entry in urls.values():
        seen = [position for position in entry["positions"] if position is not None]
        entry |= {"appearances": len(seen), "best": min(seen), "average": round(sum(seen) / len(seen), 1), "current": entry["positions"][-1] if captures else None}
        rows.append(entry)
    rows.sort(key=lambda entry: (entry["current"] is None, entry["current"] or 0, -entry["appearances"], entry["url"]))
    return {"captures": captures, "urls": rows}


def change_log(snapshots: list[dict], page_url: str | None = None, site: str | None = None) -> list[dict]:
    """What changed between consecutive captures, newest first."""
    log = []
    for previous, current in pairwise(snapshots):
        old = {result["url"]: result["position"] for result in previous["results"]}
        new = {result["url"]: result["position"] for result in current["results"]}
        moved = [{"url": url, "before": old[url], "after": new[url]} for url in old.keys() & new.keys() if old[url] != new[url]]
        before_hit, after_hit = site_hit(previous, site), site_hit(current, site)
        entry = {
            "site_before": before_hit, "site_after": after_hit,
            "ranking_url_changed": bool(before_hit and after_hit and before_hit["url"] != after_hit["url"]),
            "captured_at": current["captured_at"], "previous_at": previous["captured_at"],
            "entered": sorted(new.keys() - old.keys()), "exited": sorted(old.keys() - new.keys()),
            "moved": sorted(moved, key=lambda item: item["after"]),
            "features_added": sorted(set(current["features"]) - set(previous["features"])),
            "features_removed": sorted(set(previous["features"]) - set(current["features"])),
            "intent_before": previous["dominant_intent"], "intent_after": current["dominant_intent"],
            "page_before": page_position(previous, page_url), "page_after": page_position(current, page_url),
            "score": compare_sets([previous], [current])["score"],
        }
        entry["quiet"] = not (entry["entered"] or entry["exited"] or entry["moved"] or entry["features_added"] or entry["features_removed"]
                              or entry["intent_before"] != entry["intent_after"] or entry["page_before"] != entry["page_after"]
                              or entry["ranking_url_changed"])
        log.append(entry)
    log.reverse()
    return log


def resolve_side(snapshots: list[dict], spec: dict, baseline: list[dict]) -> list[dict]:
    """A side is a preset, one capture (`capture`), or a closed date range (`from`/`to`, ISO dates or timestamps)."""
    if not snapshots:
        return []
    latest = parse_time(snapshots[-1]["captured_at"])
    preset = spec.get("preset")
    if preset == "baseline":
        return list(baseline)
    if preset == "latest":
        return snapshots[-1:]
    if preset == "last_7_days":
        return window(snapshots, latest - timedelta(days=7), latest)
    if preset == "previous_7_days":
        return window(snapshots, latest - timedelta(days=14), latest - timedelta(days=7), exclusive_end=True)
    if preset == "last_30_days":
        return window(snapshots, latest - timedelta(days=30), latest)
    if preset == "first_week":
        first = parse_time(snapshots[0]["captured_at"])
        return window(snapshots, first, first + timedelta(days=7))
    if spec.get("capture"):
        wanted = parse_time(spec["capture"])
        return [snapshot for snapshot in snapshots if parse_time(snapshot["captured_at"]) == wanted]
    if spec.get("from") or spec.get("to"):
        start = parse_time(expand_date(spec.get("from"), end=False)) if spec.get("from") else parse_time(snapshots[0]["captured_at"])
        end = parse_time(expand_date(spec.get("to"), end=True)) if spec.get("to") else latest
        return window(snapshots, start, end)
    raise ValueError(f"Unknown comparison side; use a preset ({', '.join(PRESETS)}), a capture timestamp, or from/to dates.")


def expand_date(value: str, *, end: bool) -> str:
    return f"{value}T23:59:59.999999Z" if end and len(value) == 10 else f"{value}T00:00:00Z" if len(value) == 10 else value


def window(snapshots: list[dict], start, end, *, exclusive_end: bool = False) -> list[dict]:
    return [snapshot for snapshot in snapshots
            if start <= parse_time(snapshot["captured_at"]) and (parse_time(snapshot["captured_at"]) < end if exclusive_end else parse_time(snapshot["captured_at"]) <= end)]


def compare_specs(snapshots: list[dict], baseline: list[dict], left_spec: dict, right_spec: dict) -> dict:
    left = [snapshot for snapshot in resolve_side(snapshots, left_spec, baseline) if snapshot["quality_ok"]]
    right = [snapshot for snapshot in resolve_side(snapshots, right_spec, baseline) if snapshot["quality_ok"]]
    if not left or not right:
        raise ValueError("Both sides need at least one usable capture.")
    return compare_sets(left, right) | {"left_spec": left_spec, "right_spec": right_spec}


def citations(snapshots: list[dict], site: str | None = None) -> dict:
    """AI Overview presence and cited hosts per capture, plus how often each host was cited across the panel."""
    rows, counts = [], {}
    for snapshot in snapshots:
        summary = snapshot.get("ai_overview") or {}
        rows.append({"captured_at": snapshot["captured_at"], "status": snapshot.get("ai_overview_status"), "references": summary.get("references", 0),
                     "cited_hosts": summary.get("cited_hosts", []), "page_cited": summary.get("page_cited", False), "host_cited": summary.get("host_cited", False),
                     "site_cited": site_cited(snapshot, site), "excerpt": summary.get("excerpt", ""), "quality_ok": snapshot["quality_ok"]})
        for host in summary.get("cited_hosts", []):
            counts[host] = counts.get(host, 0) + 1
    observed = [row for row in rows if row["status"] == "observed"]
    references = [row["references"] for row in observed if row["references"]]
    return {"captures": rows, "observed": len(observed), "total": len(rows),
            "hosts": sorted(({"host": host, "citations": count, "mine": bool(site and (host == site or host.endswith("." + site)))} for host, count in counts.items()), key=lambda item: (-item["citations"], item["host"])),
            "page_cited": sum(1 for row in observed if row["page_cited"]), "host_cited": sum(1 for row in observed if row["host_cited"]),
            "site_cited": sum(1 for row in observed if row["site_cited"]),
            "references_per_overview": round(sum(references) / len(references), 1) if references else None}


def intent_stability(snapshots: list[dict]) -> dict:
    """How often the dominant estimate held across captures; a descriptive number, not an accuracy claim."""
    labels = [snapshot["dominant_intent"] for snapshot in snapshots if snapshot["quality_ok"]]
    if not labels:
        return {"captures": 0, "stability": None, "modal": "unknown"}
    modal = max(set(labels), key=labels.count)
    return {"captures": len(labels), "stability": round(labels.count(modal) / len(labels), 3), "modal": modal,
            "overall": dominant(average_distribution([snapshot for snapshot in snapshots if snapshot["quality_ok"]], "intent_distribution"))}
