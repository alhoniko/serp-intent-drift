"""Conservative, inspectable lexical intent proxies driven by per-language rule packs; not a semantic model."""

import hashlib
from html.parser import HTMLParser
from pathlib import Path
import re
from urllib.parse import urlsplit

from . import packs
from .packs import INTENTS

FIELD_WEIGHTS = (("title", 3), ("snippet", 2), ("url", 2))


def slug_words(path: str) -> str:
    return " ".join(part for part in re.split(r"[/\-_.+~%]+", path) if part and not part.isdigit())


def classify(title: str, snippet: str = "", url: str = "", language: str = "en") -> dict:
    registry = packs.registry()
    code = language.split("-")[0]
    if code not in registry.compiled:
        return {"intent": "unknown", "type": "unknown", "evidence": [], "confidence": 0.0}
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    path = parts.path.lower()
    texts = {"title": title.casefold(), "snippet": snippet.casefold(), "url": slug_words(path).casefold()}
    evidence = []
    scores = dict.fromkeys(INTENTS, 0)
    for intent, patterns in registry.compiled[code].items():
        for pattern in patterns:
            for field, weight in FIELD_WEIGHTS:
                match = pattern.search(texts[field])
                if match:
                    scores[intent] += weight
                    evidence.append(f"{field}: {match.group()} → {intent} (+{weight})")
    for intent, pattern in registry.sections.items():
        match = pattern.search(path) if pattern else None
        if match:
            scores[intent] += 2
            evidence.append(f"url section: {match.group().strip('/')} → {intent} (+2)")
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    top, runner = ranked[0], ranked[1]
    intent = top[0] if top[1] >= 3 and top[1] - runner[1] >= 2 else "unknown"
    if host in {"youtube.com", "www.youtube.com", "youtu.be", "vimeo.com"}:
        content_type = "video"
    elif host in {"github.com", "gitlab.com", "bitbucket.org", "pypi.org", "npmjs.com", "www.npmjs.com"}:
        content_type = "repository"
    elif host in {"reddit.com", "www.reddit.com", "stackoverflow.com", "www.quora.com", "quora.com"} or re.search(r"/(?:forum|community)(?:/|$)", path):
        content_type = "discussion"
    elif re.search(r"/(?:docs|documentation|help-center)(?:/|$)", path):
        content_type = "documentation"
    elif intent == "commercial":
        content_type = "comparison"
    elif intent == "transactional":
        content_type = "product"
    elif intent == "informational":
        content_type = "guide"
    elif intent == "navigational":
        content_type = "navigation"
    else:
        content_type = "unknown"
    return {
        "intent": intent, "type": content_type, "evidence": evidence,
        "confidence": round(top[1] / max(1, sum(scores.values())), 3) if intent != "unknown" else 0.0,
    }


class PageText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ignored: list[str] = []
        self.heading = False
        self.titles: list[str] = []
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in {"script", "style", "nav", "footer", "noscript", "svg"}:
            self.ignored.append(tag)
        if tag in {"title", "h1", "h2", "h3"}:
            self.heading = True

    def handle_endtag(self, tag: str) -> None:
        if tag in self.ignored:
            self.ignored.remove(tag)
        if tag in {"title", "h1", "h2", "h3"}:
            self.heading = False

    def handle_data(self, data: str) -> None:
        if not self.ignored and data.strip():
            self.parts.append(data.strip())
            if self.heading:
                self.titles.append(data.strip())


def page_profile(page: dict, language: str, observed_at: str, *, allow_fetch: bool = False) -> dict | None:
    if not page:
        return None
    text = ""
    headings = ""
    file = page.get("content_file")
    fetched = False
    resolved_url = page["url"]
    if page.get("fetch") and allow_fetch:
        from .page_fetch import fetch_page
        raw, content_type, resolved_url = fetch_page(page["url"])
        fetched = True
        if content_type in {"text/html", "application/xhtml+xml"}:
            parser = PageText()
            parser.feed(raw)
            text, headings = " ".join(parser.parts), " ".join(parser.titles)
        else:
            text = raw
            headings = raw[:200]
    elif file:
        content_path = Path(file)
        if content_path.stat().st_size > 2_000_000:
            raise ValueError("Page content file exceeds 2 MB.")
        raw = content_path.read_text(encoding="utf-8")
        if content_path.suffix.lower() in {".html", ".htm"}:
            parser = PageText()
            parser.feed(raw)
            text, headings = " ".join(parser.parts), " ".join(parser.titles)
        else:
            text = re.sub(r"\A---\s*\n.*?\n---\s*\n", "", raw, count=1, flags=re.S)
            headings = " ".join(re.findall(r"^#{1,3}\s+(.+)$", text, flags=re.M)) or text[:200]
    result = classify(headings, text[:20000], page["url"], language)
    declared = page.get("intent")
    basis = "fetched page" if fetched else "local content" if file else "declared"
    return {
        "url": page["url"], "intent": declared or result["intent"], "inferred_intent": result["intent"],
        "basis": f"declared + {basis}" if declared and (file or fetched) else basis,
        "evidence": result["evidence"], "title": headings[:300],
        "content_sha256": hashlib.sha256(text.encode()).hexdigest() if file or fetched else None,
        "observed_at": observed_at, "content_provided": bool(file or fetched), "resolved_url": resolved_url,
        "caveat": "Public page fetched for this capture. Classification uses HTML text and headings; JavaScript is not rendered." if fetched else "Local page export/profile; the live page has not been crawled. Refresh it when the page changes.",
    }
