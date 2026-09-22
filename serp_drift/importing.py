"""Keyword import: turn a Search Console performance export (or any query CSV) or rows from an API source into panel candidates."""

import csv
import io
import re

from .intent import classify

QUERY_HEADERS = ("top queries", "query", "queries", "keyword", "keywords", "search term", "search terms", "hakukysely", "kysely", "kyselyt", "suosituimmat kyselyt", "hakusana", "hakusanat", "avainsana", "avainsanat")
NUMBER_HEADERS = {"impressions": ("impressions", "näyttökerrat", "volume", "search volume", "searches"),
                  "clicks": ("clicks", "klikkaukset"), "position": ("position", "avg. position", "average position", "sijainti", "rank")}


def _number(value: str) -> float | None:
    text = str(value or "").strip().replace(" ", "").replace(" ", "").replace(",", ".")
    text = text.rstrip("%")
    if not text or text == "-":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_csv(text: str) -> tuple[list[dict], dict]:
    """Rows as dicts with query/impressions/clicks/position plus a note on how columns were detected."""
    text = text.lstrip("﻿")
    sample = text[:4000]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    rows = [row for row in reader if any(cell.strip() for cell in row)]
    if not rows:
        raise ValueError("The file is empty.")
    header = [cell.strip().lower() for cell in rows[0]]
    query_index = next((index for index, cell in enumerate(header) if cell in QUERY_HEADERS), None)
    if query_index is None:
        # No recognizable header: treat the first column as the query and any numeric columns as impressions/position guesses.
        query_index, body, mapping = 0, rows, {}
        detected = "no header: first column read as the query"
    else:
        body = rows[1:]
        mapping = {name: next((index for index, cell in enumerate(header) if cell in aliases), None) for name, aliases in NUMBER_HEADERS.items()}
        detected = ", ".join(f"{name} ← column {index + 1}" for name, index in mapping.items() if index is not None) or "query column only"
    parsed = []
    for row in body:
        if query_index >= len(row):
            continue
        query = re.sub(r"\s+", " ", row[query_index]).strip()
        if not query or len(query) > 500:
            continue
        item = {"query": query}
        for name, index in mapping.items():
            item[name] = _number(row[index]) if index is not None and index < len(row) else None
        parsed.append(item)
    return parsed, {"rows": len(parsed), "columns": detected, "delimiter": dialect.delimiter if hasattr(dialect, "delimiter") else ","}


def candidates(text: str, *, existing: set[str], language: str = "en", limit: int = 5000) -> dict:
    """Deduplicated, ranked candidates from CSV text with a suggested intent and a flag for queries already monitored."""
    rows, info = parse_csv(text)
    return candidates_from_rows(rows, info, existing=existing, language=language, limit=limit)


def candidates_from_rows(rows: list[dict], info: dict, *, existing: set[str], language: str = "en", limit: int = 5000) -> dict:
    """Shared by every source: rows carry query plus any of impressions, clicks, volume, traffic, position, url, intent_hint, branded."""
    seen: dict[str, dict] = {}
    for row in rows:
        key = row["query"].lower()
        entry = seen.setdefault(key, {"query": row["query"], "impressions": 0.0, "clicks": 0.0, "traffic": 0.0, "volume": None, "position": None, "url": None, "intent_hint": None, "branded": False, "rows": 0})
        entry["rows"] += 1
        for name in ("impressions", "clicks", "traffic"):
            if row.get(name) is not None:
                entry[name] += row[name]
        if row.get("volume") is not None:
            entry["volume"] = max(entry["volume"] or 0.0, row["volume"])
        if row.get("position") is not None and (entry["position"] is None or row["position"] < entry["position"]):
            entry["position"] = row["position"]
            entry["url"] = row.get("url") or entry["url"]
        entry["intent_hint"] = entry["intent_hint"] or row.get("intent_hint")
        entry["branded"] = entry["branded"] or bool(row.get("branded"))
    items = []
    for entry in seen.values():
        label = classify(entry["query"], language=language)
        items.append({"query": entry["query"], "impressions": round(entry["impressions"]) if entry["impressions"] else None, "clicks": round(entry["clicks"]) if entry["clicks"] else None,
                      "volume": round(entry["volume"]) if entry["volume"] is not None else None, "traffic": round(entry["traffic"]) if entry["traffic"] else None,
                      "position": round(entry["position"], 1) if entry["position"] is not None else None, "url": entry["url"], "suggested_intent": label["intent"],
                      "source_intent": entry["intent_hint"], "branded": entry["branded"], "existing": entry["query"].lower() in existing, "words": len(entry["query"].split())})
    def weight(item: dict) -> float:  # the first demand figure a source offers: traffic estimate, impressions, or search volume
        return next((value for value in (item["traffic"], item["impressions"], item["volume"]) if value is not None), 0)
    items.sort(key=lambda item: (-weight(item), -(item["clicks"] or 0), item["position"] if item["position"] is not None else 999, item["query"]))
    return {"candidates": items[:limit], "total": len(items), "truncated": len(items) > limit, "detected": info}
