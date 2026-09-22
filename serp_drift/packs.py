"""Intent rule packs: one TOML file per language, built in or added to a workspace's rules/ directory."""

from contextvars import ContextVar
import hashlib
from importlib.resources import files
import json
from pathlib import Path
import re
import tomllib

INTENTS = ("informational", "commercial", "transactional", "navigational")


def _validate(pack: dict, origin: str) -> dict:
    language = pack.get("language")
    if not isinstance(language, str) or not re.fullmatch(r"[a-z]{2,3}", language):
        raise ValueError(f"{origin}: language must be a 2–3 letter lowercase code.")
    version = pack.get("version", 1)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ValueError(f"{origin}: version must be a positive integer.")
    rules = {intent: list(pack.get("rules", {}).get(intent, [])) for intent in INTENTS}
    sections = {intent: list(pack.get("sections", {}).get(intent, [])) for intent in INTENTS}
    for table in (rules, sections):
        for intent, patterns in table.items():
            for pattern in patterns:
                if not isinstance(pattern, str) or not pattern:
                    raise ValueError(f"{origin}: {intent} contains an empty or non-string pattern.")
                try:
                    re.compile(pattern)
                except re.error as error:
                    raise ValueError(f"{origin}: invalid pattern {pattern!r} ({error}).") from None
    return {"language": language, "version": version, "name": pack.get("name", language), "replace": bool(pack.get("replace", False)),
            "rules": rules, "sections": sections, "origin": origin}


def load_pack(text: str, origin: str) -> dict:
    return _validate(tomllib.loads(text), origin)


def builtin_packs() -> dict[str, dict]:
    packs = {}
    for entry in sorted(files("serp_drift").joinpath("rules").iterdir(), key=lambda item: item.name):
        if entry.name.endswith(".toml"):
            pack = load_pack(entry.read_text(encoding="utf-8"), f"builtin:{entry.name}")
            packs[pack["language"]] = pack
    return packs


def user_packs(directory: Path | None) -> dict[str, dict]:
    packs = {}
    if directory and directory.is_dir():
        for path in sorted(directory.glob("*.toml")):
            pack = load_pack(path.read_text(encoding="utf-8"), f"user:{path.name}")
            packs[pack["language"]] = pack
    return packs


def merge(builtin: dict[str, dict], user: dict[str, dict]) -> dict[str, dict]:
    """A user pack extends the built-in pack of the same language unless it sets replace = true."""
    merged = {language: {**pack, "rules": {k: list(v) for k, v in pack["rules"].items()}, "sections": {k: list(v) for k, v in pack["sections"].items()}}
              for language, pack in builtin.items()}
    for language, pack in user.items():
        if language in merged and not pack["replace"]:
            for intent in INTENTS:
                merged[language]["rules"][intent] += [p for p in pack["rules"][intent] if p not in merged[language]["rules"][intent]]
                merged[language]["sections"][intent] += [p for p in pack["sections"][intent] if p not in merged[language]["sections"][intent]]
            merged[language]["origin"] += f"+{pack['origin']}"
            merged[language]["extended"] = True
        else:
            merged[language] = pack
    return merged


class Registry:
    def __init__(self, packs: dict[str, dict], builtin_languages: set[str]) -> None:
        self.packs = packs
        self.builtin_languages = builtin_languages
        self.compiled = {language: {intent: [re.compile(p) for p in pack["rules"][intent]] for intent in INTENTS} for language, pack in packs.items()}
        # Section patterns are language-agnostic: any pack may contribute, and every panel uses the union.
        union = {intent: [] for intent in INTENTS}
        for pack in packs.values():
            for intent in INTENTS:
                union[intent] += [p for p in pack["sections"][intent] if p not in union[intent]]
        self.sections = {intent: re.compile(r"^/(?:" + "|".join(patterns) + r")(?:/|$)") if patterns else None for intent, patterns in union.items()}

    def languages(self) -> list[str]:
        return sorted(self.packs)

    def supports(self, language: str) -> bool:
        return language.split("-")[0] in self.packs

    def analysis_version(self) -> str:
        """Stable for built-in packs; suffixed with a fingerprint whenever user rules change the effective set."""
        built = sorted(language for language in self.packs if language in self.builtin_languages and not self.packs[language].get("extended") and self.packs[language]["origin"].startswith("builtin:"))
        version = max((self.packs[language]["version"] for language in built), default=1)
        base = f"rules-{'-'.join(built)}-v{version}" if built else "rules-none-v0"
        custom = {language: pack for language, pack in self.packs.items() if language not in built}
        if not custom:
            return base
        fingerprint = hashlib.sha256(json.dumps({language: {"rules": pack["rules"], "sections": pack["sections"], "version": pack["version"]}
                                                for language, pack in sorted(custom.items())}, sort_keys=True).encode()).hexdigest()[:8]
        return f"{base}+{'-'.join(sorted(custom))}-{fingerprint}"

    def describe(self) -> list[dict]:
        return [{"language": language, "name": pack["name"], "version": pack["version"], "origin": pack["origin"],
                 "rules": {intent: len(pack["rules"][intent]) for intent in INTENTS}} for language, pack in sorted(self.packs.items())]


_registry: ContextVar[Registry | None] = ContextVar("serp_drift_rules", default=None)


def registry() -> Registry:
    current = _registry.get()
    if current is None:
        current = configure(None)
    return current


def configure(user_dir: Path | None) -> Registry:
    """Each collection thread has its own workspace rules, never another project's rules."""
    builtin = builtin_packs()
    current = Registry(merge(builtin, user_packs(user_dir)), set(builtin))
    _registry.set(current)
    return current


def reset() -> None:
    _registry.set(None)
