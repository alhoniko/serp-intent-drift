"""Compare a fixed initial baseline to later captures; expose every score component."""

from datetime import UTC, datetime
import hashlib
from itertools import pairwise
import json
from statistics import mean

from .config import minimum_spacing_seconds
from .normalize import canonical_url, dominant
from .storage import parse_time

ANALYSIS_VERSION = "drift-v4"
# States that describe something other than this panel's SERP. Sparse captures ("insufficient") are real observations and stay samples.
INVALID_STATES = {"quarantined", "excluded", "query_mismatch"}

WEIGHTS = {"intent": 0.35, "url_turnover": 0.25, "result_types": 0.20, "rank_movement": 0.10, "features": 0.10}


def tvd(left: dict, right: dict) -> float:
    return sum(abs(left.get(key, 0) - right.get(key, 0)) for key in left.keys() | right.keys()) / 2


def jaccard_distance(left: set, right: set) -> float:
    return 1 - len(left & right) / len(left | right) if left | right else 0.0


def average_distribution(snapshots: list[dict], field: str) -> dict:
    labels = set().union(*(snapshot[field] for snapshot in snapshots))
    return {label: mean(snapshot[field].get(label, 0.0) for snapshot in snapshots) for label in labels}


def side_summary(snapshots: list[dict]) -> dict:
    return {"from": snapshots[0]["captured_at"], "to": snapshots[-1]["captured_at"], "captures": len(snapshots),
            "dominant_intent": dominant(average_distribution(snapshots, "intent_distribution"))}


def compare_sets(left: list[dict], right: list[dict]) -> dict:
    """Compare two capture sets using distributions, frequency-weighted membership and mean ranks.

    A baseline-versus-latest comparison is the special case where the right side has one capture."""
    def frequencies(captures, field):
        values = [set(item["url"] for item in capture["results"]) if field == "urls" else set(capture["features"]) for capture in captures]
        return {key: sum(key in value for value in values) / len(values) for key in set().union(*values)}

    def weighted_distance(a, b):
        keys = a.keys() | b.keys()
        total = sum(max(a.get(k, 0), b.get(k, 0)) for k in keys)
        return 1 - sum(min(a.get(k, 0), b.get(k, 0)) for k in keys) / total if total else 0.0

    def ranks(captures):
        urls = set().union(*(set(item["url"] for item in capture["results"]) for capture in captures))
        return {url: mean(item["position"] for capture in captures for item in capture["results"] if item["url"] == url) for url in urls}

    old, new = ranks(left), ranks(right)
    common = old.keys() & new.keys()
    rank = mean(abs(old[url] - new[url]) / 9 for url in common) if len(common) >= 2 else None
    components = {
        "intent": tvd(average_distribution(left, "intent_distribution"), average_distribution(right, "intent_distribution")),
        "url_turnover": weighted_distance(frequencies(left, "urls"), frequencies(right, "urls")),
        "result_types": tvd(average_distribution(left, "type_distribution"), average_distribution(right, "type_distribution")),
        "rank_movement": rank,
        "features": weighted_distance(frequencies(left, "features"), frequencies(right, "features")),
    }
    score = sum(WEIGHTS[key] * (value or 0.0) for key, value in components.items()) * 100
    return {
        "method": ANALYSIS_VERSION, "membership_basis": "frequency across every eligible capture in each period", "score": round(score, 1), "components": {key: round(value, 4) if value is not None else None for key, value in components.items()},
        "entered": sorted(new.keys() - old.keys()), "exited": sorted(old.keys() - new.keys()),
        "rank_changes": [{"url": url, "before": old[url], "after": new[url], "delta": old[url] - new[url]} for url in sorted(common, key=lambda url: new[url])],
        "features_added": sorted(frequencies(right, "features").keys() - frequencies(left, "features").keys()),
        "features_removed": sorted(frequencies(left, "features").keys() - frequencies(right, "features").keys()),
        "shared_urls": len(common),
        "left": side_summary(left), "right": side_summary(right),
    }


