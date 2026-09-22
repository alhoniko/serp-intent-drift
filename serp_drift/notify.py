"""Webhook notifications on status changes and a periodic digest. One URL, four payload formats, no vendor SDKs."""

from datetime import UTC, datetime, timedelta
import json
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from . import __version__
from .config import DAYS
from .storage import Store, parse_time, utc_now

ALERTING = {"review", "watch", "collection_error", "stale", "data_quality", "insufficient_data"}
LABELS = {"review": "Review page", "watch": "Watch changes", "stable": "Stable", "building_baseline": "Building baseline", "baseline_ready": "Baseline ready",
          "awaiting_data": "Awaiting data", "insufficient_data": "Sparse results", "stale": "Collection overdue", "collection_error": "Collection error", "data_quality": "Check data quality"}


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def payload_for(fmt: str, title: str, text: str, data: dict) -> tuple[bytes, dict]:
    """Slack and Discord take a text field; ntfy takes a message plus a title header; json gets everything."""
    if fmt == "slack":
        return json.dumps({"text": f"*{title}*\n{text}"}).encode(), {"Content-Type": "application/json"}
    if fmt == "discord":
        return json.dumps({"content": f"**{title}**\n{text}"[:1900]}).encode(), {"Content-Type": "application/json"}
    if fmt == "ntfy":
        return text.encode(), {"Content-Type": "text/plain; charset=utf-8", "Title": title.encode("ascii", "ignore").decode(), "Tags": "mag"}
    return json.dumps({"title": title, "text": text, **data}, ensure_ascii=False).encode(), {"Content-Type": "application/json"}


def send(url: str, fmt: str, title: str, text: str, data: dict, *, opener=None, timeout: float = 10) -> dict:
    body, headers = payload_for(fmt, title, text, data)
    request = Request(url, data=body, headers={**headers, "User-Agent": f"serp-drift/{__version__}"}, method="POST")
    opener = opener or build_opener(_NoRedirect())
    try:
        with opener.open(request, timeout=timeout) as response:
            return {"ok": 200 <= response.status < 300, "status": response.status}
    except HTTPError as error:
        error.close()
        return {"ok": False, "status": error.code}
    except (URLError, TimeoutError, OSError) as error:
        return {"ok": False, "status": None, "error": type(error).__name__}


def status_changes(report: dict, store: Store) -> list[dict]:
    """Compare every panel's current status with the last one recorded; remember the new one either way."""
    changes = []
    for query in report["queries"]:
        target = {"id": query["id"], "identity": query["identity"]}
        before = store.get_setting(target, "last_status")
        after = query["status"]
        if before != after:
            store.set_setting(target, "last_status", after)
            if before is not None:
                store.add_event("status_change", {"before": before, "after": after, "score": query["score"]}, target)
            changes.append({"id": query["id"], "query": query["query"], "search": query["search"], "before": before, "after": after,
                            "score": query["score"], "reasons": query["reasons"], "page_position": query.get("page_position")})
    return changes


def describe_change(change: dict) -> str:
    market = f"{change['search'].get('engine', 'google')} {change['search'].get('gl', '')}/{change['search'].get('hl', '')}"
    score = "" if change["score"] is None else f", score {round(change['score'])}"
    return f"{change['query']} ({market}): {LABELS.get(change['before'], change['before'] or 'new')} → {LABELS.get(change['after'], change['after'])}{score}. " + " ".join(change["reasons"])


