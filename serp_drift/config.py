"""Validate a small, explicit search panel before spending API credits."""

from functools import wraps
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
import tomllib

from . import packs
from .engines import ENGINES, spec
from .packs import INTENTS

SEARCH_DEFAULTS = {"engine": "google", "gl": "us", "hl": "en", "device": "desktop", "page": 1}
DEFAULTS = {
    "interval_hours": 24,
    "baseline_size": 3,
    "confirmations": 2,
    "min_results": 5,
    "drift_threshold": 35,
    "max_requests_per_run": 100,
    "request_delay_seconds": 1,
    "timeout_seconds": 45,
    "max_retries": 2,
    "raw_retention_days": 90,
    "ai_overview": "expand",
    "resolve_links": True,
}
TEXT_SETTINGS = {"ai_overview": ("expand", "skip"), "resolve_links": (True, False)}


def config_edit(function):
    @wraps(function)
    def locked(path, *args, **kwargs):
        import fcntl
        with path.with_suffix(".edit.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                return function(path, *args, **kwargs)
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)
    return locked


def write_validated(path: Path, text: str) -> None:
    """Validate in the same workspace, then replace atomically. Readers never see partial TOML."""
    name = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, suffix=".toml", delete=False) as file:
            name = Path(file.name)
            file.write(text)
        load_config(name)
        os.chmod(name, path.stat().st_mode & 0o777)
        os.replace(name, path)
    finally:
        if name and name.exists():
            name.unlink()


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:20]


def search_identity(search: dict, tag: str = "") -> str:
    return digest({"search": search, "analysis_version": packs.registry().analysis_version() + tag})


def minimum_spacing_seconds(settings: dict) -> float:
    interval = settings["interval_hours"] * 3600
    # A daily timer must not skip a whole day because today's HTTP request finished seconds earlier.
    return interval - min(60, interval * 0.01)


NOTIFY_DEFAULTS = {"webhook_url": "", "format": "json", "on": ["review", "watch", "collection_error", "stale"], "digest": "none", "digest_day": "monday"}
NOTIFY_FORMATS = ("json", "slack", "discord", "ntfy")
DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
STATUSES = ("review", "watch", "stable", "building_baseline", "baseline_ready", "awaiting_data", "insufficient_data", "stale", "collection_error", "data_quality")


def validate_notify(value: object) -> dict:
    if not isinstance(value, dict) or set(value) - NOTIFY_DEFAULTS.keys():
        raise ValueError("notify accepts webhook_url, format, on, digest, and digest_day.")
    notify = NOTIFY_DEFAULTS | value
    url = notify["webhook_url"]
    if not isinstance(url, str) or (url and not re.match(r"^https?://[^\s/]+", url)):
        raise ValueError("notify.webhook_url must be an http(s) URL or empty.")
    if notify["format"] not in NOTIFY_FORMATS:
        raise ValueError(f"notify.format must be one of {', '.join(NOTIFY_FORMATS)}.")
    if not isinstance(notify["on"], list) or any(item not in STATUSES for item in notify["on"]):
        raise ValueError(f"notify.on must list statuses from {', '.join(STATUSES)}.")
    if notify["digest"] not in {"none", "weekly", "daily"}:
        raise ValueError("notify.digest must be none, weekly, or daily.")
    if notify["digest_day"] not in DAYS:
        raise ValueError("notify.digest_day must be a weekday name in English.")
    return notify


@config_edit
def update_notify(path: Path, changes: dict) -> dict:
    """Rewrite only the [notify] table."""
    original = path.read_text(encoding="utf-8")
    current = load_config(path)["notify"]
    merged = validate_notify(current | changes)
    body = "[notify]\n" + "".join(f"{key} = {json.dumps(value, ensure_ascii=False)}\n" for key, value in merged.items()) + "\n"
    match = re.search(r"^\[notify\][ \t]*(?:#.*)?$\n(?:(?!^\[).*\n?)*", original, flags=re.M)
    if match:
        text = original[:match.start()] + body + original[match.end():].lstrip("\n")
    else:
        anchor = re.search(r"^\[search\]", original, flags=re.M)
        insert_at = anchor.start() if anchor else len(original)
        text = original[:insert_at] + body + original[insert_at:]
    write_validated(path, text)
    try:
        return load_config(path)["notify"]
    except ValueError:
        write_validated(path, original)
        raise


PROJECT_DEFAULTS = {"name": "", "site": ""}


def normalize_site(value: str) -> str:
    """A bare hostname without scheme, path, or leading www."""
    value = value.strip().lower()
    value = re.sub(r"^https?://", "", value).split("/")[0].removeprefix("www.")
    if value and not re.fullmatch(r"[a-z0-9.-]+\.[a-z0-9-]+", value):
        raise ValueError("project.site must be a hostname such as example.com.")
    return value