def compare(baseline: list[dict], current: dict) -> dict:
    return compare_sets(baseline, [current])


def mismatch(snapshot: dict, page: dict | None = None) -> bool:
    page = page or snapshot.get("page")
    intent = snapshot["dominant_intent"]
    if not page or page["intent"] == "unknown" or intent in {"unknown", "mixed"}:
        return False
    return page["intent"] != intent and snapshot["intent_distribution"].get(page["intent"], 0) < 0.25


def analyze(target: dict, snapshots: list[dict], settings: dict, *, now: datetime | None = None, last_attempt: dict | None = None,
            baseline_from: str | None = None, site: str | None = None) -> dict:
    """Fixed-baseline analysis. `baseline_from` re-anchors the panel: captures before it stay in history but leave this analysis."""
    now = now or datetime.now(UTC)
    all_snapshots = snapshots
    if baseline_from:
        anchor_start = parse_time(baseline_from)
        snapshots = [snapshot for snapshot in snapshots if parse_time(snapshot["captured_at"]) >= anchor_start]
    result = {
        "id": target["id"], "query": target["query"], "search": target["search"], "identity": target["identity"],
        "method": ANALYSIS_VERSION, "status": "awaiting_data", "score": None, "baseline": [], "latest": snapshots[-1] if snapshots else None,
        "timeline": [], "comparison": None, "baseline_intent": "unknown", "confirmed_mismatch": False,
        "confirmed_intent_shift": False, "reasons": [], "snapshot_count": len(snapshots), "last_attempt": last_attempt, "baseline_from": baseline_from,
        "settings": {key: settings[key] for key in ("baseline_size", "confirmations", "min_results", "interval_hours", "drift_threshold")},
    }
    if not snapshots:
        result["reasons"].append("Collect the first SERP snapshot to start a baseline." if not baseline_from else f"No captures since the chosen baseline start {baseline_from[:10]}.")
        if last_attempt and not last_attempt["success"]:
            result["status"] = "collection_error"
            result["reasons"] = [f"Latest collection failed: {last_attempt['code']}."]
        return explain(result, snapshots, settings)
    # Forced same-day runs cannot manufacture independent confirmation samples. Invalid observations (another query or market,
    # a human exclusion) are not samples of this panel, so they neither count nor block the next valid capture in the interval.
    sampled = []
    interval = settings["interval_hours"] * 3600
    for snapshot in snapshots:
        if snapshot.get("quality", {}).get("state") in INVALID_STATES:
            continue
        if not sampled or (parse_time(snapshot["captured_at"]) - parse_time(sampled[-1]["captured_at"])).total_seconds() >= minimum_spacing_seconds(settings):
            sampled.append(snapshot)
    invalid = [snapshot for snapshot in snapshots if snapshot.get("quality", {}).get("state") in INVALID_STATES]
    eligible = [snapshot for snapshot in sampled if snapshot["quality_ok"]]
    baseline = eligible[:settings["baseline_size"]]
    result["baseline"] = baseline
    # A capture of another query is a failed collection: status comes from the newest capture that describes this panel,
    # and wall-clock staleness from that capture's age. Quarantined or excluded captures still stop the analysis for review.
    rejected = []
    while len(snapshots) > len(rejected) + 1 and snapshots[-1 - len(rejected)].get("quality", {}).get("state") == "query_mismatch":
        rejected.insert(0, snapshots[-1 - len(rejected)])
    latest = snapshots[-1 - len(rejected)]
    result["latest"] = latest
    result["rejected_after_latest"] = [snapshot["captured_at"] for snapshot in rejected]
    if len(baseline) < settings["baseline_size"]:
        result["status"] = "building_baseline"
        result["reasons"].append(f"Baseline: {len(baseline)}/{settings['baseline_size']} eligible, spaced captures.")
    else:
        base_intent = dominant(average_distribution(baseline, "intent_distribution"))
        result["baseline_intent"] = base_intent
        anchor_time = parse_time(baseline[-1]["captured_at"])
        post_baseline = [snapshot for snapshot in sampled if parse_time(snapshot["captured_at"]) > anchor_time]
        for snapshot in sorted([*sampled, *invalid], key=lambda item: item["captured_at"]):
            after_baseline = parse_time(snapshot["captured_at"]) > anchor_time
            result["timeline"].append({"captured_at": snapshot["captured_at"], "intent": snapshot["dominant_intent"],
                                       "score": compare(baseline, snapshot)["score"] if after_baseline and snapshot["quality_ok"] else None,
                                       "quality_ok": snapshot["quality_ok"], "quality_state": snapshot.get("quality", {}).get("state"),
                                       "phase": "monitoring" if after_baseline else "baseline"})
        if post_baseline and latest["quality_ok"]:
            comparison = compare(baseline, latest)
            result["comparison"] = comparison
            result["score"] = comparison["score"]
            tail = post_baseline[-settings["confirmations"]:]
            latest_is_sample = latest["captured_at"] == sampled[-1]["captured_at"]
            consecutive = len(tail) == settings["confirmations"] and latest_is_sample and all(item["quality_ok"] for item in tail)
            consecutive = consecutive and all((parse_time(right["captured_at"]) - parse_time(left["captured_at"])).total_seconds() <= interval * 1.75 for left, right in pairwise(tail))
            consecutive = consecutive and len({item.get("analysis_version") for item in [*baseline, *tail]}) == 1
            consecutive = consecutive and all(not item.get("labeling", {}).get("errors") for item in [*baseline, *tail])
            intent_delta = tvd(average_distribution(baseline, "intent_distribution"), latest["intent_distribution"])
            page = latest.get("page")
            result["confirmed_mismatch"] = bool(consecutive and page and all(mismatch(snapshot, page) and snapshot["dominant_intent"] == latest["dominant_intent"] for snapshot in tail))
            result["confirmed_intent_shift"] = bool(consecutive and base_intent not in {"unknown", "mixed"}
                and latest["dominant_intent"] not in {"unknown", "mixed", base_intent}
                and intent_delta >= 0.20
                and all(snapshot["dominant_intent"] == latest["dominant_intent"] for snapshot in tail))
            candidate = mismatch(latest) or (base_intent not in {"unknown", "mixed"} and latest["dominant_intent"] not in {base_intent, "unknown", "mixed"})
            if result["confirmed_mismatch"] or result["confirmed_intent_shift"]:
                result["status"] = "review"
            elif candidate or comparison["score"] >= settings["drift_threshold"]:
                result["status"] = "watch"
            else:
                result["status"] = "stable"
            result["confirmed_recovery"] = bool(consecutive and all(not mismatch(item) and item["dominant_intent"] == base_intent
                and base_intent not in {"unknown", "mixed"} and compare(baseline, item)["score"] < settings["drift_threshold"] for item in tail))
            if result["confirmed_mismatch"]:
                result["reasons"].append(f"The supplied {page['intent']} page profile conflicts with {latest['dominant_intent']} SERPs across {len(tail)} captures. Review the page and the live results.")
            elif mismatch(latest):
                result["reasons"].append("Possible page-profile mismatch; waiting for spaced confirmation captures.")
            if result["confirmed_intent_shift"]:
                result["reasons"].append(f"Estimated dominant intent changed from {base_intent} to {latest['dominant_intent']} across {len(tail)} captures.")
            if not latest_is_sample:
                result["reasons"].append("Latest capture is too close to the previous sample to confirm a change.")
            if not result["reasons"]:
                result["reasons"].append("Inspect the observed changes." if result["status"] == "watch" else "No confirmed intent or page-profile mismatch in the current comparison.")
        else:
            result["status"] = "baseline_ready"
            result["reasons"].append("Baseline is ready. The next spaced capture starts change detection.")
    if not result["timeline"]:
        result["timeline"] = [{"captured_at": snapshot["captured_at"], "intent": snapshot["dominant_intent"], "score": None, "quality_ok": snapshot["quality_ok"],
                               "quality_state": snapshot.get("quality", {}).get("state"), "phase": "baseline"}
                              for snapshot in sorted([*sampled, *invalid], key=lambda item: item["captured_at"])]
    if rejected:
        result["reasons"].append(f"{len(rejected)} newer capture{'s' if len(rejected) > 1 else ''} returned results for a different query and "
                                 f"{'were' if len(rejected) > 1 else 'was'} not used; this status comes from the capture of {latest['captured_at'][:16].replace('T', ' ')} UTC.")
    if not latest["quality_ok"]:
        result["status"] = "insufficient_data"
        result["reasons"].append("The latest capture has too few usable results. Alerts are suppressed.")
    if latest.get("quality", {}).get("state") in INVALID_STATES:
        result["status"] = "data_quality"
        result["reasons"] = latest["quality"].get("reasons", []) or ["This observation is excluded from comparisons."]
    if latest["source"] != "synthetic" and (now - parse_time(latest["captured_at"])).total_seconds() > interval * 1.75:
        result["status"] = "stale"
        # An old comparison says nothing current; keep only what explains the gap.
        result["reasons"] = [reason for reason in result["reasons"] if "different query" in reason]
        result["reasons"].append("No valid capture within 1.75 collection intervals: recent captures did not match the query. Check collection before interpreting this panel."
                                 if rejected else "Collection is overdue. Previous observations cannot describe the current SERP.")
    if last_attempt and not last_attempt["success"] and parse_time(last_attempt["attempted_at"]) > parse_time(latest["captured_at"]):
        result["status"] = "collection_error"
        result["reasons"].append(f"Latest collection failed: {last_attempt['code']}. The displayed SERP is the last successful capture.")
    if result["status"] in {"stale", "collection_error", "insufficient_data", "data_quality"}:
        result["confirmed_mismatch"] = result["confirmed_intent_shift"] = False
        result["confirmed_recovery"] = False
    # Position evidence comes from the newest valid capture; a capture of another query says nothing about this page.
    shown = latest if latest.get("quality", {}).get("state") not in INVALID_STATES else next(
        (snapshot for snapshot in reversed(snapshots) if snapshot.get("quality", {}).get("state") not in INVALID_STATES), latest)
    if shown.get("page"):
        page_url = canonical_url(shown["page"]["url"])
        result["page_position"] = next((item["position"] for item in shown["results"] if item["url"] == page_url), None)
    if site:
        from .history import site_cited, site_hit
        hit = site_hit(shown, site)
        result["site"] = {"position": hit["position"] if hit else None, "url": hit["url"] if hit else None, "hits": hit["count"] if hit else 0,
                          "cited": site_cited(shown, site), "captured_at": shown["captured_at"]}
        earlier = snapshots[:snapshots.index(shown)]
        previous = next((snapshot for snapshot in reversed(earlier) if snapshot["quality_ok"]), None)
        if previous is not None:
            before = site_hit(previous, site)
            result["site"]["previous_url"] = before["url"] if before else None
            result["site"]["previous_position"] = before["position"] if before else None
            result["site"]["ranking_url_changed"] = bool(before and hit and before["url"] != hit["url"])
        if result.get("page_position") is None and not shown.get("page"):
            result["page_position"] = result["site"]["position"]
        # Per-capture position of the site, so lists can say when a page left the top ten without loading the panel.
        by_time = {snapshot["captured_at"]: snapshot for snapshot in snapshots}
        for point in result["timeline"]:
            point_hit = site_hit(by_time[point["captured_at"]], site) if point["captured_at"] in by_time else None
            point["site_position"] = point_hit["position"] if point_hit else None
            point["site_url"] = point_hit["url"] if point_hit else None
    return explain(result, all_snapshots, settings)