def after_run(config: dict, store: Store, report: dict, *, sender=send) -> dict:
    """Detect status changes and post one notification listing the ones the config asked for."""
    changes = status_changes(report, store)
    notify = config.get("notify", {})
    wanted = [change for change in changes if change["before"] is not None and change["after"] in set(notify.get("on", []))]
    # Retry a failed delivery and identify reviews by episode, including a new signal
    # that arrives while the display status is already 'review'.
    pending = json.loads(store.get_meta("pending_notifications") or "[]")
    by_id = {q["id"]: q for q in report["queries"]}
    wanted = {c["id"]: c for c in [*pending, *wanted] if c["id"] in by_id and by_id[c["id"]]["status"] == c["after"] and c["after"] in notify.get("on", [])}
    for query in report["queries"]:
        target = {"id": query["id"], "identity": query["identity"]}
        case = next((c for c in query.get("reviews", []) if c["active"]), None)
        episode = str(case["id"]) if case else query.get("signal_key")
        if query["status"] == "review" and episode and "review" in notify.get("on", []):
            if store.get_setting(target, "notified_review_episode") == episode or (case and case["status"] in {"closed", "decided", "monitoring"}):
                wanted.pop(query["id"], None)
            else:
                wanted[query["id"]] = {"id": query["id"], "identity": query["identity"], "episode": episode,
                    "query": query["query"], "search": query["search"], "before": "watch", "after": "review", "score": query["score"], "reasons": query["reasons"]}
    wanted = list(wanted.values())
    result = {"changes": len(changes), "notified": 0, "sent": None}
    if not wanted or not notify.get("webhook_url"):
        return result
    title = f"serp-drift: {len(wanted)} panel{'s' if len(wanted) != 1 else ''} changed status"
    text = "\n".join(f"• {describe_change(change)}" for change in wanted)
    outcome = sender(notify["webhook_url"], notify.get("format", "json"), title, text, {"event": "status_change", "changes": wanted, "at": utc_now()})
    store.set_meta("pending_notifications", None if outcome["ok"] else json.dumps(wanted))
    if outcome["ok"]:
        for change in wanted:
            if change.get("episode"):
                store.set_setting(change, "notified_review_episode", change["episode"])
    store.add_event("notification", {"kind": "status_change", "count": len(wanted), **outcome})
    result |= {"notified": len(wanted), "sent": outcome}
    return result


# --- digest ---------------------------------------------------------------------------------------------------------------
def digest(config: dict, store: Store, report: dict, *, days: int = 7, now: datetime | None = None) -> dict:
    """A period summary across panels: statuses, movers, AI Overview prevalence, cited hosts, and page citations."""
    now = now or datetime.now(UTC)
    since = now - timedelta(days=days)
    statuses: dict[str, int] = {}
    movers, captures, overviews, page_cited, host_counts = [], 0, 0, 0, {}
    for query in report["queries"]:
        statuses[query["status"]] = statuses.get(query["status"], 0) + 1
        target = {"id": query["id"], "identity": query["identity"]}
        history = [snapshot for snapshot in store.history(target) if parse_time(snapshot["captured_at"]) >= since]
        captures += len(history)
        for snapshot in history:
            if snapshot.get("ai_overview_status") == "observed":
                overviews += 1
            summary = snapshot.get("ai_overview") or {}
            page_cited += int(bool(summary.get("page_cited")))
            for host in summary.get("cited_hosts", []):
                host_counts[host] = host_counts.get(host, 0) + 1
        if query["score"] is not None:
            movers.append({"id": query["id"], "query": query["query"], "status": query["status"], "score": query["score"], "page_position": query.get("page_position")})
    movers.sort(key=lambda item: -item["score"])
    hosts = sorted(({"host": host, "citations": count} for host, count in host_counts.items()), key=lambda item: (-item["citations"], item["host"]))
    return {"generated_at": utc_now(), "days": days, "since": since.isoformat(timespec="seconds").replace("+00:00", "Z"), "panels": len(report["queries"]),
            "captures": captures, "statuses": statuses, "movers": movers[:10], "ai_overviews": overviews,
            "ai_overview_share": round(overviews / captures, 3) if captures else None, "page_cited": page_cited, "hosts": hosts[:10],
            "review": [item for item in movers if item["status"] == "review"][:10], "version": __version__}


def digest_markdown(data: dict) -> str:
    share = "—" if data["ai_overview_share"] is None else f"{round(data['ai_overview_share'] * 100)}%"
    lines = [f"# SERP drift digest · last {data['days']} days", "",
             f"{data['panels']} panels · {data['captures']} captures · AI Overview in {share} of captures · your pages cited {data['page_cited']} times", ""]
    if data["statuses"]:
        lines += ["## Status", ""] + [f"- {LABELS.get(key, key)}: {value}" for key, value in sorted(data["statuses"].items(), key=lambda item: -item[1])] + [""]
    if data["movers"]:
        lines += ["## Biggest changes vs baseline", ""]
        for item in data["movers"]:
            page = f", your page #{item['page_position']}" if item["page_position"] else ""
            lines.append(f"- {item['query']} — {round(item['score'])}/100 ({LABELS.get(item['status'], item['status'])}{page})")
        lines.append("")
    if data["hosts"]:
        lines += ["## Most cited hosts in AI Overviews", ""] + [f"- {item['host']}: {item['citations']}" for item in data["hosts"]] + [""]
    lines.append(f"_Generated {data['generated_at']} by serp-drift {data['version']}._")
    return "\n".join(lines) + "\n"