def validate_project(value: object, path: Path | None = None) -> dict:
    if not isinstance(value, dict) or set(value) - PROJECT_DEFAULTS.keys():
        raise ValueError("project accepts name and site.")
    project = PROJECT_DEFAULTS | value
    if not isinstance(project["name"], str) or not isinstance(project["site"], str):
        raise ValueError("project.name and project.site must be strings.")
    project["site"] = normalize_site(project["site"])
    project["name"] = project["name"].strip() or project["site"] or (path.resolve().parent.name if path else "")
    return project


@config_edit
def update_project(path: Path, changes: dict) -> dict:
    """Rewrite only the [project] table."""
    original = path.read_text(encoding="utf-8")
    current = load_config(path)["project"]
    merged = validate_project({key: value for key, value in (current | changes).items() if key in PROJECT_DEFAULTS}, path)
    body = "[project]\n" + "".join(f"{key} = {json.dumps(value, ensure_ascii=False)}\n" for key, value in merged.items()) + "\n"
    match = re.search(r"^\[project\][ \t]*(?:#.*)?$\n(?:(?!^\[).*\n?)*", original, flags=re.M)
    if match:
        text = original[:match.start()] + body + original[match.end():].lstrip("\n")
    else:
        anchor = re.search(r"^version\s*=\s*1[ \t]*(?:#.*)?$\n", original, flags=re.M)
        insert_at = anchor.end() if anchor else 0
        text = original[:insert_at] + "\n" + body + original[insert_at:].lstrip("\n")
    write_validated(path, text)
    try:
        return load_config(path)["project"]
    except ValueError:
        write_validated(path, original)
        raise


def toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def render_target(target: dict) -> str:
    """Serialize one [[targets]] block; the writer only emits fields this tool defines."""
    lines = ["[[targets]]", f"id = {toml_string(target['id'])}", f"query = {toml_string(target['query'])}"]
    search = {key: value for key, value in target.get("search", {}).items() if key in {"engine", "gl", "hl", "device", "location"}}
    if search:
        lines.append("[targets.search]")
        lines += [f"{key} = {toml_string(str(value))}" for key, value in search.items()]
    page = target.get("page") or {}
    if page:
        lines.append("[targets.page]")
        for key in ("url", "intent", "content_file"):
            if page.get(key):
                lines.append(f"{key} = {toml_string(str(page[key]))}")
        if page.get("fetch"):
            lines.append("fetch = true")
    return "\n".join(lines) + "\n"


def render_config(settings: dict | None = None, search: dict | None = None, targets: list[dict] | None = None) -> str:
    """A complete monitor.toml; used by init and by the app when it adds panels."""
    parts = ["version = 1", ""]
    if settings:
        parts += ["[settings]"] + [f"{key} = {value}" for key, value in settings.items() if key in DEFAULTS] + [""]
    parts += ["[search]"] + [f"{key} = {toml_string(str(value))}" for key, value in (search or {"gl": "us", "hl": "en", "device": "desktop"}).items()] + [""]
    for target in targets or []:
        parts.append(render_target(target))
    return "\n".join(parts)


