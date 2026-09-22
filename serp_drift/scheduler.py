"""In-process scheduler: wakes up on a poll interval and collects whatever panel is due, project by project."""

from datetime import UTC, datetime, timedelta
import sqlite3
import threading

from .config import minimum_spacing_seconds
from .storage import Store, parse_time, utc_now

FAILURE_BACKOFF = timedelta(minutes=15)


def due_panels(config: dict, database, now: datetime | None = None) -> list[dict]:
    """Targets whose last capture is older than the interval (or missing), unless paused or a recent attempt failed."""
    now = now or datetime.now(UTC)
    if not database.is_file():
        return list(config["targets"])
    due = []
    with Store(database) as store:
        for target in config["targets"]:
            if store.get_setting(target, "paused") == "1":
                continue
            last = store.last_capture_time(target)
            if last and (now - parse_time(last)).total_seconds() < minimum_spacing_seconds(config["settings"]):
                continue
            attempt = store.last_attempt(target)
            if attempt and not attempt["success"] and now - parse_time(attempt["attempted_at"]) < FAILURE_BACKOFF:
                continue
            due.append(target)
    return due


def next_due_at(config: dict, database, now: datetime | None = None) -> str | None:
    now = now or datetime.now(UTC)
    if not database.is_file() or not config["targets"]:
        return utc_now() if config["targets"] else None
    spacing = timedelta(seconds=minimum_spacing_seconds(config["settings"]))
    with Store(database) as store:
        times = []
        for target in config["targets"]:
            if store.get_setting(target, "paused") == "1":
                continue
            last = store.last_capture_time(target)
            next_at = parse_time(last) + spacing if last else now
            attempt = store.last_attempt(target)
            if attempt and not attempt["success"]:
                next_at = max(next_at, parse_time(attempt["attempted_at"]) + FAILURE_BACKOFF)
            times.append(next_at)
    if not times:
        return None
    soonest = max(min(times), now)
    return soonest.isoformat(timespec="seconds").replace("+00:00", "Z")


class Scheduler(threading.Thread):
    def __init__(self, app, poll_seconds: int = 60) -> None:
        super().__init__(name="serp-drift-scheduler", daemon=True)
        self.app = app
        self.poll_seconds = poll_seconds
        self.stop_event = threading.Event()
        self.last_check: str | None = None
        self.last_due: dict[str, list[str]] = {}

    def run(self) -> None:
        while not self.stop_event.wait(self.poll_seconds if self.last_check else 2):
            self.check()

    def check(self) -> None:
        self.last_check = utc_now()
        for project in list(self.app.projects.values()):
            config = project.current_config()
            if not config or project.run_state["running"]:
                continue
            try:
                due = due_panels(config, project.workspace.database)
            except (ValueError, OSError, sqlite3.Error):
                due = []
            self.last_due[project.id] = [target["id"] for target in due]
            if due:
                project.run("scheduler", only={target["id"] for target in due})

    def stop(self) -> None:
        self.stop_event.set()

    def describe(self) -> dict:
        soonest = None
        per_project = {}
        for project in self.app.projects.values():
            config = project.current_config()
            try:
                next_at = next_due_at(config, project.workspace.database) if config else None
            except (ValueError, OSError, sqlite3.Error):
                next_at = None
            per_project[project.id] = next_at
            if next_at and (soonest is None or next_at < soonest):
                soonest = next_at
        return {"enabled": True, "poll_seconds": self.poll_seconds, "last_check": self.last_check, "last_due": self.last_due, "next_due_at": soonest,
                "next_by_project": per_project, "alive": self.is_alive()}