def _svg_escape(value: object) -> str:
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def digest_svg(data: dict) -> str:
    """A 1200×630 share card in the report's palette. Text only, so it renders everywhere."""
    share = "—" if data["ai_overview_share"] is None else f"{round(data['ai_overview_share'] * 100)}%"
    metrics = [("PANELS", data["panels"]), ("CAPTURES", data["captures"]), ("REVIEW", data["statuses"].get("review", 0)), ("WATCH", data["statuses"].get("watch", 0)), ("AI OVERVIEW", share)]
    movers = data["movers"][:5]
    hosts = data["hosts"][:5]
    lines = ['<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630" role="img" aria-label="SERP drift digest">',
             '<rect width="1200" height="630" fill="#f3efe6"/>',
             '<style>text{font-family:Outfit,"Avenir Next","Segoe UI",sans-serif;fill:#0b0b0f}.eyebrow{font-size:14px;letter-spacing:2px;font-weight:600;fill:#605e55}.h1{font-size:54px;font-weight:600;letter-spacing:-2px}.metric{font-size:44px;font-weight:500;letter-spacing:-2px}.label{font-size:12px;letter-spacing:1.5px;font-weight:600;fill:#605e55}.row{font-size:18px}.muted{fill:#605e55;font-size:14px}</style>',
             f'<text x="72" y="84" class="eyebrow">SERP INTENT DRIFT MONITOR · LAST {data["days"]} DAYS</text>',
             '<text x="72" y="150" class="h1">The query stayed.</text>',
             '<rect x="72" y="175" width="298" height="18" fill="#d8ff2e"/>',
             '<text x="72" y="200" class="h1">The intent moved.</text>']
    for index, (label, value) in enumerate(metrics):
        x = 72 + index * 215
        lines += [f'<line x1="{x - 24}" y1="250" x2="{x - 24}" y2="330" stroke="#c9c5bb"/>' if index else '',
                  f'<text x="{x}" y="270" class="label">{_svg_escape(label)}</text>', f'<text x="{x}" y="318" class="metric">{_svg_escape(value)}</text>']
    lines.append('<text x="72" y="392" class="label">BIGGEST CHANGES VS BASELINE</text>')
    for index, item in enumerate(movers):
        lines.append(f'<text x="72" y="{422 + index * 30}" class="row">{_svg_escape(str(round(item["score"])).rjust(3))} · {_svg_escape(item["query"][:44])}</text>')
    if not movers:
        lines.append('<text x="72" y="422" class="muted">No comparisons yet; baselines are still building.</text>')
    lines.append('<text x="660" y="392" class="label">MOST CITED IN AI OVERVIEWS</text>')
    for index, item in enumerate(hosts):
        lines.append(f'<text x="660" y="{422 + index * 30}" class="row">{item["citations"]} · {_svg_escape(item["host"][:40])}</text>')
    if not hosts:
        lines.append('<text x="660" y="422" class="muted">No AI Overview citations stored in this period.</text>')
    lines += [f'<text x="72" y="596" class="muted">Generated {_svg_escape(data["generated_at"][:16].replace("T", " "))} UTC · serp-drift {_svg_escape(data["version"])} · built with SearchApi</text>', '</svg>']
    return "\n".join(line for line in lines if line) + "\n"


def digest_due(config: dict, store: Store, now: datetime | None = None) -> bool:
    now = now or datetime.now(UTC)
    notify = config.get("notify", {})
    cadence = notify.get("digest", "none")
    if cadence == "none" or not notify.get("webhook_url"):
        return False
    last = store.get_meta("last_digest_at")
    if cadence == "daily":
        return not last or parse_time(last).date() < now.date()
    if DAYS[now.weekday()] != notify.get("digest_day", "monday"):
        return False
    return not last or now - parse_time(last) > timedelta(days=6)


def send_digest(config: dict, store: Store, report: dict, *, sender=send, days: int | None = None, now: datetime | None = None) -> dict:
    notify = config["notify"]
    days = days or (1 if notify.get("digest") == "daily" else 7)
    data = digest(config, store, report, days=days, now=now)
    outcome = sender(notify["webhook_url"], notify.get("format", "json"), f"serp-drift digest · last {days} days", digest_markdown(data), {"event": "digest", "digest": data})
    stamp = (now or datetime.now(UTC)).isoformat(timespec="microseconds").replace("+00:00", "Z")
    store.set_meta("last_digest_at", stamp)
    store.add_event("notification", {"kind": "digest", "days": days, **outcome})
    return outcome