def load_config(path: Path) -> dict:
    packs.configure(path.resolve().parent / "rules")
    with path.open("rb") as handle:
        data = tomllib.load(handle)
    if set(data) - {"version", "settings", "search", "targets", "notify", "labeling", "project"}:
        raise ValueError("Unknown top-level config field; check the example configuration.")
    if data.get("version") != 1:
        raise ValueError("Configuration requires version = 1.")
    if not isinstance(data.get("settings", {}), dict) or not isinstance(data.get("search", {}), dict):
        raise ValueError("settings and search must be TOML tables.")
    if set(data.get("settings", {})) - DEFAULTS.keys():
        raise ValueError("Unknown settings field.")
    settings = DEFAULTS | data.get("settings", {})
    integer_keys = {"baseline_size", "confirmations", "min_results", "max_requests_per_run", "max_retries", "raw_retention_days"}
    for key, value in settings.items():
        if key in TEXT_SETTINGS:
            if value not in TEXT_SETTINGS[key]:
                raise ValueError(f"{key} must be one of {TEXT_SETTINGS[key]}.")
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"{key} must be a finite number.")
        if key in integer_keys and not isinstance(value, int):
            raise ValueError(f"{key} must be an integer.")
        if value < (0 if key in {"max_retries", "request_delay_seconds", "raw_retention_days"} else 1):
            raise ValueError(f"{key} is below the allowed minimum.")
    if settings["min_results"] > 10 or settings["max_retries"] > 5 or settings["drift_threshold"] > 100:
        raise ValueError("min_results <= 10, max_retries <= 5, and drift_threshold <= 100 are required.")
    if settings["timeout_seconds"] > 120:
        raise ValueError("timeout_seconds must be <= 120.")
    notify = validate_notify(data.get("notify", {}))
    project = validate_project(data.get("project", {}), path)
    from .labeling import identity_tag
    from .labeling import validate as validate_labeling
    labeling = validate_labeling(data.get("labeling", {}))
    tag = identity_tag(labeling)
    defaults = SEARCH_DEFAULTS | data.get("search", {})
    targets = data.get("targets", [])
    if not isinstance(targets, list):
        raise ValueError("targets must be a list of [[targets]] tables.")
    seen = set()
    searches = set()
    for target in targets:
        if not isinstance(target, dict) or set(target) - {"id", "query", "search", "page"}:
            raise ValueError("Invalid target fields.")
        identifier = target.get("id", "")
        if not isinstance(identifier, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", identifier) or identifier in seen:
            raise ValueError("Each target needs a unique kebab-case id (max 80 characters).")
        seen.add(identifier)
        query = target.get("query")
        if not isinstance(query, str) or not query.strip() or len(query) > 500:
            raise ValueError(f"{identifier}: query must contain 1–500 characters.")
        overrides = target.get("search", {})
        if not isinstance(overrides, dict):
            raise ValueError(f"{identifier}: search must be a table.")
        search = defaults | overrides | {"q": query.strip()}
        if set(search) - {"engine", "q", "gl", "hl", "device", "page", "location"}:
            raise ValueError("Unsupported search parameter. API keys belong in SEARCHAPI_API_KEY.")
        if not isinstance(search["engine"], str) or search["engine"] not in ENGINES:
            raise ValueError(f"{identifier}: unsupported engine; choose one of {', '.join(ENGINES)}.")
        if search["page"] != 1 or isinstance(search["page"], bool):
            raise ValueError("This release compares the first result page only.")
        allowed = spec(search["engine"])["params"]
        if "device" not in allowed:
            if "device" in overrides:
                raise ValueError(f"{identifier}: {search['engine']} does not take a device parameter.")
            search.pop("device", None)
        elif not isinstance(search["device"], str) or search["device"] not in {"desktop", "mobile", "tablet"}:
            raise ValueError("device must be desktop, mobile, or tablet.")
        if "location" in search and "location" not in allowed:
            raise ValueError(f"{identifier}: {search['engine']} does not take a location parameter.")
        for key in ("gl", "hl"):
            if not isinstance(search[key], str) or not re.fullmatch(r"[a-z]{2}(?:-[A-Za-z]{2,4})?", search[key]):
                raise ValueError(f"Invalid {key} code.")
        if "location" in search and (not isinstance(search["location"], str) or not search["location"].strip()):
            raise ValueError("location must be a canonical SearchApi location string.")
        identity = search_identity(search, tag)
        if identity in searches:
            raise ValueError("Duplicate search panel. Use one page profile per exact query/locale/device.")
        searches.add(identity)
        page = target.get("page", {})
        if not isinstance(page, dict) or set(page) - {"url", "intent", "content_file", "fetch"}:
            raise ValueError(f"{identifier}: invalid page profile.")
        if page:
            from .normalize import canonical_url
            if not canonical_url(page.get("url", "")):
                raise ValueError(f"{identifier}: page.url must be an HTTP(S) URL without credentials.")
            if "intent" in page and page["intent"] not in INTENTS:
                raise ValueError(f"{identifier}: invalid page.intent.")
            if "fetch" in page and not isinstance(page["fetch"], bool):
                raise ValueError("page.fetch must be true or false.")
            if page.get("fetch") and page.get("content_file"):
                raise ValueError("Choose page.fetch or content_file, not both.")
            if "content_file" in page:
                if not isinstance(page["content_file"], str):
                    raise ValueError("content_file must be a path string.")
                content_path = (path.resolve().parent / page["content_file"]).resolve()
                if not content_path.is_file() or content_path.stat().st_size > 2_000_000:
                    raise ValueError(f"{identifier}: content_file must exist and be <= 2 MB.")
                page["content_file"] = str(content_path)
            if not page.get("intent") and not page.get("content_file") and not page.get("fetch"):
                raise ValueError(f"{identifier}: supply page.intent, page.content_file, or page.fetch.")
        target["search"] = search
        target["identity"] = identity
    return {"rules_dir": str(path.resolve().parent / "rules"), "version": 1, "settings": settings, "targets": targets, "notify": notify, "labeling": labeling, "project": project, "search": defaults,
            "analysis_version": packs.registry().analysis_version() + tag}


def _target_blocks(text: str) -> list[tuple[int, int, str | None]]:
    """(start, end, id) of every [[targets]] block in the file text, in order."""
    blocks = []
    starts = [match.start() for match in re.finditer(r"^\[\[targets\]\][ \t]*(?:#.*)?$", text, flags=re.M)]
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(text)
        match = re.search(r'^id\s*=\s*"([^"]*)"', text[start:end], flags=re.M) or re.search(r"^id\s*=\s*'([^']*)'", text[start:end], flags=re.M)
        blocks.append((start, end, match.group(1) if match else None))
    return blocks


@config_edit
def append_target(path: Path, target: dict) -> dict:
    """Append one [[targets]] block, then reload and validate; the original text is restored on any error."""
    original = path.read_text(encoding="utf-8")
    text = original if original.endswith("\n") or not original else original + "\n"
    text += ("\n" if text and not text.endswith("\n\n") else "") + render_target(target)
    write_validated(path, text)
    try:
        config = load_config(path)
    except ValueError:
        write_validated(path, original)
        raise
    return next(item for item in config["targets"] if item["id"] == target["id"])


@config_edit
def replace_target(path: Path, target: dict) -> dict:
    """Rewrite one [[targets]] block in place (same position, comments elsewhere untouched)."""
    original = path.read_text(encoding="utf-8")
    blocks = [block for block in _target_blocks(original) if block[2] == target["id"]]
    if not blocks:
        raise ValueError(f"No target with id {target['id']!r} in {path.name}.")
    start, end, _ = blocks[0]
    text = original[:start] + render_target(target) + ("\n" if original[end:].strip() else "") + original[end:].lstrip("\n")
    write_validated(path, text)
    try:
        config = load_config(path)
    except ValueError:
        write_validated(path, original)
        raise
    return next(item for item in config["targets"] if item["id"] == target["id"])


@config_edit
def remove_target(path: Path, identifier: str) -> None:
    original = path.read_text(encoding="utf-8")
    blocks = [block for block in _target_blocks(original) if block[2] == identifier]
    if not blocks:
        raise ValueError(f"No target with id {identifier!r} in {path.name}.")
    start, end, _ = blocks[0]
    text = original[:start].rstrip("\n") + ("\n\n" if original[end:].strip() else "\n") + original[end:].lstrip("\n")
    write_validated(path, text)
    try:
        load_config(path)
    except ValueError:
        write_validated(path, original)
        raise


@config_edit
def update_settings(path: Path, changes: dict) -> dict:
    """Rewrite only the [settings] table; targets, comments elsewhere, and the [search] table are untouched."""
    original = path.read_text(encoding="utf-8")
    current = load_config(path)["settings"]
    unknown = set(changes) - DEFAULTS.keys()
    if unknown:
        raise ValueError(f"Unknown settings: {', '.join(sorted(unknown))}.")
    merged = current | changes
    body = "[settings]\n" + "".join(f"{key} = {json.dumps(value) if isinstance(value, (str, bool)) else value}\n".replace("true", "true").replace("false", "false")
                                    for key, value in merged.items() if key in DEFAULTS) + "\n"
    match = re.search(r"^\[settings\][ \t]*(?:#.*)?$\n(?:(?!^\[).*\n?)*", original, flags=re.M)
    if match:
        text = original[:match.start()] + body + original[match.end():].lstrip("\n")
    else:
        anchor = re.search(r"^version\s*=\s*1[ \t]*(?:#.*)?$\n", original, flags=re.M)
        insert_at = anchor.end() if anchor else 0
        text = original[:insert_at] + "\n" + body + original[insert_at:].lstrip("\n")
    write_validated(path, text)
    try:
        return load_config(path)["settings"]
    except ValueError:
        write_validated(path, original)
        raise


@config_edit
def update_labeling(path: Path, changes: dict) -> dict:
    from .labeling import validate
    original = path.read_text(encoding="utf-8")
    merged = validate(load_config(path)["labeling"] | changes)
    body = "[labeling]\n" + "".join(f"{key} = {json.dumps(value)}\n" for key, value in merged.items()) + "\n"
    pattern = re.compile(r"^\[labeling\][ \t]*(?:#.*)?$\n(?:(?!^\[).*\n?)*", re.M)
    match = pattern.search(original)
    if match:
        text = original[:match.start()] + body + original[match.end():]
    else:
        offset = re.search(r"^\[", original, re.M)
        at = offset.start() if offset else len(original)
        text = original[:at] + body + original[at:]
    write_validated(path, text)
    return merged
