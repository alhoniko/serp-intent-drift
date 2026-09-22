"""Durable snapshots, indexed result rows, run records, events, and a single local collector lock."""

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import sqlite3
from urllib.parse import urlsplit

from .normalize import FEATURES

SCHEMA_VERSION = 6


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Timestamp must include a timezone.")
    return parsed.astimezone(UTC)


@contextmanager
def collection_lock(path: Path):
    try:
        import fcntl
    except ImportError:
        raise ValueError("Collection requires Linux/macOS or WSL for the advisory file lock.") from None
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(path.suffix + ".lock").open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("Another collector is using this database; wait for it to finish.") from None
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def retained_payload(payload: dict) -> dict:
    # A local audit subset, never the request URLs/metadata where providers may echo keys.
    def scrub(value):
        if isinstance(value, dict):
            return {key: scrub(item) for key, item in value.items()
                    if not any(part in key.lower() for part in ("token", "api_key", "authorization", "password", "searchapi"))
                    and key not in {"favicon", "thumbnail", "image"}}
        if isinstance(value, list):
            return [scrub(item) for item in value]
        return value
    return scrub({key: payload[key] for key in ("organic_results", *FEATURES) if key in payload})


def host_of(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY, target_id TEXT NOT NULL, identity TEXT NOT NULL,
    captured_at TEXT NOT NULL, source TEXT NOT NULL, normalized TEXT NOT NULL, raw_subset TEXT NOT NULL,
    UNIQUE(target_id, identity, captured_at, source)
);
CREATE INDEX IF NOT EXISTS snapshots_panel ON snapshots(target_id, identity, source, captured_at);
CREATE TABLE IF NOT EXISTS attempts (
    id INTEGER PRIMARY KEY, target_id TEXT NOT NULL, identity TEXT NOT NULL,
    attempted_at TEXT NOT NULL, success INTEGER NOT NULL, code TEXT NOT NULL, requests INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS attempts_panel ON attempts(target_id, identity, id);
CREATE TABLE IF NOT EXISTS results (
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    target_id TEXT NOT NULL, identity TEXT NOT NULL, source TEXT NOT NULL, captured_at TEXT NOT NULL,
    position INTEGER NOT NULL, url TEXT NOT NULL, host TEXT NOT NULL, title TEXT NOT NULL,
    intent TEXT NOT NULL, type TEXT NOT NULL,
    PRIMARY KEY (snapshot_id, position)
);
CREATE INDEX IF NOT EXISTS results_url ON results(target_id, identity, source, url, captured_at);
CREATE INDEX IF NOT EXISTS results_host ON results(host, captured_at);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT NOT NULL, trigger TEXT NOT NULL,
    collected INTEGER NOT NULL, skipped INTEGER NOT NULL, failed INTEGER NOT NULL, requests INTEGER NOT NULL,
    errors TEXT NOT NULL, error TEXT
);
CREATE TABLE IF NOT EXISTS panel_settings (
    target_id TEXT NOT NULL, identity TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL, updated_at TEXT NOT NULL,
    PRIMARY KEY (target_id, identity, key)
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY, at TEXT NOT NULL, target_id TEXT, identity TEXT, kind TEXT NOT NULL, payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_panel ON events(target_id, identity, id);
CREATE TABLE IF NOT EXISTS ai_overviews (
    snapshot_id INTEGER PRIMARY KEY REFERENCES snapshots(id) ON DELETE CASCADE,
    target_id TEXT NOT NULL, identity TEXT NOT NULL, source TEXT NOT NULL, captured_at TEXT NOT NULL,
    markdown TEXT NOT NULL, text_blocks TEXT NOT NULL, reference_links TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ai_overviews_panel ON ai_overviews(target_id, identity, source, captured_at);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS observation_reviews (
 target_id TEXT NOT NULL, identity TEXT NOT NULL, source TEXT NOT NULL, captured_at TEXT NOT NULL,
 excluded INTEGER NOT NULL, reason TEXT NOT NULL, updated_at TEXT NOT NULL,
 PRIMARY KEY(target_id,identity,source,captured_at)
);
CREATE TABLE IF NOT EXISTS analysis_runs (
 id INTEGER PRIMARY KEY, at TEXT NOT NULL, target_id TEXT NOT NULL, identity TEXT NOT NULL,
 method TEXT NOT NULL, input_hash TEXT NOT NULL, result TEXT NOT NULL,
 UNIQUE(target_id,identity,method,input_hash)
);
CREATE TABLE IF NOT EXISTS review_cases (
 id INTEGER PRIMARY KEY, target_id TEXT NOT NULL, identity TEXT NOT NULL, signal_key TEXT NOT NULL,
 opened_at TEXT NOT NULL, last_seen TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
 status TEXT NOT NULL DEFAULT 'new', decision TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT '',
 review_on TEXT, recovered_at TEXT
);
CREATE INDEX IF NOT EXISTS cases_panel ON review_cases(target_id,identity,id);
CREATE TABLE IF NOT EXISTS observations (
 snapshot_id INTEGER PRIMARY KEY REFERENCES snapshots(id), document TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS labels (key TEXT PRIMARY KEY, intent TEXT NOT NULL, model TEXT NOT NULL, labelled_at TEXT NOT NULL);
"""


class Store:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, timeout=10)
        self.connection.row_factory = sqlite3.Row
        version = self.connection.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            self.connection.close()
            raise ValueError("Unsupported database version; use a newer application release.")
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.executescript(SCHEMA)
        if version < 2:
            self._backfill_results()
        if version < 6:
            self.connection.execute("INSERT OR IGNORE INTO observations(snapshot_id,document) SELECT id,normalized FROM snapshots")
        self.connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        self.connection.commit()

    def _backfill_results(self) -> None:
        """Version 1 databases only stored normalized JSON; index their result rows once."""
        rows = self.connection.execute("SELECT id, target_id, identity, source, captured_at, normalized FROM snapshots").fetchall()
        with self.connection:
            for row in rows:
                self._index_results(row["id"], row["target_id"], row["identity"], row["source"], row["captured_at"], json.loads(row["normalized"]))

    def _index_results(self, snapshot_id: int, target_id: str, identity: str, source: str, captured_at: str, snapshot: dict) -> None:
        self.connection.executemany(
            "INSERT OR REPLACE INTO results(snapshot_id,target_id,identity,source,captured_at,position,url,host,title,intent,type) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            [(snapshot_id, target_id, identity, source, captured_at, result["position"], result["url"], host_of(result["url"]),
              result.get("title", ""), result.get("intent", "unknown"), result.get("type", "unknown")) for result in snapshot.get("results", [])])

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.connection.close()

    # --- snapshots -----------------------------------------------------------------------------------------------
    def add(self, target: dict, snapshot: dict, payload: dict) -> bool:
        timestamp = parse_time(snapshot["captured_at"]).isoformat(timespec="microseconds").replace("+00:00", "Z")
        snapshot = snapshot | {"captured_at": timestamp}
        observation = snapshot.pop("observation", None) or snapshot.copy()
        observation = observation | {"captured_at": timestamp}
        with self.connection:
            cursor = self.connection.execute(
                "INSERT OR IGNORE INTO snapshots(target_id,identity,captured_at,source,normalized,raw_subset) VALUES(?,?,?,?,?,?)",
                (target["id"], target["identity"], timestamp, snapshot["source"], json.dumps(snapshot), json.dumps(retained_payload(payload))),
            )
            if cursor.rowcount:
                self.connection.execute("INSERT INTO observations(snapshot_id,document) VALUES(?,?)",
                                        (cursor.lastrowid, json.dumps(observation)))
                self._index_results(cursor.lastrowid, target["id"], target["identity"], snapshot["source"], timestamp, snapshot)
                self._store_ai_overview(cursor.lastrowid, target, snapshot["source"], timestamp, payload.get("ai_overview"))
            return bool(cursor.rowcount)

    def _store_ai_overview(self, snapshot_id: int, target: dict, source: str, captured_at: str, value: object) -> None:
        """Full AI Overview text and citations live here, outside the normalized record, and outside raw pruning."""
        if not isinstance(value, dict) or not value.get("text_blocks"):
            return
        references = [{key: reference.get(key) for key in ("index", "title", "link", "source", "snippet")}
                      for reference in value.get("reference_links", []) if isinstance(reference, dict)]
        self.connection.execute(
            "INSERT OR REPLACE INTO ai_overviews(snapshot_id,target_id,identity,source,captured_at,markdown,text_blocks,reference_links) VALUES(?,?,?,?,?,?,?,?)",
            (snapshot_id, target["id"], target["identity"], source, captured_at, value.get("markdown", "") if isinstance(value.get("markdown"), str) else "",
             json.dumps(value.get("text_blocks", [])), json.dumps(references)))

    def ai_overview(self, target: dict, captured_at: str, source: str = "searchapi") -> dict | None:
        timestamp = parse_time(captured_at).isoformat(timespec="microseconds").replace("+00:00", "Z")
        row = self.connection.execute("SELECT markdown, text_blocks, reference_links FROM ai_overviews WHERE target_id=? AND identity=? AND source=? AND captured_at=?",
                                      (target["id"], target["identity"], source, timestamp)).fetchone()
        return {"markdown": row["markdown"], "text_blocks": json.loads(row["text_blocks"]), "reference_links": json.loads(row["reference_links"])} if row else None

    def ai_overview_count(self, source: str = "searchapi") -> int:
        return self.connection.execute("SELECT COUNT(*) FROM ai_overviews WHERE source=?", (source,)).fetchone()[0]

    def history(self, target: dict, source: str = "searchapi", since: str | None = None, until: str | None = None) -> list[dict]:
        query = "SELECT normalized FROM snapshots WHERE target_id=? AND identity=? AND source=?"
        params: list = [target["id"], target["identity"], source]
        if since:
            query += " AND captured_at>=?"
            params.append(since)
        if until:
            query += " AND captured_at<=?"
            params.append(until)
        rows = self.connection.execute(query + " ORDER BY captured_at,id", params).fetchall()
        snapshots = [json.loads(row[0]) for row in rows]
        reviews = {row["captured_at"]: dict(row) for row in self.connection.execute(
            "SELECT captured_at,excluded,reason,updated_at FROM observation_reviews WHERE target_id=? AND identity=? AND source=?",
            (target["id"], target["identity"], source))}
        for snapshot in snapshots:
            review = reviews.get(snapshot["captured_at"])
            if review:
                snapshot["observation_review"] = review
                if review["excluded"]:
                    snapshot["quality_ok"] = False
                    snapshot["quality"] = {**snapshot.get("quality", {}), "state": "excluded", "eligible": False, "reasons": [review["reason"]]}
        return snapshots

    def last_capture_time(self, target: dict, source: str = "searchapi") -> str | None:
        row = self.connection.execute("SELECT MAX(captured_at) FROM snapshots WHERE target_id=? AND identity=? AND source=?",
                                      (target["id"], target["identity"], source)).fetchone()
        return row[0] if row and row[0] else None

    def snapshot_count(self, source: str = "searchapi") -> int:
        return self.connection.execute("SELECT COUNT(*) FROM snapshots WHERE source=?", (source,)).fetchone()[0]

    def raw_subset(self, target: dict, captured_at: str, source: str = "searchapi") -> dict | None:
        timestamp = parse_time(captured_at).isoformat(timespec="microseconds").replace("+00:00", "Z")
        row = self.connection.execute("SELECT raw_subset FROM snapshots WHERE target_id=? AND identity=? AND source=? AND captured_at=?",
                                      (target["id"], target["identity"], source, timestamp)).fetchone()
        return json.loads(row[0]) if row else None

    def prune_raw(self, days: int, now: datetime | None = None) -> int:
        """Drop the raw provider subset for old captures; normalized observations stay forever."""
        if days <= 0:
            return 0
        cutoff = ((now or datetime.now(UTC)) - timedelta(days=days)).isoformat(timespec="microseconds").replace("+00:00", "Z")
        with self.connection:
            return self.connection.execute("UPDATE snapshots SET raw_subset='{}' WHERE captured_at<? AND raw_subset<>'{}'", (cutoff,)).rowcount

    # --- indexed results -------------------------------------------------------------------------------------------
    def url_history(self, target: dict, source: str = "searchapi") -> list[dict]:
        rows = self.connection.execute(
            "SELECT captured_at, position, url, host, title, intent, type FROM results WHERE target_id=? AND identity=? AND source=? ORDER BY captured_at, position",
            (target["id"], target["identity"], source)).fetchall()
        return [dict(row) for row in rows]

    def host_appearances(self, host: str, source: str = "searchapi") -> list[dict]:
        rows = self.connection.execute(
            "SELECT target_id, identity, captured_at, position, url FROM results WHERE host=? AND source=? ORDER BY captured_at", (host, source)).fetchall()
        return [dict(row) for row in rows]

    # --- attempts, runs, events, settings ---------------------------------------------------------------------------
    def attempt(self, target: dict, success: bool, code: str, requests: int) -> None:
        with self.connection:
            self.connection.execute("INSERT INTO attempts(target_id,identity,attempted_at,success,code,requests) VALUES(?,?,?,?,?,?)",
                                    (target["id"], target["identity"], utc_now(), int(success), code, requests))

    def last_attempt(self, target: dict) -> dict | None:
        row = self.connection.execute("SELECT attempted_at,success,code,requests FROM attempts WHERE target_id=? AND identity=? ORDER BY id DESC LIMIT 1",
                                      (target["id"], target["identity"])).fetchone()
        return dict(row) if row else None

    def attempts(self, target: dict, limit: int = 50) -> list[dict]:
        rows = self.connection.execute("SELECT attempted_at,success,code,requests FROM attempts WHERE target_id=? AND identity=? ORDER BY id DESC LIMIT ?",
                                       (target["id"], target["identity"], limit)).fetchall()
        return [dict(row) for row in rows]

    def record_run(self, started_at: str, summary: dict, trigger: str) -> int:
        with self.connection:
            cursor = self.connection.execute(
                "INSERT INTO runs(started_at,finished_at,trigger,collected,skipped,failed,requests,errors,error) VALUES(?,?,?,?,?,?,?,?,?)",
                (started_at, utc_now(), trigger, summary.get("collected", 0), summary.get("skipped", 0), summary.get("failed", 0),
                 summary.get("requests", 0), json.dumps(summary.get("errors", {})), summary.get("error")))
            return cursor.lastrowid

    def runs(self, limit: int = 30) -> list[dict]:
        rows = self.connection.execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) | {"errors": json.loads(row["errors"])} for row in rows]

    def add_event(self, kind: str, payload: dict, target: dict | None = None) -> None:
        with self.connection:
            self.connection.execute("INSERT INTO events(at,target_id,identity,kind,payload) VALUES(?,?,?,?,?)",
                                    (utc_now(), target["id"] if target else None, target["identity"] if target else None, kind, json.dumps(payload)))

    def events(self, target: dict | None = None, limit: int = 100) -> list[dict]:
        if target:
            rows = self.connection.execute("SELECT * FROM events WHERE target_id=? AND identity=? ORDER BY id DESC LIMIT ?",
                                           (target["id"], target["identity"], limit)).fetchall()
        else:
            rows = self.connection.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) | {"payload": json.loads(row["payload"])} for row in rows]

    def get_setting(self, target: dict, key: str) -> str | None:
        row = self.connection.execute("SELECT value FROM panel_settings WHERE target_id=? AND identity=? AND key=?", (target["id"], target["identity"], key)).fetchone()
        return row[0] if row else None

    def set_setting(self, target: dict, key: str, value: str | None) -> None:
        with self.connection:
            if value is None:
                self.connection.execute("DELETE FROM panel_settings WHERE target_id=? AND identity=? AND key=?", (target["id"], target["identity"], key))
            else:
                self.connection.execute("INSERT OR REPLACE INTO panel_settings(target_id,identity,key,value,updated_at) VALUES(?,?,?,?,?)",
                                        (target["id"], target["identity"], key, value, utc_now()))

    def get_meta(self, key: str) -> str | None:
        row = self.connection.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def set_meta(self, key: str, value: str | None) -> None:
        with self.connection:
            if value is None:
                self.connection.execute("DELETE FROM meta WHERE key=?", (key,))
            else:
                self.connection.execute("INSERT OR REPLACE INTO meta(key,value,updated_at) VALUES(?,?,?)", (key, value, utc_now()))

    def cached_labels(self, keys: list[str]) -> dict[str, str]:
        labels = {}
        for start in range(0, len(keys), 500):
            chunk = keys[start:start + 500]
            rows = self.connection.execute(f"SELECT key, intent FROM labels WHERE key IN ({','.join('?' * len(chunk))})", chunk).fetchall()
            labels.update({row["key"]: row["intent"] for row in rows})
        return labels

    def cache_label(self, key: str, intent: str, model: str) -> None:
        with self.connection:
            self.connection.execute("INSERT OR REPLACE INTO labels(key,intent,model,labelled_at) VALUES(?,?,?,?)", (key, intent, model, utc_now()))

    def panel_settings(self, target: dict) -> dict:
        rows = self.connection.execute("SELECT key, value FROM panel_settings WHERE target_id=? AND identity=?", (target["id"], target["identity"])).fetchall()
        return {row["key"]: row["value"] for row in rows}


    def review_observation(self, target: dict, captured_at: str, excluded: bool, reason: str) -> None:
        timestamp = parse_time(captured_at).isoformat(timespec="microseconds").replace("+00:00", "Z")
        if not reason.strip() or len(reason) > 2000:
            raise ValueError("Provide a reason between 1 and 2000 characters.")
        if not self.connection.execute("SELECT 1 FROM snapshots WHERE target_id=? AND identity=? AND source='searchapi' AND captured_at=?",
                                       (target["id"], target["identity"], timestamp)).fetchone():
            raise ValueError("Capture not found.")
        with self.connection:
            self.connection.execute("INSERT OR REPLACE INTO observation_reviews VALUES(?,?,?,?,?,?,?)",
                                    (target["id"], target["identity"], "searchapi", timestamp, int(excluded), reason.strip(), utc_now()))
        self.add_event("observation_review", {"capture": timestamp, "excluded": excluded, "reason": reason.strip()}, target)

    def record_analysis(self, query: dict) -> None:
        import hashlib
        document = json.dumps(query, sort_keys=True)
        fingerprint = hashlib.sha256(document.encode()).hexdigest()
        with self.connection:
            self.connection.execute("INSERT OR IGNORE INTO analysis_runs(at,target_id,identity,method,input_hash,result) VALUES(?,?,?,?,?,?)",
                                    (utc_now(), query["id"], query["identity"], query["method"], fingerprint, document))

    def cases(self, target: dict) -> list[dict]:
        return [dict(row) for row in self.connection.execute("SELECT * FROM review_cases WHERE target_id=? AND identity=? ORDER BY id DESC",
                                                            (target["id"], target["identity"]))]

    def sync_case(self, query: dict) -> dict | None:
        """Persist alert episodes on collection, not on read-only dashboard requests."""
        target = {"id": query["id"], "identity": query["identity"]}
        current = next((row for row in self.cases(target) if row["active"]), None)
        seen = (query.get("latest") or {}).get("captured_at", utc_now())
        signal = query.get("signal_key")
        # Collection failure/uncertainty cannot resolve an earlier confirmed change.
        recovered = query["status"] == "stable" and query.get("confirmed_recovery", False) and query.get("evidence", {}).get("support") == "available"
        if current and ((signal and signal != current["signal_key"]) or recovered):
            with self.connection:
                self.connection.execute("UPDATE review_cases SET active=0,recovered_at=? WHERE id=?", (seen, current["id"]))
            self.add_event("review_recovered" if recovered else "review_replaced", {"case_id": current["id"]}, target)
            current = None
        if signal and current:
            with self.connection:
                self.connection.execute("UPDATE review_cases SET last_seen=? WHERE id=?", (seen, current["id"]))
        elif signal:
            with self.connection:
                cursor = self.connection.execute("INSERT INTO review_cases(target_id,identity,signal_key,opened_at,last_seen) VALUES(?,?,?,?,?)",
                                                 (query["id"], query["identity"], signal, seen, seen))
            self.add_event("review_opened", {"case_id": cursor.lastrowid, "signal": signal}, target)
        return next((row for row in self.cases(target) if row["active"]), None)

    def decide(self, target: dict, case_id: int, status: str, decision: str, note: str, review_on: str | None = None) -> dict:
        if status not in {"new", "investigating", "decided", "monitoring", "closed"}:
            raise ValueError("Unknown review status.")
        if decision not in {"", "update_page", "create_page", "wait", "no_action", "incorrect_observation", "incorrect_label"}:
            raise ValueError("Unknown decision.")
        if len(note) > 4000 or (status in {"decided", "monitoring", "closed"} and (not decision or not note.strip())):
            raise ValueError("A decision and a short rationale are required; notes are limited to 4000 characters.")
        if review_on:
            from datetime import date
            date.fromisoformat(review_on)
        with self.connection:
            cursor = self.connection.execute("UPDATE review_cases SET status=?,decision=?,note=?,review_on=? WHERE id=? AND target_id=? AND identity=?",
                                             (status, decision, note.strip(), review_on, case_id, target["id"], target["identity"]))
            if not cursor.rowcount:
                raise ValueError("Review not found.")
        self.add_event("review_decision", {"case_id": case_id, "status": status, "decision": decision, "note": note.strip(), "review_on": review_on}, target)
        return next(row for row in self.cases(target) if row["id"] == case_id)
