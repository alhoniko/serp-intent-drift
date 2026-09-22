"""A workspace is one directory that owns the panel config, database, reports, key, and logs."""

from datetime import UTC, datetime
import json
import os
from pathlib import Path
import stat

ENV_DIR = "SERP_DRIFT_DIR"
ENV_KEY = "SEARCHAPI_API_KEY"
KEY_FILE = "searchapi.key"
SERVICES = {"searchapi": (ENV_KEY, KEY_FILE), "ahrefs": ("AHREFS_API_TOKEN", "ahrefs.key"), "labeling": ("OPENAI_API_KEY", "labeling.key")}  # service -> (environment variable, 0600 file)
GITIGNORE = "# serp-drift workspace: keep secrets, databases, and generated reports out of version control\n*.key\ndata/\nreports/\nlogs/\n*.sqlite*\n*.lock\n"


class Workspace:
    def __init__(self, root: Path) -> None:
        self.root = Path(root).expanduser().resolve()

    @classmethod
    def resolve(cls, explicit: Path | None = None) -> "Workspace":
        """Explicit --dir, then SERP_DRIFT_DIR, then the current directory."""
        if explicit is not None:
            return cls(explicit)
        if os.environ.get(ENV_DIR):
            return cls(Path(os.environ[ENV_DIR]))
        return cls(Path.cwd())

    @classmethod
    def default_init_dir(cls) -> Path:
        return Path(os.environ.get(ENV_DIR) or (Path.home() / "serp-drift"))

    @property
    def config(self) -> Path:
        return self.root / "monitor.toml"

    @property
    def database(self) -> Path:
        return self.root / "data" / "monitor.sqlite"

    @property
    def reports(self) -> Path:
        return self.root / "reports" / "live"

    @property
    def key_file(self) -> Path:
        return self.key_path("searchapi")

    def key_path(self, service: str = "searchapi") -> Path:
        if service not in SERVICES:
            raise ValueError(f"Unknown service {service!r}; expected one of {', '.join(SERVICES)}.")
        return self.root / SERVICES[service][1]

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    @property
    def rules(self) -> Path:
        return self.root / "rules"

    def exists(self) -> bool:
        return self.config.is_file()

    def api_key(self, service: str = "searchapi") -> str:
        """Environment first, then the 0600 key file. Never logged, never placed in a URL."""
        path = self.key_path(service)
        value = os.environ.get(SERVICES[service][0], "")
        if value:
            return value.strip()
        if not path.is_file():
            return ""
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode & (stat.S_IRWXG | stat.S_IRWXO):
            raise ValueError(f"{path} is readable by other users. Run: chmod 600 {path}")
        return path.read_text(encoding="utf-8").strip()

    def key_source(self, service: str = "searchapi") -> str:
        return "environment" if os.environ.get(SERVICES[service][0]) else ("file" if self.key_path(service).is_file() else "missing")

    def save_key(self, value: str, service: str = "searchapi") -> Path:
        value = value.strip()
        if not value or any(char.isspace() for char in value):
            raise ValueError("The API key must be a single token without spaces.")
        path = self.key_path(service)
        self.root.mkdir(parents=True, exist_ok=True)
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        descriptor = os.open(path, flags, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(value + "\n")
        os.chmod(path, 0o600)
        return path

    def ensure_layout(self) -> None:
        for directory in (self.root, self.database.parent, self.reports, self.logs, self.rules):
            directory.mkdir(parents=True, exist_ok=True)
        ignore = self.root / ".gitignore"
        if not ignore.exists():
            ignore.write_text(GITIGNORE, encoding="utf-8")

    def log(self, event: str, **fields: object) -> None:
        """Append one JSON line per run so cron and launchd users can see what happened."""
        self.logs.mkdir(parents=True, exist_ok=True)
        record = {"at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"), "event": event, **fields}
        with (self.logs / "serp-drift.log").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def describe(self) -> dict:
        return {"dir": str(self.root), "config": str(self.config), "database": str(self.database), "reports": str(self.reports),
                "key": self.key_source("searchapi"), "keys": {service: self.key_source(service) for service in SERVICES},
                "initialized": self.exists()}