def explain(result: dict, snapshots: list[dict], settings: dict) -> dict:
    """Single decision contract shared by the app, exports, notifications and agent tools."""
    from .quality import topic_check
    latest = result.get("latest") or {}
    baseline = result.get("baseline") or []
    quality = latest.get("quality") or {"state": "legacy", "provenance": "unverified", "reasons": ["Legacy capture: returned search context was not retained."]}
    coverage = latest.get("classified_coverage", 0)
    status = result["status"]
    if latest.get("labeling", {}).get("errors"):
        result["reasons"].append("Model classification is incomplete: " + ", ".join(latest["labeling"]["errors"]) + ". Intent confirmation is suppressed.")
    health = status in {"data_quality", "collection_error", "stale", "insufficient_data", "awaiting_data"}
    baseline_mix = average_distribution(baseline, "intent_distribution") if baseline else {}
    usable = not health and coverage >= .6 and len(baseline) >= settings["baseline_size"] and all(s.get("classified_coverage", 0) >= .6 for s in baseline)
    usable = usable and not latest.get("labeling", {}).get("errors")
    result["evidence"] = {
        "quality": quality, "classified_coverage": coverage,
        "support": "available" if usable else "insufficient",
        "baseline_captures": len(baseline), "baseline_required": settings["baseline_size"],
        "confirmation_required": settings["confirmations"],
        "baseline_variation": round(mean(tvd(baseline_mix, s["intent_distribution"]) for s in baseline), 3) if baseline else None,
        "classifier": latest.get("labeling", {}).get("model") or "English/Finnish lexical rules",
        "accuracy": "Not independently benchmarked. Coverage is not accuracy.",
    }
    recent = [s for s in snapshots[:-1] if s["quality_ok"]][-7:]
    result["recent_comparison"] = compare_sets(recent, [latest]) if recent and latest.get("quality_ok") else None
    result["topic_check"] = topic_check(baseline, latest) if baseline and latest else None
    intent_state = "confirmed" if result["confirmed_intent_shift"] else "unresolved" if not usable else "no_confirmed_shift"
    fit = "mismatch" if result["confirmed_mismatch"] else "not_configured" if not latest.get("page") else "unresolved" if not usable else "no_confirmed_mismatch"
    result["dimensions"] = {"serp_change": result["score"], "intent": intent_state, "page_fit": fit, "data": quality.get("state", "legacy")}
    if status == "data_quality" and quality.get("state") == "query_mismatch":
        title, action = "Latest capture did not match the query", "Treat it as a failed collection. The next valid capture replaces it; no content decision follows from it."
    elif health:
        title, action = "Check collection evidence", "Inspect the observation and fix collection before making a content decision."
    elif status in {"building_baseline", "baseline_ready"}:
        title, action = "Building a reliable comparison", "Keep the same search context and wait for spaced observations."
    elif status == "review":
        title, action = "Review the page brief", "Compare the evidence, then record your decision. A review does not require a rewrite."
    elif status == "watch":
        title, action = "Change observed; intent shift unconfirmed", "Inspect what changed. A high change score alone never confirms an intent shift."
    else:
        title, action = "No confirmed intent change", "Continue collecting. Check coverage before interpreting an unchanged classification."
    if (result.get("topic_check") or {}).get("inspection_suggested"):
        action += " Title vocabulary differs substantially; check query relevance."
    result["decision"] = {"title": title, "next_action": action, "reasons": result["reasons"]}
    signature = [ANALYSIS_VERSION, baseline[0]["captured_at"] if baseline else None, result.get("baseline_from"),
                 result["baseline_intent"], latest.get("dominant_intent"), result["confirmed_mismatch"], (latest.get("page") or {}).get("intent")]
    result["signal_key"] = hashlib.sha256(json.dumps(signature).encode()).hexdigest()[:20] if status == "review" else None
    return result
