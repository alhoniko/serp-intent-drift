"""Regenerate invented SearchApi-shaped scenarios; performs no network requests."""

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def result(index: int, kind: str, topic: str, family: str = "") -> dict:
    titles = {"guide": f"What is {topic}? A practical guide", "comparison": f"Best {topic}: tools compared and reviewed",
              "product": f"{topic} pricing: start a free trial", "unknown": f"{topic} — the collection"}
    snippets = {"guide": "Learn the fundamentals with this tutorial and definition.", "comparison": "Compare alternatives and read our software comparison.",
                "product": "Choose a plan and book a demo.", "unknown": "Explore the latest resources and selected pages."}
    return {"position": index, "title": f"{titles[kind]} | Source {index}",
            "link": f"https://source-{family}{index}.example/{topic.replace(' ', '-')}/{kind}", "snippet": snippets[kind]}


def main() -> None:
    specifications = [
        ("crm-automation", "crm automation", "CRM automation", "informational"),
        ("technical-seo", "technical seo audit", "technical SEO", "informational"),
        ("ai-tools", "ai research tools", "AI research tools", "commercial"),
        ("thin-serp", "search workflow templates", "search workflow templates", None),
    ]
    targets = []
    snapshots = []
    for identifier, query, topic, intent in specifications:
        target = {"id": identifier, "query": query, "search": {"engine": "google", "q": query, "gl": "us", "hl": "en", "device": "desktop", "page": 1}}
        if intent:
            target["page"] = {"url": f"https://publisher.example/{identifier}/", "intent": intent}
        targets.append(target)
        for day in range(6):
            kinds = ["guide"] * 10
            features = {"related_questions": [{"question": f"How does {topic} work?"}]}
            if identifier == "crm-automation" and day >= 3:
                kinds = ["comparison"] * 8 + ["guide"] * 2
                features |= {"ai_overview": {"text_blocks": [{"type": "paragraph", "answer": "Synthetic overview for demonstration."}]}, "inline_videos": [{"title": "Synthetic comparison video", "link": "https://video.example/demo"}]}
            if identifier == "ai-tools":
                kinds = ["comparison"] * 10
                if day >= 4:
                    features = {"inline_shopping": [{"title": "Synthetic listing"}], "ads": [{"title": "Synthetic ad"}], "inline_videos": [{"title": "Synthetic video"}], "ai_overview": {"text_blocks": [{"answer": "Synthetic overview."}]}}
            rows = [result(index, kind, topic, "new-" if identifier == "ai-tools" and day >= 4 else "") for index, kind in enumerate(kinds, 1)]
            if identifier == "technical-seo" and day >= 3:
                rows[3], rows[4] = rows[4], rows[3]
                for position, row in enumerate(rows, 1):
                    row["position"] = position
            if identifier == "thin-serp" and day == 5:
                rows = rows[:2]
            timestamp = (datetime(2026, 8, 24, 8, tzinfo=UTC) + timedelta(days=day)).isoformat().replace("+00:00", "Z")
            snapshots.append({"target_id": identifier, "captured_at": timestamp, "response": {"search_metadata": {"status": "Success"}, "organic_results": rows, **features}})
    dataset = {"schema_version": 1, "source": "synthetic", "license": "MIT", "description": "Entirely invented test fixtures. Not collected from Google or SearchApi. Reserved .example domains are intentional.", "targets": targets, "snapshots": snapshots}
    (ROOT / "serp_drift/assets/example-data.json").write_text(json.dumps(dataset, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

