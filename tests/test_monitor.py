"""Behavior tests for misleading alerts, provider failures, and reproducibility."""

import contextlib
from datetime import UTC, datetime, timedelta
import http.client
import io
from io import BytesIO
import json
import os
from pathlib import Path
import plistlib
import re
import sqlite3
import subprocess
import tempfile
import threading
import unittest
from unittest import mock
from unittest.mock import patch
from urllib.error import HTTPError, URLError
import zipfile

from serp_drift import insights, labeling, notify, packs, schedule
from serp_drift.analysis import analyze, compare, compare_sets, mismatch
from serp_drift.cli import collect, demo, expand_ai_overview, init_workspace, main, run_once
from serp_drift.client import ApiError, SearchApi
from serp_drift.config import DEFAULTS, SEARCH_DEFAULTS, load_config, minimum_spacing_seconds, search_identity, update_notify, update_project, validate_notify
from serp_drift.engines import request_params, rows
from serp_drift.history import change_log, citations, compare_specs, intent_stability, resolve_side, timeline, url_trajectories
from serp_drift.importing import candidates as import_candidates
from serp_drift.importing import candidates_from_rows
from serp_drift.intent import classify, page_profile
from serp_drift.mcp import McpServer
from serp_drift.normalize import canonical_url, dominant, normalize
from serp_drift.page_fetch import fetch_page, public_addresses
from serp_drift.report import build_report, csv_cell, write_report
from serp_drift.server import App, AppState, ProjectState, make_server
from serp_drift.sources import SourceError, ahrefs_keywords, ahrefs_units, clean_target
from serp_drift.storage import SCHEMA_VERSION, Store, collection_lock, retained_payload, utc_now
from serp_drift.workspace import Workspace

ROOT = Path(__file__).resolve().parents[1]
SEARCH = SEARCH_DEFAULTS | {"q": "test query"}
TARGET = {"id": "test-query", "query": "test query", "search": SEARCH, "identity": search_identity(SEARCH)}
START = datetime(2026, 8, 1, tzinfo=UTC)


def response(intent="informational", count=10):
    title = {"informational": "What is testing? A practical guide", "commercial": "Best tools: software comparison", "unknown": "Selected resources"}[intent]
    return {"search_metadata": {"status": "Success"}, "organic_results": [{"position": index, "title": title, "link": f"https://test-{index}.example/{intent}", "snippet": "A useful resource."} for index in range(1, count + 1)]}


def snapshot(day=0, intent="informational", count=10, source="synthetic"):
    timestamp = (START + timedelta(days=day)).isoformat()
    page = page_profile({"url": "https://publisher.example/guide", "intent": "informational"}, "en", timestamp)
    return normalize(response(intent, count), SEARCH, timestamp, page, source=source)


class NormalizationTests(unittest.TestCase):
    def test_tracking_removed_but_meaningful_parameters_kept(self):
        self.assertEqual(canonical_url("https://www.Example.com/a?v=one&utm_source=x#part"), "https://example.com/a?v=one")
        self.assertNotEqual(canonical_url("https://example.com/a?id=1"), canonical_url("https://example.com/a?id=2"))
        self.assertNotEqual(canonical_url("https://example.com/a"), canonical_url("https://example.com/a/"))

    def test_unsafe_links_rejected(self):
        for url in ("javascript:alert(1)", "https://user:secret@example.com", "file:///etc/passwd", "https://x.example:broken", "https://x.example\n/"):
            self.assertIsNone(canonical_url(url))

    def test_explicit_unknown_and_mixed_intents(self):
        self.assertEqual(classify("The collection")["intent"], "unknown")
        self.assertEqual(classify("Best tools comparison")["intent"], "commercial")
        self.assertEqual(classify("Parhaat työkalut vertailu", language="fi")["intent"], "commercial")
        self.assertEqual(classify("Best tools", language="de")["intent"], "unknown")
        self.assertEqual(dominant({"informational": .45, "commercial": .45, "unknown": .1}), "mixed")
        self.assertEqual(dominant({"informational": .35, "unknown": .65}), "unknown")

    def test_rules_v2_cover_technical_titles_and_known_exclusions(self):
        self.assertEqual(classify("SERP analysis using 3 Python scripts")["intent"], "informational")
        self.assertEqual(classify("Automating SEO competitor analysis with Python")["intent"], "informational")
        self.assertEqual(classify("Technical SEO best practices")["intent"], "unknown")
        self.assertEqual(classify("Column order in Google Sheets")["intent"], "unknown")
        self.assertEqual(classify("Selected resources", "Learn the definition with this tutorial.")["intent"], "informational")
        self.assertEqual(classify("Selected resources", "", "https://x.example/blog/python-tutorial-basics/")["intent"], "informational")
        self.assertEqual(classify("Selected resources", "", "https://x.example/pricing/")["intent"], "transactional")
        self.assertEqual(classify("SEO-oppaan ohjeet aloittelijalle", language="fi")["intent"], "informational")
        self.assertEqual(classify("Verkkokaupan hinnat ja tilaukset", language="fi")["intent"], "transactional")
        self.assertEqual(classify("HasData/python-for-seo", "", "https://github.com/HasData/python-for-seo")["type"], "repository")
        evidence = classify("Best tools comparison", "", "https://x.example/blog/best-tools/")["evidence"]
        self.assertTrue(any(item.startswith("url section: blog") for item in evidence))

    def test_ai_overview_error_object_is_not_observed(self):
        payload = response() | {"ai_overview": {"error": "An AI Overview is not available for this search"},
                                "related_questions": [{"question": "How?", "is_ai_overview": True, "error": "Loads asynchronously; not included."}]}
        result = normalize(payload, SEARCH, START.isoformat(), None)
        self.assertEqual(result["features"], ["related_questions"])
        self.assertEqual(result["ai_overview_status"], "not_available")
        self.assertFalse(result["warnings"])

    def test_unknown_language_does_not_claim_intent(self):
        result = normalize(response(), SEARCH | {"hl": "de"}, START.isoformat(), None)
        self.assertEqual(result["dominant_intent"], "unknown")
        self.assertTrue(result["warnings"])

    def test_no_empty_or_token_only_feature_claim(self):
        payload = response() | {"ai_overview": {"page_token": "private"}, "inline_videos": [], "local_results": {"places": []}, "related_questions": [{"question": "How?"}]}
        result = normalize(payload, SEARCH, START.isoformat(), None)
        self.assertEqual(result["features"], ["related_questions"])
        self.assertEqual(result["ai_overview_status"], "requires_followup")

    def test_sparse_or_malformed_results_do_not_become_full_serps(self):
        payload = response(count=2)
        payload["organic_results"] += [None, {"position": 3, "link": "javascript:bad"}, payload["organic_results"][0]]
        result = normalize(payload, SEARCH, START.isoformat(), None)
        self.assertFalse(result["quality_ok"])
        self.assertEqual(len(result["results"]), 2)

    def test_failed_payloads_are_rejected(self):
        for payload in ({"error": "bad"}, {"organic_results": {}}, {"search_metadata": {"status": "Processing"}, "organic_results": []}):
            with self.assertRaises(ValueError):
                normalize(payload, SEARCH, START.isoformat(), None)

    def test_local_content_classification_and_no_raw_content_export(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "page.html"
            path.write_text('<html><title>What is testing? A guide</title><nav>Best pricing buy comparison</nav><main><h1>Testing tutorial</h1><p>Learn how to test.</p></main><script>pricing pricing</script></html>')
            profile = page_profile({"url": "https://page.example/", "content_file": str(path)}, "en", START.isoformat())
            self.assertEqual(profile["intent"], "informational")
            self.assertEqual(profile["basis"], "local content")
            self.assertTrue(profile["content_sha256"])
            self.assertNotIn("script", json.dumps(profile))
            self.assertNotIn(str(path), json.dumps(profile))


class AnalysisTests(unittest.TestCase):
    def test_daily_timer_jitter_does_not_skip_confirmation(self):
        history = [snapshot(day if day < 4 else day - 30 / 86400, "commercial" if day >= 3 else "informational") for day in range(5)]
        self.assertTrue(analyze(TARGET, history, DEFAULTS)["confirmed_mismatch"])
        self.assertEqual(minimum_spacing_seconds(DEFAULTS), 86340)

    def test_identical_serps_zero_score(self):
        baseline = [snapshot(day) for day in range(3)]
        result = compare(baseline, snapshot(3))
        self.assertEqual(result["score"], 0)
        self.assertEqual(result["entered"], [])

    def test_confirmed_shift_and_page_mismatch(self):
        history = [snapshot(day, "informational" if day < 3 else "commercial") for day in range(5)]
        result = analyze(TARGET, history, DEFAULTS)
        self.assertEqual(result["status"], "review")
        self.assertTrue(result["confirmed_intent_shift"])
        self.assertTrue(result["confirmed_mismatch"])
        self.assertEqual(result["baseline_intent"], "informational")

    def test_one_shift_waits_for_confirmation(self):
        result = analyze(TARGET, [snapshot(day, "commercial" if day == 3 else "informational") for day in range(4)], DEFAULTS)
        self.assertEqual(result["status"], "watch")
        self.assertFalse(result["confirmed_mismatch"])

    def test_recovery_clears_alert(self):
        history = [snapshot(day, "commercial" if day in {3, 4} else "informational") for day in range(6)]
        result = analyze(TARGET, history, DEFAULTS)
        self.assertEqual(result["status"], "stable")
        self.assertFalse(result["confirmed_intent_shift"])

    def test_ranking_changes_are_not_intent_changes(self):
        history = [snapshot(day) for day in range(5)]
        for item in history[3:]:
            for row in item["results"]:
                row["position"] = 11 - row["position"]
        result = analyze(TARGET, history, DEFAULTS)
        self.assertGreater(result["score"], 0)
        self.assertFalse(result["confirmed_intent_shift"])
        self.assertFalse(result["confirmed_mismatch"])

    def test_unknowns_do_not_flag_mismatch(self):
        result = analyze(TARGET, [snapshot(day, "unknown") for day in range(5)], DEFAULTS)
        self.assertFalse(result["confirmed_mismatch"])
        self.assertFalse(mismatch(snapshot(0, "unknown")))

    def test_sparse_latest_suppresses_alert(self):
        history = [snapshot(day, "commercial" if day >= 3 else "informational", 2 if day == 4 else 10) for day in range(5)]
        result = analyze(TARGET, history, DEFAULTS)
        self.assertEqual(result["status"], "insufficient_data")
        self.assertFalse(result["confirmed_mismatch"])

    def test_gap_breaks_confirmation(self):
        history = [snapshot(day) for day in range(3)] + [snapshot(3, "commercial"), snapshot(7, "commercial")]
        result = analyze(TARGET, history, DEFAULTS)
        self.assertFalse(result["confirmed_mismatch"])
        self.assertEqual(result["status"], "watch")

    def test_force_runs_cannot_fake_confirmation(self):
        history = [snapshot(day) for day in range(3)] + [snapshot(3, "commercial"), snapshot(3.01, "commercial")]
        result = analyze(TARGET, history, DEFAULTS)
        self.assertFalse(result["confirmed_intent_shift"])
        self.assertFalse(result["confirmed_mismatch"])

    def test_stale_and_failed_collection_suppress_action(self):
        history = [snapshot(day, "commercial" if day >= 3 else "informational", source="searchapi") for day in range(5)]
        result = analyze(TARGET, history, DEFAULTS, now=START + timedelta(days=8))
        self.assertEqual(result["status"], "stale")
        self.assertFalse(result["confirmed_mismatch"])
        result = analyze(TARGET, history, DEFAULTS, now=START + timedelta(days=4, hours=2), last_attempt={"attempted_at": (START + timedelta(days=4, hours=1)).isoformat(), "success": False, "code": "http_429"})
        self.assertEqual(result["status"], "collection_error")
        self.assertFalse(result["confirmed_mismatch"])

    def test_page_profile_change_is_compared_to_recent_serps(self):
        history = [snapshot(day, "commercial" if day >= 3 else "informational") for day in range(5)]
        history[-1]["page"]["intent"] = "commercial"
        self.assertFalse(analyze(TARGET, history, DEFAULTS)["confirmed_mismatch"])


class ClientTests(unittest.TestCase):
    def client(self, effects, **overrides):
        class Opener:
            def __init__(self):
                self.calls = []
            def open(self, request, timeout):
                self.calls.append(request)
                effect = effects.pop(0)
                if isinstance(effect, Exception):
                    raise effect
                return BytesIO(json.dumps(effect).encode())
        opener = Opener()
        sleeps = []
        client = SearchApi("test-secret", DEFAULTS | {"request_delay_seconds": 0} | overrides, opener=opener, sleep=sleeps.append)
        return client, opener, sleeps

    def test_authorization_is_header_only(self):
        client, opener, _ = self.client([response()])
        client.search(SEARCH)
        self.assertNotIn("test-secret", opener.calls[0].full_url)
        self.assertEqual(opener.calls[0].get_header("Authorization"), "Bearer test-secret")
        self.assertNotIn("num=", opener.calls[0].full_url)

    def test_429_honors_retry_after(self):
        client, _, sleeps = self.client([HTTPError("https://api.example", 429, "secret", {"Retry-After": "4"}, BytesIO()), response()])
        client.search(SEARCH)
        self.assertEqual(sleeps, [4.0])
        self.assertEqual(client.requests, 2)

    def test_long_retry_after_fails_without_early_retry(self):
        client, _, sleeps = self.client([HTTPError("https://api.example", 429, "secret", {"Retry-After": "3600"}, BytesIO())])
        with self.assertRaises(ApiError) as caught:
            client.search(SEARCH)
        self.assertEqual(caught.exception.code, "rate_limited")
        self.assertEqual(client.requests, 1)
        self.assertEqual(sleeps, [])

    def test_auth_failure_never_retried_or_echoed(self):
        client, _, _ = self.client([HTTPError("https://api.example?api_key=test-secret", 401, "test-secret", {}, BytesIO())])
        with self.assertRaises(ApiError) as caught:
            client.search(SEARCH)
        self.assertNotIn("test-secret", str(caught.exception))
        self.assertEqual(client.requests, 1)

    def test_budget_includes_retries(self):
        client, _, _ = self.client([URLError("test-secret")], max_requests_per_run=1)
        with self.assertRaises(ApiError) as caught:
            client.search(SEARCH)
        self.assertEqual(caught.exception.code, "budget_exhausted")
        self.assertEqual(client.requests, 1)

    def test_error_json_and_empty_key(self):
        client, _, _ = self.client([{"error": "test-secret"}])
        with self.assertRaises(ApiError) as caught:
            client.search(SEARCH)
        self.assertNotIn("test-secret", str(caught.exception))
        with self.assertRaises(ApiError):
            SearchApi("", DEFAULTS)


class PageFetchTests(unittest.TestCase):
    def test_private_and_mixed_dns_results_rejected(self):
        for addresses in (["127.0.0.1"], ["10.0.0.1"], ["169.254.169.254"], ["::1"], ["93.184.215.14", "192.168.1.1"]):
            records = [(2, 1, 6, "", (address, 443)) for address in addresses]
            with patch("serp_drift.page_fetch.socket.getaddrinfo", return_value=records), self.assertRaises(ValueError):
                public_addresses("example.com", 443)

    def test_public_dns_is_available_for_pinned_connection(self):
        with patch("serp_drift.page_fetch.socket.getaddrinfo", return_value=[(2, 1, 6, "", ("93.184.215.14", 443))]):
            self.assertEqual(public_addresses("example.com", 443), ["93.184.215.14"])

    def test_non_web_ports_and_unsafe_schemes_fail_before_network(self):
        for url in ("https://example.com:8080/", "file:///etc/passwd", "http://user:pass@example.com"):
            with self.assertRaises(ValueError):
                fetch_page(url)

    def test_live_html_profile_has_provenance(self):
        with patch("serp_drift.page_fetch.fetch_page", return_value=("<h1>Best tools comparison</h1><p>Compare alternatives.</p>", "text/html", "https://example.com/final/")) as fetch:
            page = page_profile({"url": "https://example.com/", "fetch": True}, "en", START.isoformat(), allow_fetch=True)
            self.assertEqual(page["intent"], "commercial")
            self.assertEqual(page["basis"], "fetched page")
            self.assertEqual(page["resolved_url"], "https://example.com/final/")
            self.assertTrue(page["content_sha256"])
            fetch.assert_called_once()

    def test_validation_does_not_fetch_pages(self):
        with patch("serp_drift.page_fetch.fetch_page") as fetch:
            page_profile({"url": "https://example.com/", "fetch": True}, "en", START.isoformat())
            fetch.assert_not_called()


class WorkflowTests(unittest.TestCase):
    def test_config_and_invalid_inputs(self):
        config = load_config(ROOT / "examples/monitor.example.toml")
        self.assertEqual(len(config["targets"]), 3)
        self.assertEqual(config["targets"][2]["search"]["hl"], "fi")
        original = (ROOT / "examples/monitor.example.toml").read_text()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "monitor.toml"
            for invalid in (original.replace('device = "desktop"', 'device = "unknown"'), original.replace("baseline_size = 3", "baseline_size = 2.5"), original.replace("interval_hours = 24", "interval_hours = nan"), original.replace('[search]', '[search]\napi_key = "secret"')):
                path.write_text(invalid)
                with self.assertRaises(ValueError):
                    load_config(path)

    def test_locale_and_source_separation_and_idempotency(self):
        with tempfile.TemporaryDirectory() as temporary, Store(Path(temporary) / "monitor.sqlite") as store:
            sample = snapshot()
            store.add(TARGET, sample, response())
            store.add(TARGET, sample, response())
            self.assertEqual(len(store.history(TARGET, "synthetic")), 1)
            self.assertEqual(store.history(TARGET, "searchapi"), [])
            other = TARGET | {"identity": search_identity(SEARCH | {"device": "mobile"})}
            self.assertEqual(store.history(other, "synthetic"), [])

    def test_collector_records_failure_without_fake_snapshot(self):
        class Fake:
            requests = 0
            def search(self, search):
                self.requests += 1
                raise ApiError("http_401", "Access denied")
        with tempfile.TemporaryDirectory() as temporary:
            db = Path(temporary) / "monitor.sqlite"
            summary = collect({"settings": DEFAULTS, "targets": [TARGET]}, db, client=Fake())
            with Store(db) as store:
                self.assertEqual(store.history(TARGET), [])
                self.assertEqual(store.last_attempt(TARGET)["code"], "http_401")
            self.assertEqual(summary["failed"], 1)

    def test_collector_skips_before_spending_when_not_due(self):
        class Fake:
            requests = 0
            def search(self, search):
                self.requests += 1
                return response()
        with tempfile.TemporaryDirectory() as temporary:
            db = Path(temporary) / "monitor.sqlite"
            config = {"settings": DEFAULTS, "targets": [TARGET]}
            self.assertEqual(collect(config, db, client=Fake())["collected"], 1)
            second = Fake()
            self.assertEqual(collect(config, db, client=second)["skipped"], 1)
            self.assertEqual(second.requests, 0)

    def test_collector_lock_prevents_overlapping_runs(self):
        with tempfile.TemporaryDirectory() as temporary:
            db = Path(temporary) / "monitor.sqlite"
            with collection_lock(db), self.assertRaises(ValueError), collection_lock(db):
                pass

    def test_retention_removes_provider_metadata_and_tokens(self):
        payload = response() | {"search_metadata": {"json_endpoint": "secret"}, "search_parameters": {"api_key": "secret"}, "ai_overview": {"page_token": "secret", "text_blocks": [{"answer": "Example"}]}}
        self.assertNotIn("secret", json.dumps(retained_payload(payload)))

    def test_demo_has_expected_scenarios_and_exports(self):
        with tempfile.TemporaryDirectory() as temporary:
            report = demo(Path(temporary))
            statuses = {query["id"]: query["status"] for query in report["queries"]}
            self.assertEqual(statuses, {"crm-automation": "review", "technical-seo": "stable", "ai-tools": "watch", "thin-serp": "insufficient_data"})
            self.assertEqual(sum(query["snapshot_count"] for query in report["queries"]), 24)
            self.assertTrue((Path(temporary) / "report.csv").is_file())
            self.assertNotIn("REPORT_DATA_JSON", (Path(temporary) / "index.html").read_text())

    def test_embedded_html_and_csv_injection_are_escaped(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            report = demo(directory)
            report["queries"][0]["query"] = '</script><img src=x onerror="alert(1)">'
            write_report(report, directory)
            self.assertNotIn('</script><img src=x', (directory / "index.html").read_text())
            self.assertEqual(csv_cell('=HYPERLINK("https://evil.example")')[0], "'")
            self.assertEqual(csv_cell("  +SUM(1)"), "'  +SUM(1)")

    def test_missing_database_report_is_actionable(self):
        with tempfile.TemporaryDirectory() as temporary:
            self.assertEqual(main(["report", "--config", str(ROOT / "examples/monitor.example.toml"), "--db", str(Path(temporary) / "missing.sqlite")]), 1)


if __name__ == "__main__":
    unittest.main()


class WorkspaceTests(unittest.TestCase):
    def test_init_creates_layout_and_valid_config(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Workspace(Path(temporary) / "ws")
            path = init_workspace(workspace, query="topical authority", page="https://x.example/topical/", intent="informational", gl="us", hl="en", device="desktop")
            config = load_config(path)
            self.assertEqual(config["targets"][0]["id"], "topical-authority")
            self.assertEqual(config["targets"][0]["page"]["intent"], "informational")
            self.assertTrue((workspace.root / ".gitignore").is_file())
            self.assertTrue(workspace.logs.is_dir())
            with self.assertRaises(ValueError):
                init_workspace(workspace, query=None, page=None, intent=None, gl="us", hl="en", device="desktop")

    def test_key_file_requires_private_permissions(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Workspace(temporary)
            with mock.patch.dict(os.environ, {"SEARCHAPI_API_KEY": ""}):
                self.assertEqual(workspace.api_key(), "")
                path = workspace.save_key("secret-token\n")
                self.assertEqual(oct(path.stat().st_mode & 0o777), "0o600")
                self.assertEqual(workspace.api_key(), "secret-token")
                path.chmod(0o644)
                with self.assertRaises(ValueError):
                    workspace.api_key()
                with self.assertRaises(ValueError):
                    workspace.save_key("has space")
            with mock.patch.dict(os.environ, {"SEARCHAPI_API_KEY": "from-env"}):
                self.assertEqual(workspace.api_key(), "from-env")

    def test_resolution_order(self):
        with tempfile.TemporaryDirectory() as temporary, mock.patch.dict(os.environ, {"SERP_DRIFT_DIR": temporary}):
            self.assertEqual(Workspace.resolve(None).root, Path(temporary).resolve())
            self.assertEqual(Workspace.resolve(Path(temporary) / "x").root, (Path(temporary) / "x").resolve())

    def test_run_once_writes_report_and_log_even_when_collection_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Workspace(temporary)
            init_workspace(workspace, query="test query", page=None, intent=None, gl="us", hl="en", device="desktop")
            with mock.patch.dict(os.environ, {"SEARCHAPI_API_KEY": ""}):
                summary = run_once(workspace)
            self.assertEqual(summary["failed"], 1)
            self.assertIn("missing_key", (workspace.logs / "serp-drift.log").read_text())
            self.assertTrue((workspace.reports / "index.html").is_file())
            with Store(workspace.database) as store:
                self.assertEqual(store.history(load_config(workspace.config)["targets"][0]), [])


class HistoryTests(unittest.TestCase):
    def series(self):
        # Three informational days, then three commercial days with a new URL set.
        return [snapshot(day, "informational") for day in range(3)] + [snapshot(day, "commercial") for day in range(3, 6)]

    def test_compare_sets_matches_single_capture_compare(self):
        snapshots = self.series()
        single = compare(snapshots[:3], snapshots[-1])
        sets = compare_sets(snapshots[:3], snapshots[-1:])
        self.assertEqual(single["score"], sets["score"])
        self.assertEqual(single["components"], sets["components"])
        self.assertEqual(sets["left"]["captures"], 3)
        self.assertEqual(sets["right"]["dominant_intent"], "commercial")
        # Averaging the right side over three commercial captures gives the same intent distance.
        self.assertEqual(compare_sets(snapshots[:3], snapshots[3:])["components"]["intent"], sets["components"]["intent"])

    def test_baseline_from_reanchors_without_deleting_history(self):
        snapshots = self.series()
        original = analyze(TARGET, snapshots, DEFAULTS | {"baseline_size": 3, "confirmations": 2}, now=START + timedelta(days=5, hours=1))
        self.assertEqual(original["baseline_intent"], "informational")
        moved = analyze(TARGET, snapshots, DEFAULTS | {"baseline_size": 3, "confirmations": 2}, now=START + timedelta(days=5, hours=1),
                        baseline_from=(START + timedelta(days=3)).isoformat())
        self.assertEqual(moved["baseline_intent"], "commercial")
        self.assertEqual(moved["snapshot_count"], 3)
        self.assertEqual(moved["baseline_from"], (START + timedelta(days=3)).isoformat())
        self.assertEqual(len(snapshots), 6)

    def test_url_trajectories_and_change_log(self):
        snapshots = self.series()
        trajectories = url_trajectories(snapshots)
        self.assertEqual(len(trajectories["captures"]), 6)
        current = [entry for entry in trajectories["urls"] if entry["current"] == 1][0]
        self.assertEqual(current["positions"], [None, None, None, 1, 1, 1])
        self.assertEqual(current["appearances"], 3)
        gone = [entry for entry in trajectories["urls"] if entry["current"] is None]
        self.assertEqual(len(gone), 10)
        log = change_log(snapshots)
        self.assertEqual(len(log), 5)
        self.assertTrue(log[-1]["quiet"])
        self.assertEqual(len(log[2]["entered"]), 10)
        self.assertEqual(log[2]["intent_before"], "informational")
        self.assertEqual(log[2]["intent_after"], "commercial")

    def test_timeline_and_period_presets(self):
        snapshots = self.series()
        rows = timeline(snapshots, snapshots[:3])
        self.assertEqual([row["phase"] for row in rows], ["baseline"] * 3 + ["monitoring"] * 3)
        self.assertIsNone(rows[0]["score"])
        self.assertGreater(rows[-1]["score"], 50)
        self.assertEqual(len(resolve_side(snapshots, {"preset": "latest"}, snapshots[:3])), 1)
        self.assertEqual(len(resolve_side(snapshots, {"preset": "first_week"}, snapshots[:3])), 6)
        self.assertEqual(len(resolve_side(snapshots, {"from": START.date().isoformat(), "to": (START + timedelta(days=1)).date().isoformat()}, [])), 2)
        self.assertEqual(len(resolve_side(snapshots, {"capture": snapshots[4]["captured_at"]}, [])), 1)
        result = compare_specs(snapshots, snapshots[:3], {"preset": "baseline"}, {"from": (START + timedelta(days=3)).date().isoformat()})
        self.assertEqual(result["right"]["captures"], 3)
        with self.assertRaises(ValueError):
            resolve_side(snapshots, {"nonsense": True}, [])
        with self.assertRaises(ValueError):
            compare_specs(snapshots, [], {"preset": "baseline"}, {"preset": "latest"})
        stability = intent_stability(snapshots)
        self.assertEqual(stability["captures"], 6)
        self.assertEqual(stability["stability"], 0.5)


class StorageV2Tests(unittest.TestCase):
    def test_v1_database_is_migrated_with_indexed_results(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "old.sqlite"
            connection = sqlite3.connect(path)
            connection.executescript("""
                CREATE TABLE snapshots (id INTEGER PRIMARY KEY, target_id TEXT NOT NULL, identity TEXT NOT NULL, captured_at TEXT NOT NULL,
                    source TEXT NOT NULL, normalized TEXT NOT NULL, raw_subset TEXT NOT NULL, UNIQUE(target_id, identity, captured_at, source));
                CREATE TABLE attempts (id INTEGER PRIMARY KEY, target_id TEXT NOT NULL, identity TEXT NOT NULL, attempted_at TEXT NOT NULL,
                    success INTEGER NOT NULL, code TEXT NOT NULL, requests INTEGER NOT NULL);
                PRAGMA user_version=1;""")
            old = snapshot(0, "informational", source="searchapi")
            connection.execute("INSERT INTO snapshots(target_id,identity,captured_at,source,normalized,raw_subset) VALUES(?,?,?,?,?,?)",
                               (TARGET["id"], TARGET["identity"], old["captured_at"], "searchapi", json.dumps(old), "{}"))
            connection.commit(); connection.close()
            with Store(path) as store:
                self.assertEqual(store.connection.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)
                rows = store.url_history(TARGET)
                self.assertEqual(len(rows), 10)
                self.assertEqual(rows[0]["position"], 1)
                self.assertEqual(rows[0]["host"], "test-1.example")

    def test_runs_events_settings_and_raw_retention(self):
        with tempfile.TemporaryDirectory() as temporary, Store(Path(temporary) / "monitor.sqlite") as store:
            old = snapshot(0, "informational", source="searchapi")
            self.assertTrue(store.add(TARGET, old, response()))
            self.assertFalse(store.add(TARGET, old, response()))
            self.assertTrue(store.raw_subset(TARGET, old["captured_at"])["organic_results"])
            self.assertEqual(store.prune_raw(0), 0)
            self.assertEqual(store.prune_raw(30, now=START + timedelta(days=31)), 1)
            self.assertEqual(store.raw_subset(TARGET, old["captured_at"]), {})
            self.assertEqual(len(store.history(TARGET)), 1)
            store.record_run(utc_now(), {"collected": 1, "skipped": 0, "failed": 1, "requests": 2, "errors": {"x": "http_500"}}, "test")
            self.assertEqual(store.runs()[0]["errors"], {"x": "http_500"})
            store.set_setting(TARGET, "baseline_from", "2026-01-01T00:00:00Z")
            self.assertEqual(store.get_setting(TARGET, "baseline_from"), "2026-01-01T00:00:00Z")
            store.set_setting(TARGET, "baseline_from", None)
            self.assertIsNone(store.get_setting(TARGET, "baseline_from"))
            store.add_event("status_change", {"before": "stable", "after": "watch"}, TARGET)
            self.assertEqual(store.events(TARGET)[0]["payload"]["after"], "watch")
            self.assertEqual(store.host_appearances("test-1.example")[0]["position"], 1)


class RulePackTests(unittest.TestCase):
    def tearDown(self):
        packs.reset()

    def test_builtin_packs_define_the_stable_analysis_version(self):
        registry = packs.registry()
        self.assertEqual(registry.languages(), ["en", "fi"])
        self.assertEqual(registry.analysis_version(), "rules-en-fi-v2")
        self.assertTrue(registry.supports("en-GB"))
        self.assertFalse(registry.supports("de"))

    def test_user_pack_extends_and_changes_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            rules = Path(temporary) / "rules"
            rules.mkdir()
            (rules / "de.toml").write_text("language = 'de'\nversion = 1\n[rules]\ninformational = ['\\banleitung\\b']\n", encoding="utf-8")
            (rules / "en.toml").write_text("language = 'en'\n[rules]\ninformational = ['\\bwalkthrough\\b']\n", encoding="utf-8")
            registry = packs.configure(rules)
            self.assertEqual(classify("Komplette Anleitung", language="de")["intent"], "informational")
            self.assertEqual(classify("A complete walkthrough")["intent"], "informational")
            self.assertTrue(registry.analysis_version().startswith("rules-fi-v2+de-en-"))
            self.assertNotEqual(search_identity(SEARCH), search_identity(SEARCH | {"q": "other"}))
            packs.configure(None)
            self.assertEqual(packs.registry().analysis_version(), "rules-en-fi-v2")
            self.assertEqual(classify("A complete walkthrough")["intent"], "unknown")

    def test_invalid_pack_is_rejected(self):
        with self.assertRaises(ValueError):
            packs.load_pack('language = "en"\n[rules]\ncommercial = ["(unclosed"]\n', "test")
        with self.assertRaises(ValueError):
            packs.load_pack('language = "English"\n', "test")
        with self.assertRaises(ValueError):
            packs.load_pack('language = "en"\nversion = 0\n', "test")

    def test_unknown_language_warning_lists_available_packs(self):
        result = normalize(response(), SEARCH | {"hl": "sv"}, START.isoformat(), None)
        self.assertIn("available: en, fi", result["warnings"][0])


class EngineTests(unittest.TestCase):
    def test_request_params_follow_the_engine_and_keep_link_resolution_out_of_identity(self):
        google = SEARCH | {"location": "New York,New York,United States"}
        params = request_params(google)
        self.assertEqual(params["link"], "resolved")
        self.assertEqual(params["location"], "New York,New York,United States")
        self.assertNotIn("link", google)
        self.assertNotIn("link", request_params(google, resolve_links=False))
        youtube = request_params({"engine": "youtube", "q": "x", "gl": "us", "hl": "en", "device": "desktop", "page": 1})
        self.assertEqual(set(youtube), {"engine", "q", "gl", "hl"})
        with self.assertRaises(ValueError):
            request_params({"engine": "duckduckgo", "q": "x"})

    def test_other_engines_normalize_to_the_same_schema(self):
        youtube = {"search_metadata": {"status": "Success"}, "videos": [{"position": index, "title": f"How to do SERP analysis part {index}", "link": f"https://www.youtube.com/watch?v=v{index}", "description": "Tutorial."} for index in range(1, 20)], "shorts": [{"title": "short"}]}
        result = normalize(youtube, SEARCH | {"engine": "youtube"}, START.isoformat(), None)
        self.assertEqual(len(result["results"]), 10)
        self.assertEqual(result["returned_beyond_top"], 9)
        self.assertEqual(result["results"][0]["type"], "video")
        self.assertEqual(result["features"], ["inline_shorts"])
        self.assertEqual(result["ai_overview_status"], "not_applicable")
        shopping = {"search_metadata": {"status": "Success"}, "shopping_results": [{"position": 1, "title": "SEO book", "product_link": "https://www.google.com/shopping/product/1", "price": "$20", "seller": "Store"}]}
        result = normalize(shopping, SEARCH | {"engine": "google_shopping"}, START.isoformat(), None, min_results=1)
        self.assertEqual(result["results"][0]["type"], "product")
        self.assertEqual(result["results"][0]["snippet"], "$20 · Store")
        news = {"search_metadata": {"status": "Success"}, "organic_results": [{"position": 1, "title": "SEO news", "link": "https://news.example/a", "snippet": "s"}]}
        self.assertEqual(normalize(news, SEARCH | {"engine": "google_news"}, START.isoformat(), None, min_results=1)["results"][0]["type"], "news")
        with self.assertRaises(ValueError):
            rows({"organic_results": []}, "youtube")

    def test_config_rejects_engine_parameter_mismatches(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "monitor.toml"
            path.write_text('version = 1\n[[targets]]\nid = "a"\nquery = "x"\n[targets.search]\nengine = "youtube"\n', encoding="utf-8")
            config = load_config(path)
            self.assertNotIn("device", config["targets"][0]["search"])
            path.write_text('version = 1\n[[targets]]\nid = "a"\nquery = "x"\n[targets.search]\nengine = "youtube"\ndevice = "mobile"\n', encoding="utf-8")
            with self.assertRaises(ValueError):
                load_config(path)
            path.write_text('version = 1\n[[targets]]\nid = "a"\nquery = "x"\n[targets.search]\nengine = "bing"\nlocation = "Paris,France"\n', encoding="utf-8")
            with self.assertRaises(ValueError):
                load_config(path)
            path.write_text('version = 1\n[settings]\nai_overview = "sometimes"\n[[targets]]\nid = "a"\nquery = "x"\n', encoding="utf-8")
            with self.assertRaises(ValueError):
                load_config(path)


class AiOverviewTests(unittest.TestCase):
    def overview(self, links):
        return {"text_blocks": [{"type": "paragraph", "answer": "Technical SEO is the practice of optimizing infrastructure."}],
                "markdown": "Technical SEO is…", "reference_links": [{"index": i, "title": f"Ref {i}", "link": link, "source": "Src"} for i, link in enumerate(links)]}

    def test_inline_overview_summary_and_page_citation(self):
        page = page_profile({"url": "https://publisher.example/guide", "intent": "informational"}, "en", START.isoformat())
        payload = response() | {"ai_overview": self.overview(["https://www.publisher.example/guide?utm_source=x", "https://other.example/a", "https://www.google.com/goto?url=abc"])}
        result = normalize(payload, SEARCH, START.isoformat(), page)
        self.assertEqual(result["ai_overview_status"], "observed")
        summary = result["ai_overview"]
        self.assertTrue(summary["page_cited"])
        self.assertTrue(summary["host_cited"])
        self.assertEqual(summary["cited_hosts"], ["publisher.example", "other.example"])
        self.assertEqual(summary["unresolved_links"], 1)
        self.assertEqual(summary["references"], 3)
        self.assertTrue(summary["excerpt"].startswith("Technical SEO"))
        self.assertIsNone(normalize(response(), SEARCH, START.isoformat(), page)["ai_overview"])

    def test_expansion_replaces_token_and_survives_failure(self):
        class Client:
            requests = 0
            def __init__(self, fail=False): self.fail = fail
            def ai_overview(self, token, *, resolve_links=True):
                self.requests += 1
                if self.fail:
                    raise ApiError("http_500", "boom")
                return {"text_blocks": [{"type": "paragraph", "answer": "Answer."}], "reference_links": [{"link": "https://cited.example/"}], "page_token": "should-drop"}
        settings = DEFAULTS | {"ai_overview": "expand"}
        payload = response() | {"ai_overview": {"page_token": "tok"}}
        self.assertTrue(expand_ai_overview(Client(), payload, SEARCH, settings))
        self.assertNotIn("page_token", payload["ai_overview"])
        self.assertEqual(normalize(payload, SEARCH, START.isoformat(), None)["ai_overview"]["cited_hosts"], ["cited.example"])
        payload = response() | {"ai_overview": {"page_token": "tok"}}
        self.assertFalse(expand_ai_overview(Client(fail=True), payload, SEARCH, settings))
        self.assertEqual(normalize(payload, SEARCH, START.isoformat(), None)["ai_overview_status"], "requires_followup")
        self.assertFalse(expand_ai_overview(Client(), response() | {"ai_overview": {"page_token": "tok"}}, SEARCH, settings | {"ai_overview": "skip"}))
        self.assertFalse(expand_ai_overview(Client(), response() | {"ai_overview": {"page_token": "tok"}}, SEARCH | {"engine": "google_light"}, settings))

    def test_overview_text_is_stored_and_citation_history_counts_hosts(self):
        with tempfile.TemporaryDirectory() as temporary, Store(Path(temporary) / "monitor.sqlite") as store:
            first = normalize(response() | {"ai_overview": self.overview(["https://a.example/1", "https://b.example/2"])}, SEARCH, START.isoformat(), None)
            second = normalize(response() | {"ai_overview": self.overview(["https://a.example/1"])}, SEARCH, (START + timedelta(days=1)).isoformat(), None)
            store.add(TARGET, first | {"source": "searchapi"}, response() | {"ai_overview": self.overview(["https://a.example/1", "https://b.example/2"])})
            store.add(TARGET, second | {"source": "searchapi"}, response() | {"ai_overview": self.overview(["https://a.example/1"])})
            stored = store.ai_overview(TARGET, START.isoformat())
            self.assertEqual(len(stored["reference_links"]), 2)
            self.assertEqual(store.ai_overview_count(), 2)
            history = citations(store.history(TARGET))
            self.assertEqual(history["observed"], 2)
            self.assertEqual(history["hosts"][0], {"host": "a.example", "citations": 2, "mine": False})


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace = Workspace(self.temporary.name)
        init_workspace(self.workspace, query="topical authority", page="https://publisher.example/topical/", intent="informational", gl="us", hl="en", device="desktop")
        with Store(self.workspace.database) as store:
            target = load_config(self.workspace.config)["targets"][0]
            now = datetime.now(UTC).replace(microsecond=0)
            for day in range(4):
                # Recent timestamps, so the panel is judged rather than flagged as overdue.
                captured = (now - timedelta(days=3 - day, hours=1)).isoformat()
                intent = "informational" if day < 3 else "commercial"
                page = page_profile({"url": "https://publisher.example/topical/", "intent": "informational"}, "en", captured)
                store.add(target, normalize(response(intent), SEARCH, captured, page, source="searchapi"), response(intent))
        self.state = AppState(self.workspace, scheduler_enabled=False)
        self.server = make_server(self.state, "127.0.0.1", 0)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.temporary.cleanup()

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        payload = json.dumps(body).encode() if body is not None else None
        connection.request(method, path, body=payload, headers={"Content-Type": "application/json", **(headers or {})})
        response = connection.getresponse()
        raw = response.read()
        connection.close()
        try:
            return response.status, json.loads(raw), response.headers
        except ValueError:
            return response.status, raw, response.headers

    CSRF = {"X-Requested-With": "serp-drift"}

    def test_index_status_report_and_panel_views(self):
        status, body, headers = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"SERP Intent Drift Monitor", body)
        self.assertIn("default-src 'self'", headers["Content-Security-Policy"])
        status, body, _ = self.request("GET", "/api/status")
        self.assertEqual(body["panels"], 1)
        self.assertEqual(body["snapshots"], 4)
        status, body, _ = self.request("GET", "/api/report")
        self.assertEqual(body["queries"][0]["status"], "watch")
        status, body, _ = self.request("GET", "/api/panels/topical-authority")
        self.assertEqual(len(body["captures"]), 4)
        self.assertEqual(len(body["trajectories"]["urls"]), 20)
        self.assertEqual(body["changes"][0]["intent_after"], "commercial")
        status, body, _ = self.request("GET", "/api/panels/topical-authority/captures/" + body["captures"][0])
        self.assertEqual(status, 200)
        self.assertIn("organic_results", body["raw"])
        self.assertEqual(self.request("GET", "/api/panels/nope")[0], 404)
        self.assertEqual(self.request("GET", "/assets/app.js")[0], 200)
        self.assertEqual(self.request("GET", "/assets/example-data.json")[0], 404)
        self.assertEqual(self.request("GET", "/assets/../cli.py")[0], 404)

    def test_mutations_need_csrf_header_and_edit_the_config(self):
        self.assertEqual(self.request("POST", "/api/panels", {"query": "x"})[0], 403)
        self.assertEqual(self.request("POST", "/api/panels", {"query": "x"}, {**self.CSRF, "Origin": "http://evil.example"})[0], 403)
        status, body, _ = self.request("POST", "/api/panels", {"query": "seo roi", "engine": "bing", "gl": "gb", "page_url": "https://publisher.example/roi/", "intent": "informational"}, self.CSRF)
        self.assertEqual(status, 201, body)
        self.assertEqual(body["id"], "seo-roi-bing-gb")
        self.assertEqual(body["search"]["engine"], "bing")
        self.assertEqual(len(load_config(self.workspace.config)["targets"]), 2)
        self.assertEqual(self.request("POST", "/api/panels", {"query": "seo roi", "engine": "bing", "gl": "gb"}, self.CSRF)[0], 400)
        status, body, _ = self.request("POST", "/api/settings", {"interval_hours": 12, "ai_overview": "skip"}, self.CSRF)
        self.assertEqual(body["interval_hours"], 12)
        self.assertEqual(load_config(self.workspace.config)["settings"]["ai_overview"], "skip")
        self.assertEqual(self.request("POST", "/api/settings", {"nonsense": 1}, self.CSRF)[0], 400)
        status, body, _ = self.request("POST", "/api/panels/topical-authority/compare", {"left": {"preset": "baseline"}, "right": {"preset": "latest"}}, self.CSRF)
        self.assertEqual(status, 200, body)
        self.assertGreater(body["score"], 50)
        status, body, _ = self.request("POST", "/api/panels/topical-authority/compare", {"left": {"preset": "first_week"}, "right": {"preset": "latest"}}, self.CSRF)
        self.assertEqual(body["left"]["captures"], 4)
        today = datetime.now(UTC).date().isoformat()
        status, body, _ = self.request("POST", "/api/panels/topical-authority/baseline", {"from": today}, self.CSRF)
        self.assertEqual(body["baseline_from"], today + "T00:00:00Z")
        status, body, _ = self.request("GET", "/api/panels/topical-authority")
        self.assertEqual(body["analysis"]["snapshot_count"], 1)
        status, body, _ = self.request("DELETE", "/api/panels/seo-roi-bing-gb", None, self.CSRF)
        self.assertEqual(body["removed"], "seo-roi-bing-gb")
        self.assertEqual(len(load_config(self.workspace.config)["targets"]), 1)
        status, body, _ = self.request("GET", "/api/runs")
        self.assertEqual([event["kind"] for event in body["events"]][:3], ["panel_removed", "baseline_moved", "panel_added"])
        status, body, _ = self.request("POST", "/api/notify", {"webhook_url": "https://hook.example/x", "format": "slack", "on": ["review"]}, self.CSRF)
        self.assertEqual(body["format"], "slack")
        status, raw, headers = self.request("GET", "/api/digest.svg?days=7")
        self.assertEqual(status, 200)
        self.assertTrue(headers["Content-Type"].startswith("image/svg+xml"))
        status, body, _ = self.request("GET", "/api/digest?days=7")
        self.assertEqual(body["panels"], 1)
        status, body, _ = self.request("GET", "/api/insights?days=30")
        self.assertEqual(body["panels"], 1)
        status, raw, headers = self.request("GET", "/api/export/dataset.zip")
        self.assertEqual(headers["Content-Type"], "application/zip")
        self.assertEqual(len(zipfile.ZipFile(io.BytesIO(raw)).namelist()), 6)

    def test_token_protection(self):
        state = AppState(self.workspace, token="secret-token", scheduler_enabled=False)
        server = make_server(state, "127.0.0.1", 0)
        port = server.server_address[1]
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            def call(path, headers=None):
                connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                connection.request("GET", path, headers=headers or {})
                response = connection.getresponse(); response.read(); connection.close()
                return response.status, response.headers
            self.assertEqual(call("/api/status")[0], 401)
            self.assertEqual(call("/")[0], 401)
            self.assertEqual(call("/api/status", {"Authorization": "Bearer wrong"})[0], 401)
            self.assertEqual(call("/api/status", {"Authorization": "Bearer secret-token"})[0], 200)
            status, headers = call("/?token=secret-token")
            self.assertEqual(status, 303)
            self.assertIn("serp_drift_token=secret-token", headers["Set-Cookie"])
            self.assertEqual(call("/api/status", {"Cookie": "serp_drift_token=secret-token"})[0], 200)
        finally:
            server.shutdown(); server.server_close()


class NotifyTests(unittest.TestCase):
    def workspace_with_history(self):
        temporary = tempfile.TemporaryDirectory()
        workspace = Workspace(temporary.name)
        init_workspace(workspace, query="topical authority", page="https://publisher.example/topical/", intent="informational", gl="us", hl="en", device="desktop")
        config = load_config(workspace.config)
        target = config["targets"][0]
        now = datetime.now(UTC).replace(microsecond=0)
        with Store(workspace.database) as store:
            for day in range(4):
                captured = (now - timedelta(days=3 - day, hours=1)).isoformat()
                intent = "informational" if day < 3 else "commercial"
                overview = {"text_blocks": [{"type": "paragraph", "answer": "Answer."}], "reference_links": [{"link": "https://publisher.example/topical/"}, {"link": "https://other.example/x"}]}
                payload = response(intent) | ({"ai_overview": overview} if day >= 2 else {})
                page = page_profile(target["page"], "en", captured)
                store.add(target, normalize(payload, SEARCH, captured, page, source="searchapi"), payload)
        return temporary, workspace, config

    def test_payload_formats(self):
        body, headers = notify.payload_for("slack", "T", "hello", {})
        self.assertEqual(json.loads(body)["text"], "*T*\nhello")
        body, headers = notify.payload_for("discord", "T", "hello", {})
        self.assertIn("content", json.loads(body))
        body, headers = notify.payload_for("ntfy", "Tïtle", "hello", {})
        self.assertEqual(body, b"hello"); self.assertEqual(headers["Title"], "Ttle")
        body, headers = notify.payload_for("json", "T", "hello", {"event": "x"})
        self.assertEqual(json.loads(body)["event"], "x")

    def test_status_changes_notify_once_and_respect_the_filter(self):
        temporary, workspace, config = self.workspace_with_history()
        try:
            sent = []
            sender = lambda url, fmt, title, text, data: sent.append((url, fmt, title, text, data)) or {"ok": True, "status": 200}
            with Store(workspace.database) as store:
                report = build_report(config, store)
                first = notify.after_run(config, store, report, sender=sender)
                self.assertEqual(first["changes"], 1)
                self.assertEqual(first["notified"], 0)  # first observation is not a change
                self.assertEqual(notify.after_run(config, store, report, sender=sender)["changes"], 0)
                store.set_setting({"id": report["queries"][0]["id"], "identity": report["queries"][0]["identity"]}, "last_status", "stable")
                config_on = config | {"notify": config["notify"] | {"webhook_url": "https://hook.example/x", "on": ["watch"]}}
                result = notify.after_run(config_on, store, report, sender=sender)
                self.assertEqual(result["notified"], 1)
                self.assertIn("Stable → Watch changes", sent[0][3])
                self.assertEqual(sent[0][4]["event"], "status_change")
                self.assertEqual(store.events()[0]["kind"], "notification")
                store.set_setting({"id": report["queries"][0]["id"], "identity": report["queries"][0]["identity"]}, "last_status", "stable")
                config_off = config | {"notify": config["notify"] | {"webhook_url": "https://hook.example/x", "on": ["review"]}}
                self.assertEqual(notify.after_run(config_off, store, report, sender=sender)["notified"], 0)
        finally:
            temporary.cleanup()

    def test_digest_content_and_cadence(self):
        temporary, workspace, config = self.workspace_with_history()
        try:
            with Store(workspace.database) as store:
                report = build_report(config, store)
                data = notify.digest(config, store, report, days=7)
                self.assertEqual(data["captures"], 4)
                self.assertEqual(data["ai_overviews"], 2)
                self.assertEqual(data["page_cited"], 2)
                self.assertEqual(data["hosts"][0]["host"], "other.example")
                markdown = notify.digest_markdown(data)
                self.assertIn("# SERP drift digest", markdown)
                self.assertIn("topical authority", markdown)
                svg = notify.digest_svg(data)
                self.assertTrue(svg.startswith("<svg"))
                self.assertIn("topical authority", svg)
                self.assertIn("&lt;", notify.digest_svg(data | {"movers": [{"query": "<b>", "score": 1, "status": "watch", "page_position": None, "id": "x"}]}))
                self.assertFalse(notify.digest_due(config, store))
                weekly = config | {"notify": config["notify"] | {"webhook_url": "https://hook.example/x", "digest": "weekly", "digest_day": "monday"}}
                monday = datetime(2026, 9, 14, 9, tzinfo=UTC)
                self.assertTrue(notify.digest_due(weekly, store, now=monday))
                self.assertFalse(notify.digest_due(weekly, store, now=monday + timedelta(days=1)))
                sent = []
                notify.send_digest(weekly, store, report, sender=lambda *args: sent.append(args) or {"ok": True, "status": 200}, now=monday)
                self.assertEqual(sent[0][4]["event"], "digest")
                self.assertFalse(notify.digest_due(weekly, store, now=monday + timedelta(hours=2)))
                self.assertTrue(notify.digest_due(weekly, store, now=monday + timedelta(days=7)))
                daily = weekly | {"notify": weekly["notify"] | {"digest": "daily"}}
                self.assertTrue(notify.digest_due(daily, store, now=monday + timedelta(days=1)))
        finally:
            temporary.cleanup()

    def test_notify_config_validation_and_update(self):
        self.assertEqual(validate_notify({})["format"], "json")
        for bad in ({"webhook_url": "ftp://x"}, {"format": "sms"}, {"on": ["nonsense"]}, {"digest": "hourly"}, {"digest_day": "maanantai"}, {"extra": 1}):
            with self.assertRaises(ValueError):
                validate_notify(bad)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "monitor.toml"
            path.write_text('version = 1\n\n[search]\ngl = "us"\n\n[[targets]]\nid = "a"\nquery = "a"\n', encoding="utf-8")
            result = update_notify(path, {"webhook_url": "https://hook.example/x", "on": ["review"], "digest": "weekly"})
            self.assertEqual(result["on"], ["review"])
            self.assertEqual(load_config(path)["notify"]["digest"], "weekly")
            self.assertEqual(update_notify(path, {"format": "ntfy"})["webhook_url"], "https://hook.example/x")
            self.assertEqual(len(load_config(path)["targets"]), 1)

    def test_send_handles_http_failures_without_raising(self):
        class Opener:
            def open(self, request, timeout=0):
                from urllib.error import HTTPError
                raise HTTPError(request.full_url, 500, "boom", {}, None)
        self.assertEqual(notify.send("https://hook.example/x", "json", "t", "x", {}, opener=Opener()), {"ok": False, "status": 500})


class ScheduleTests(unittest.TestCase):
    def test_plans_for_each_platform(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Workspace(temporary)
            mac = schedule.plan(workspace, "app", time="08:17", port=8765, platform="darwin")
            self.assertEqual(mac["platform"], "launchd")
            path, body = next(iter(mac["files"].items()))
            self.assertTrue(path.endswith(".plist"))
            plist = plistlib.loads(body.encode())
            self.assertTrue(plist["KeepAlive"])
            self.assertEqual(plist["ProgramArguments"][-3:], ["serve", "--port", "8765"])
            multi = plistlib.loads(next(iter(schedule.plan(workspace, "app", time="08:17", port=8765, platform="darwin", extra_dirs=[Path(temporary) / "other"])["files"].values())).encode())
            self.assertEqual(multi["ProgramArguments"][-2], "--also")
            self.assertLess(multi["ProgramArguments"].index("serve"), multi["ProgramArguments"].index("--also"))
            self.assertIn(str(workspace.root), plist["ProgramArguments"])
            self.assertLess(len(plist["EnvironmentVariables"]["PATH"]), 300)
            # From a source checkout without an installed console script the job must still import the package from any cwd.
            with mock.patch.object(schedule.shutil, "which", return_value=None):
                checkout = plistlib.loads(next(iter(schedule.plan(workspace, "app", time="08:17", port=8765, platform="darwin")["files"].values())).encode())
                self.assertEqual(checkout["ProgramArguments"][1:3], ["-m", "serp_drift"])
                self.assertTrue((Path(checkout["EnvironmentVariables"]["PYTHONPATH"]) / "serp_drift" / "cli.py").is_file())
                self.assertIn("PYTHONPATH=", schedule.cron_line(workspace, time="08:17"))
            with mock.patch.object(schedule.shutil, "which", return_value="/usr/local/bin/serp-drift"):
                installed = plistlib.loads(next(iter(schedule.plan(workspace, "app", time="08:17", port=8765, platform="darwin")["files"].values())).encode())
                self.assertEqual(installed["ProgramArguments"][0], "/usr/local/bin/serp-drift")
                self.assertNotIn("PYTHONPATH", installed["EnvironmentVariables"])
            daily = plistlib.loads(next(iter(schedule.plan(workspace, "run", time="06:30", port=8765, platform="darwin")["files"].values())).encode())
            self.assertEqual(daily["StartCalendarInterval"], {"Hour": 6, "Minute": 30})
            self.assertNotIn("KeepAlive", daily)
            linux = schedule.plan(workspace, "run", time="08:17", port=8765, platform="linux")
            self.assertEqual(linux["platform"], "systemd")
            self.assertEqual(len(linux["files"]), 2)
            timer = [body for path, body in linux["files"].items() if path.endswith(".timer")][0]
            self.assertIn("OnCalendar=*-*-* 08:17:00", timer)
            self.assertIn("Persistent=true", timer)
            self.assertIn("cron alternative", linux["note"].lower())
            other = schedule.plan(workspace, "run", time="08:17", port=8765, platform="win32")
            self.assertEqual(other["platform"], "cron")
            self.assertIn("17 8 * * *", other["note"])
            with self.assertRaises(ValueError):
                schedule.plan(workspace, "run", time="25:00", port=8765, platform="darwin")

    def test_apply_writes_files_and_tolerates_bootout(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "unit.plist"
            plan_data = {"platform": "launchd", "files": {str(target): "<plist/>"}, "install": [["launchctl", "bootout", "gui/1", str(target)]], "uninstall": [], "note": ""}
            calls = []
            class Result:
                def __init__(self, code): self.returncode = code; self.stderr = "nope" if code else ""
            with mock.patch.object(schedule.subprocess, "run", side_effect=lambda command, **kw: calls.append(command) or Result(1)):
                log = schedule.apply(plan_data)
            self.assertTrue(target.is_file())
            self.assertTrue(log[1].startswith("skipped"))
            with mock.patch.object(schedule.subprocess, "run", side_effect=lambda command, **kw: Result(0)):
                log = schedule.apply(plan_data, uninstall=True)
            self.assertFalse(target.exists())
            plan_data["install"] = [["false-command"]]
            with mock.patch.object(schedule.subprocess, "run", side_effect=lambda command, **kw: Result(2)), self.assertRaises(ValueError):
                schedule.apply(plan_data)


class InsightsTests(unittest.TestCase):
    def test_compute_and_dataset(self):
        temporary, workspace, config = NotifyTests().workspace_with_history()
        try:
            with Store(workspace.database) as store:
                data = insights.compute(config, store)
                self.assertEqual(data["panels"], 1)
                self.assertEqual(data["captures"], 4)
                metrics = data["panel_metrics"][0]
                self.assertEqual(metrics["ai_overview_observed"], 2)
                self.assertEqual(metrics["page_cited"], 2)
                self.assertEqual(metrics["intent"], "informational")
                self.assertGreater(metrics["turnover"], 0)
                self.assertEqual(data["hosts"][0]["host"], "other.example")
                self.assertEqual(data["by"]["language"]["en"]["panels"], 1)
                self.assertEqual(data["your_pages"]["tracked"], 1)
                self.assertEqual(insights.compute(config, store, days=1)["captures"], 1)
                files = insights.dataset(config, store)
                self.assertEqual(files["captures.csv"].count("\n"), 5)
                self.assertEqual(files["results.csv"].count("\n"), 41)
                self.assertEqual(files["citations.csv"].count("\n"), 5)
                self.assertIn("topical authority", files["captures.csv"])
                archive = zipfile.ZipFile(io.BytesIO(insights.dataset_zip(files)))
                self.assertEqual(len(archive.namelist()), 6)
                # AI Overview prevalence in the digest counts observed Overviews, not only stored citations.
                report = build_report(config, store)
                self.assertEqual(notify.digest(config, store, report, days=7)["ai_overviews"], 2)
        finally:
            temporary.cleanup()


class LocationTests(unittest.TestCase):
    def test_locations_parse_list_payloads_without_spending_the_budget_twice(self):
        class Response:
            status = 200
            def __init__(self, body): self.body = body
            def read(self, n=-1): return self.body
            def __enter__(self): return self
            def __exit__(self, *args): return False
        class Opener:
            calls = []
            def open(self, request, timeout=0):
                self.calls.append(request.full_url)
                self.assertion = "locations" in request.full_url
                return Response(json.dumps([{"canonical_name": "Turku,Southwest Finland,Finland", "name": "Turku", "country_code": "FI"}, "junk"]).encode())
        client = SearchApi("secret-key-123", DEFAULTS, opener=Opener(), sleep=lambda s: None)
        rows = client.locations("Turku")
        self.assertEqual(rows[0]["canonical_name"], "Turku,Southwest Finland,Finland")
        self.assertEqual(len(rows), 1)
        self.assertIn("/api/v1/locations?", Opener.calls[0])
        self.assertNotIn("secret-key-123", Opener.calls[0])

    def test_server_location_lookup_is_cached_and_short_queries_are_ignored(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Workspace(temporary)
            init_workspace(workspace, query="x", page=None, intent=None, gl="us", hl="en", device="desktop")
            state = AppState(workspace, scheduler_enabled=False)
            self.assertEqual(state.locations("T"), [])
            with mock.patch.object(SearchApi, "locations", return_value=[{"canonical_name": "Turku,Southwest Finland,Finland", "target_type": "Municipality", "country_code": "FI", "reach": 1, "google_id": 1}]) as lookup:
                with mock.patch.object(Workspace, "api_key", return_value="k"):
                    first = state.locations("Turku")
                    second = state.locations("turku ")
            self.assertEqual(first, second)
            self.assertNotIn("google_id", first[0])
            self.assertEqual(lookup.call_count, 1)


class McpTests(unittest.TestCase):
    def test_json_rpc_lifecycle_and_tools(self):
        temporary, workspace, _config = NotifyTests().workspace_with_history()
        try:
            server = McpServer(workspace)
            init = server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}})
            self.assertEqual(init["result"]["serverInfo"]["name"], "serp-drift")
            self.assertIsNone(server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))
            self.assertEqual(server.handle({"jsonrpc": "2.0", "id": 2, "method": "ping"})["result"], {})
            tools = server.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/list"})["result"]["tools"]
            self.assertIn("compare", [tool["name"] for tool in tools])
            call = lambda name, args=None: server.handle({"jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": {"name": name, "arguments": args or {}}})["result"]
            panels = json.loads(call("list_panels")["content"][0]["text"])["panels"]
            self.assertEqual(panels[0]["id"], "topical-authority")
            panel = json.loads(call("panel", {"id": "topical-authority"})["content"][0]["text"])
            self.assertEqual(len(panel["results"]), 10)
            self.assertEqual(panel["latest_intent"], "commercial")
            history = json.loads(call("history", {"id": "topical-authority", "limit": 2})["content"][0]["text"])
            self.assertEqual(len(history["timeline"]), 2)
            compare = json.loads(call("compare", {"id": "topical-authority", "left": {"preset": "baseline"}, "right": {"preset": "latest"}})["content"][0]["text"])
            self.assertGreater(compare["score"], 50)
            citations = json.loads(call("citations", {"id": "topical-authority"})["content"][0]["text"])
            self.assertEqual(citations["observed"], 2)
            insights_data = json.loads(call("insights", {"days": 30})["content"][0]["text"])
            self.assertEqual(insights_data["panels"], 1)
            host = json.loads(call("search_host", {"host": "www.test-1.example"})["content"][0]["text"])
            self.assertEqual(host["total"], 4)
            self.assertTrue(call("panel", {"id": "missing"})["isError"])
            self.assertEqual(server.handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "nope"}})["error"]["code"], -32602)
            self.assertEqual(server.handle({"jsonrpc": "2.0", "id": 5, "method": "unknown"})["error"]["code"], -32601)
            stdin = io.StringIO('{"jsonrpc":"2.0","id":1,"method":"ping"}\nnot json\n')
            stdout = io.StringIO()
            server.serve(stdin=stdin, stdout=stdout)
            lines = [json.loads(line) for line in stdout.getvalue().splitlines()]
            self.assertEqual(lines[0]["result"], {})
            self.assertEqual(lines[1]["error"]["code"], -32700)
        finally:
            temporary.cleanup()


class LabelingTests(unittest.TestCase):
    class Opener:
        def __init__(self, answers, status=200):
            self.answers, self.status, self.calls = answers, status, 0
        def open(self, request, timeout=0):
            self.calls += 1
            from urllib.error import HTTPError
            if self.status != 200:
                raise HTTPError(request.full_url, self.status, "boom", {}, None)
            body = json.loads(request.data)
            items = json.loads(body["messages"][1]["content"])
            content = "Sure! " + json.dumps({item["id"]: {"intent": self.answers.get(item["title"], "unknown"), "format": "comparison", "task": "evaluate resources", "evidence": item["title"]} for item in items})
            payload = json.dumps({"choices": [{"message": {"content": content}}]}).encode()
            class Response:
                def read(self_inner, n=-1): return payload
                def __enter__(self_inner): return self_inner
                def __exit__(self_inner, *args): return False
            return Response()

    def test_unknowns_are_labelled_cached_and_aggregates_recomputed(self):
        section = labeling.validate({"provider": "openai", "model": "test-model"})
        opener = self.Opener({"Selected resources": "commercial"})
        labeler = labeling.Labeler(section, "key", opener=opener)
        with tempfile.TemporaryDirectory() as temporary, Store(Path(temporary) / "m.sqlite") as store:
            snapshot = normalize(response("unknown"), SEARCH, START.isoformat(), None)
            self.assertEqual(snapshot["dominant_intent"], "unknown")
            changed = labeling.apply(snapshot, labeler, store)
            self.assertEqual(changed, 10)
            self.assertEqual(snapshot["dominant_intent"], "commercial")
            self.assertEqual(snapshot["results"][0]["type"], "comparison")
            self.assertIn("llm: test-model → commercial", snapshot["results"][0]["evidence"])
            self.assertEqual(opener.calls, 1)
            again = normalize(response("unknown"), SEARCH, START.isoformat(), None)
            labeling.apply(again, labeler, store)
            self.assertEqual(opener.calls, 1)  # served from the cache
            self.assertEqual(labeling.apply(normalize(response("informational"), SEARCH, START.isoformat(), None), labeler, store), 0)
            failing = labeling.Labeler(section, "key", opener=self.Opener({}, status=500))
            broken = normalize(response("unknown") | {"organic_results": [{"position": 1, "title": "Other", "link": "https://o.example/", "snippet": ""}]}, SEARCH, START.isoformat(), None, min_results=1)
            self.assertEqual(labeling.apply(broken, failing, store), 0)
            self.assertEqual(broken["labeling"]["errors"], ["http_500"])

    def test_config_validation_and_identity_tag(self):
        self.assertEqual(labeling.validate({})["provider"], "none")
        self.assertEqual(labeling.identity_tag(labeling.validate({})), "")
        self.assertRegex(labeling.identity_tag(labeling.validate({"provider": "openai", "model": "GPT 4o-mini"})), r"^\+llm-[a-f0-9]{12}$")
        for bad in ({"provider": "anthropic"}, {"provider": "openai"}, {"provider": "openai", "model": "m", "base_url": "ftp://x"}, {"batch_size": 0}, {"nope": 1}):
            with self.assertRaises(ValueError):
                labeling.validate(bad)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "monitor.toml"
            path.write_text('version = 1\n[[targets]]\nid = "a"\nquery = "a"\n', encoding="utf-8")
            plain = load_config(path)["targets"][0]["identity"]
            path.write_text('version = 1\n[labeling]\nprovider = "openai"\nmodel = "m"\n[[targets]]\nid = "a"\nquery = "a"\n', encoding="utf-8")
            config = load_config(path)
            self.assertNotEqual(config["targets"][0]["identity"], plain)
            self.assertIn("+llm-", config["analysis_version"])
            with mock.patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
                with self.assertRaises(ValueError):
                    labeling.Labeler.from_config(config, Workspace(temporary))
            self.assertIsNone(labeling.Labeler.from_config(load_config(path) | {"labeling": labeling.DEFAULTS}, Workspace(temporary)))


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.a = Workspace(root / "alpha")
        init_workspace(self.a, query="topical authority", page=None, intent=None, gl="us", hl="en", device="desktop")
        update_project(self.a.config, {"name": "Alpha", "site": "https://www.publisher.example/"})
        self.b = Workspace(root / "beta")
        init_workspace(self.b, query="seo roi", page=None, intent=None, gl="fi", hl="fi", device="desktop")
        now = datetime.now(UTC).replace(microsecond=0)
        with Store(self.a.database) as store:
            target = load_config(self.a.config)["targets"][0]
            for day in range(5):
                captured = (now - timedelta(days=4 - day, hours=1)).isoformat()
                intent = "informational" if day < 3 else "commercial"
                payload = response(intent) | {"ai_overview": {"text_blocks": [{"type": "paragraph", "answer": "A."}], "reference_links": [{"link": "https://publisher.example/x"}]}}
                if day >= 3:  # publisher.example starts ranking on day 3 with a new URL on day 4
                    payload["organic_results"][1]["link"] = f"https://www.publisher.example/{'guide' if day == 3 else 'blog'}"
                store.add(target, normalize(payload, SEARCH | {"hl": "en"}, captured, None, source="searchapi"), payload)
        self.app = App([ProjectState(self.a, "alpha"), ProjectState(self.b, "beta")], scheduler_enabled=False, projects_root=root)
        self.server = make_server(self.app, "127.0.0.1", 0)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.temporary.cleanup()

    def request(self, method, path, body=None, raw=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        payload = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        connection.request(method, path, body=payload, headers={"Content-Type": "text/csv" if raw is not None else "application/json", "X-Requested-With": "serp-drift", **(headers or {})})
        response = connection.getresponse()
        data = response.read(); connection.close()
        try:
            return response.status, json.loads(data)
        except ValueError:
            return response.status, data

    def test_site_detection_ranking_url_change_and_attention(self):
        status, body = self.request("GET", "/api/p/alpha/panels/topical-authority")
        self.assertEqual(status, 200, body)
        site = body["analysis"]["site"]
        self.assertEqual(site["position"], 2)
        self.assertTrue(site["url"].endswith("/blog"))
        self.assertTrue(site["ranking_url_changed"])
        self.assertTrue(site["cited"])
        self.assertEqual(body["analysis"]["page_position"], 2)
        self.assertTrue(body["changes"][0]["ranking_url_changed"])
        self.assertTrue(body["trajectories"]["urls"][1]["mine"] or any(url["mine"] for url in body["trajectories"]["urls"]))
        self.assertEqual(body["citations"]["site_cited"], 5)
        self.assertEqual(body["timeline"][-1]["site_position"], 2)
        status, body = self.request("GET", "/api/portfolio")
        self.assertEqual([row["id"] for row in body["projects"]], ["alpha", "beta"])
        self.assertEqual(body["projects"][0]["site"], "publisher.example")
        self.assertEqual(body["projects"][0]["counts"].get("review", 0) + body["projects"][0]["counts"].get("watch", 0), 1)
        kinds = {item["kind"] for item in body["attention"]}
        self.assertIn("config", kinds)  # no API key in the temp workspaces
        status, body = self.request("GET", "/api/p/alpha/attention")
        self.assertEqual(status, 200)
        status, body = self.request("GET", "/api/p/nope/status")
        self.assertEqual(status, 404)

    def test_acknowledge_pause_page_project_and_activity(self):
        status, body = self.request("POST", "/api/p/alpha/panels/topical-authority/acknowledge", {})
        self.assertEqual(status, 200); self.assertTrue(body["acknowledged_at"])
        status, body = self.request("POST", "/api/p/alpha/panels/topical-authority/pause", {"paused": True})
        self.assertTrue(body["paused"])
        status, body = self.request("GET", "/api/p/alpha/report")
        self.assertTrue(body["queries"][0]["paused"])
        self.assertTrue(body["queries"][0]["acknowledged_at"])
        status, body = self.request("POST", "/api/p/alpha/panels/topical-authority/page", {"page_url": "https://publisher.example/guide", "intent": "commercial"})
        self.assertEqual(body["page"]["intent"], "commercial")
        self.assertEqual(load_config(self.a.config)["targets"][0]["page"]["intent"], "commercial")
        status, body = self.request("POST", "/api/p/alpha/panels/topical-authority/page", {"page_url": None})
        self.assertIsNone(body["page"])
        self.assertNotIn("page", load_config(self.a.config)["targets"][0])
        status, body = self.request("POST", "/api/p/beta/project", {"name": "Beta Oy", "site": "beta.example"})
        self.assertEqual(body["site"], "beta.example")
        self.assertEqual(self.request("POST", "/api/p/beta/project", {"site": "not a host"})[0], 400)
        status, body = self.request("GET", "/api/p/alpha/activity")
        self.assertEqual([event["kind"] for event in body["events"]][:2], ["paused", "acknowledged"])

    def test_import_preview_bulk_add_and_project_creation(self):
        csv_text = "Top queries,Clicks,Impressions,CTR,Position\ntopical authority,4,5107,0.08%,26.7\nagentic seo,1,1572,0.06%,12.2\nwhat is seo,0,900,0%,8.1\n"
        status, body = self.request("POST", "/api/p/alpha/import/preview", raw=csv_text.encode())
        self.assertEqual(status, 200, body)
        self.assertEqual(body["total"], 3)
        self.assertTrue(body["candidates"][0]["existing"])
        self.assertEqual(body["candidates"][2]["suggested_intent"], "informational")
        status, body = self.request("POST", "/api/p/alpha/import/preview", {"text": csv_text})
        self.assertEqual(body["total"], 3)
        status, body = self.request("POST", "/api/p/alpha/panels/bulk", {"panels": [{"query": "agentic seo", "intent": "informational"}, {"query": "what is seo"}, {"query": "topical authority"}, {"query": ""}], "source": "gsc"})
        self.assertEqual(status, 201, body)
        self.assertEqual(len(body["created"]), 2)
        self.assertEqual(body["skipped"], ["topical authority"])
        self.assertEqual(len(body["errors"]), 1)
        self.assertEqual(len(load_config(self.a.config)["targets"]), 3)
        status, body = self.request("POST", "/api/projects", {"name": "Gamma", "site": "gamma.example", "gl": "de", "hl": "de"})
        self.assertEqual(status, 201, body)
        self.assertEqual(body["id"], "gamma")
        self.assertTrue((Path(self.temporary.name) / "gamma" / "monitor.toml").is_file())
        self.assertEqual(load_config(Path(self.temporary.name) / "gamma" / "monitor.toml")["project"]["site"], "gamma.example")
        self.assertEqual(self.request("POST", "/api/projects", {"name": "Gamma"})[0], 400)
        status, body = self.request("GET", "/api/projects")
        self.assertEqual(len(body["projects"]), 3)
        status, body = self.request("GET", "/api/status")
        self.assertTrue(body["multi_project"])
        self.assertEqual(body["project"]["id"], "alpha")

    def test_ahrefs_fetch_key_and_cli_import(self):
        status, body = self.request("POST", "/api/p/alpha/key", {"key": "ahrefs-token-123", "service": "ahrefs"})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["service"], "ahrefs")
        self.assertEqual(os.stat(self.a.root / "ahrefs.key").st_mode & 0o777, 0o600)
        self.assertEqual(self.request("POST", "/api/p/alpha/key", {"key": "x", "service": "other"})[0], 400)
        status, body = self.request("GET", "/api/p/alpha/status")
        self.assertEqual(body["integrations"]["ahrefs"]["key"], "file")
        self.assertEqual(body["integrations"]["ahrefs"]["per_row_units"], 19)
        def fetch(token, target, **kw):
            return ahrefs_keywords(token, target, opener=FakeAhrefs(AHREFS_PAYLOAD), **kw)
        with patch("serp_drift.server.ahrefs_keywords", side_effect=fetch):
            status, body = self.request("POST", "/api/p/alpha/import/fetch", {"country": "us", "limit": 100})
            self.assertEqual(status, 200, body)
            self.assertEqual(body["source"]["name"], "ahrefs")
            self.assertEqual(body["source"]["target"], "publisher.example")
            self.assertEqual(body["source"]["units"], 1900)
            self.assertEqual(body["total"], 3)
            first = body["candidates"][0]
            self.assertEqual((first["query"], first["volume"], first["position"], first["url"], first["source_intent"]), ("keyword research", 12000, 3.0, "https://www.publisher.example/keyword-research", "informational"))
            self.assertTrue(next(c for c in body["candidates"] if c["query"].lower() == "topical authority")["existing"])
            self.assertTrue(next(c for c in body["candidates"] if c["query"] == "publisher login")["branded"])
            self.assertEqual(self.request("POST", "/api/p/alpha/import/fetch", {"source": "semrush"})[0], 400)
            status, body = self.request("POST", "/api/p/beta/import/fetch", {"target": "beta.example"})
            self.assertEqual(status, 400)
            self.assertIn("No Ahrefs API token", body["error"])
            self.assertEqual(self.request("POST", "/api/p/beta/import/fetch", {})[0], 400)
        with Store(self.a.database) as store:
            self.assertEqual(store.events(None, 5)[0]["kind"], "import_fetch")
        with patch("serp_drift.cli.ahrefs_keywords", side_effect=fetch):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(main(["--dir", str(self.a.root), "import", "--source", "ahrefs", "--dry-run", "--exclude-brand", "--min-volume", "600"]), 0)
            printed = json.loads(out.getvalue())
            self.assertEqual([c["query"] for c in printed["candidates"]], ["keyword research"])
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--dir", str(self.a.root), "import", "--source", "ahrefs"]), 0)
            queries = [t["query"] for t in load_config(self.a.config)["targets"]]
            self.assertEqual(queries, ["topical authority", "keyword research", "publisher login"])
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--dir", str(self.a.root), "import", "--source", "ahrefs"]), 0)  # idempotent: everything skipped
            self.assertEqual(len(load_config(self.a.config)["targets"]), 3)

    def test_connect_agent_info_and_self_test(self):
        status, body = self.request("GET", "/api/p/alpha/mcp")
        self.assertEqual(status, 200, body)
        self.assertIn("mcp", body["args"])
        self.assertIn(str(self.a.root), body["shell"])
        self.assertEqual([c["id"] for c in body["clients"]], ["claude-code", "claude-desktop", "cursor", "codex", "vscode", "other"])
        for client in body["clients"]:
            self.assertIn(str(self.a.root), client["text"], client["id"])
        self.assertTrue(body["clients"][0]["text"].startswith("claude mcp add serp-drift"))
        self.assertTrue(body["clients"][3]["text"].startswith("[mcp_servers.serp-drift]"))
        self.assertEqual(json.loads(body["clients"][1]["text"])["mcpServers"]["serp-drift"]["args"][-1], "mcp")
        self.assertEqual(len(body["tools"]), 8)
        status, body = self.request("POST", "/api/p/alpha/mcp/check", {})
        self.assertEqual(status, 200, body)
        self.assertTrue(body["ok"], body)
        self.assertEqual(body["server"]["name"], "serp-drift")
        self.assertEqual(len(body["tools"]), 8)

    def test_import_parser_edge_cases(self):
        result = import_candidates("query\n\nhello world\nHello World\n", existing=set())
        self.assertEqual(result["total"], 1)
        with self.assertRaises(ValueError):
            import_candidates("   \n", existing=set())


AHREFS_PAYLOAD = {"keywords": [
    {"keyword": "keyword research", "volume": 12000, "best_position": 3, "best_position_url": "https://www.publisher.example/keyword-research", "best_position_kind": "organic", "is_informational": True, "is_commercial": False, "is_transactional": False, "is_navigational": False, "is_branded": False},
    {"keyword": "publisher  login", "volume": 500, "best_position": 1, "best_position_url": "https://www.publisher.example/login", "best_position_kind": "organic", "is_informational": False, "is_commercial": False, "is_transactional": False, "is_navigational": True, "is_branded": True},
    {"keyword": "Topical Authority", "volume": 900, "best_position": 8, "best_position_url": "https://www.publisher.example/guide", "best_position_kind": "snippet", "is_informational": True, "is_commercial": False, "is_transactional": False, "is_navigational": False, "is_branded": False},
    {"keyword": "", "volume": 1},
]}


class FakeAhrefs:
    """Stands in for urllib's opener: records the request, returns a canned body with unit headers, or raises."""

    def __init__(self, payload=None, error=None, units="1900"):
        self.payload, self.error, self.units, self.request = payload, error, units, None

    def open(self, request, timeout=None):
        self.request = request
        if self.error:
            raise self.error
        opener = self
        headers = http.client.HTTPMessage()
        headers["x-api-units-cost-total"] = opener.units
        headers["x-api-rows"] = str(len(opener.payload.get("keywords", [])))

        class Response:
            headers = None

            def __init__(self):
                self.headers = headers

            def read(self, size=-1):
                return json.dumps(opener.payload).encode()

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        return Response()


class AhrefsSourceTests(unittest.TestCase):
    def test_request_shape_rows_and_units(self):
        opener = FakeAhrefs(AHREFS_PAYLOAD)
        result = ahrefs_keywords("tok", "https://Publisher.example/", country="US", limit=100, opener=opener, date="2026-09-16")
        url = opener.request.full_url
        self.assertTrue(url.startswith("https://api.ahrefs.com/v3/site-explorer/organic-keywords?"))
        self.assertIn("target=publisher.example", url)
        self.assertIn("country=us", url)
        self.assertIn("order_by=volume%3Adesc", url)
        self.assertIn("select=keyword%2Cvolume%2Cbest_position", url)
        self.assertNotIn("tok", url)
        self.assertEqual(opener.request.get_header("Authorization"), "Bearer tok")
        self.assertEqual(len(result["rows"]), 3)  # the empty keyword is dropped
        self.assertEqual(result["rows"][1]["query"], "publisher login")  # whitespace collapsed
        self.assertEqual(result["rows"][1]["intent_hint"], "navigational")
        self.assertTrue(result["rows"][1]["branded"])
        self.assertEqual(result["rows"][2]["kind"], "snippet")
        self.assertEqual(result["source"]["units"], 1900)
        self.assertEqual(result["source"]["estimated_units"], ahrefs_units(3))
        self.assertEqual(ahrefs_units(500), 9500)
        self.assertEqual(ahrefs_units(500, traffic=True), 14500)
        self.assertEqual(ahrefs_units(1), 50)
        traffic = FakeAhrefs(AHREFS_PAYLOAD)
        ahrefs_keywords("tok", "publisher.example", country=None, limit=50, traffic=True, opener=traffic)
        self.assertIn("order_by=sum_traffic%3Adesc", traffic.request.full_url)
        self.assertNotIn("country=", traffic.request.full_url)

    def test_validation_and_provider_errors(self):
        with self.assertRaises(SourceError):
            ahrefs_keywords("", "publisher.example", country="us", opener=FakeAhrefs(AHREFS_PAYLOAD))
        with self.assertRaises(SourceError):
            ahrefs_keywords("tok", "publisher.example", country="usa", opener=FakeAhrefs(AHREFS_PAYLOAD))
        with self.assertRaises(SourceError):
            ahrefs_keywords("tok", "not a host", country="us", opener=FakeAhrefs(AHREFS_PAYLOAD))
        with self.assertRaises(SourceError):
            ahrefs_keywords("tok", "publisher.example", country="us", limit=5000, opener=FakeAhrefs(AHREFS_PAYLOAD))
        self.assertEqual(clean_target("https://www.example.com/blog/"), "www.example.com/blog")
        unauthorized = HTTPError("https://api.ahrefs.com/x", 401, "Unauthorized", http.client.HTTPMessage(), BytesIO(b'{"error":"token"}'))
        with self.assertRaises(SourceError) as caught:
            ahrefs_keywords("sekret-42", "publisher.example", country="us", opener=FakeAhrefs(error=unauthorized))
        self.assertIn("rejected the token", str(caught.exception))
        self.assertNotIn("sekret-42", str(caught.exception))
        bad = HTTPError("https://api.ahrefs.com/x", 400, "Bad Request", http.client.HTTPMessage(), BytesIO(b'{"error":"unknown field: foo"}'))
        with self.assertRaises(SourceError) as caught:
            ahrefs_keywords("tok", "publisher.example", country="us", opener=FakeAhrefs(error=bad))
        self.assertIn("unknown field", str(caught.exception))
        with self.assertRaises(SourceError) as caught:
            ahrefs_keywords("tok", "publisher.example", country="us", opener=FakeAhrefs(error=URLError("dns")))
        self.assertIn("Could not reach", str(caught.exception))
        with self.assertRaises(SourceError):
            ahrefs_keywords("tok", "publisher.example", country="us", opener=FakeAhrefs({"error": "nope"}))

    def test_candidates_from_rows_merges_sources(self):
        rows = [{"query": "seo audit", "volume": 800, "position": 12, "url": "https://x.example/a", "intent_hint": "commercial", "branded": False},
                {"query": "SEO audit", "volume": 700, "position": 4, "url": "https://x.example/b", "intent_hint": None, "branded": True},
                {"query": "seo audit checklist", "impressions": 40, "clicks": 2, "position": 9.5}]
        result = candidates_from_rows(rows, {"rows": 3, "columns": "test"}, existing={"seo audit checklist"})
        self.assertEqual(result["total"], 2)
        merged = result["candidates"][0]
        self.assertEqual((merged["query"], merged["volume"], merged["position"], merged["url"], merged["source_intent"], merged["branded"]), ("seo audit", 800, 4.0, "https://x.example/b", "commercial", True))
        self.assertTrue(result["candidates"][1]["existing"])
        self.assertIsNone(result["candidates"][1]["volume"])


class RepoHygieneTests(unittest.TestCase):
    def test_tracked_text_files_contain_no_local_paths(self):
        """Nothing that reveals a contributor's machine may be committed: home directories, private tool folders, example-workspace paths."""
        try:
            tracked = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
        except (OSError, subprocess.CalledProcessError):
            self.skipTest("not a git checkout")
        # Built from fragments so this file does not trip its own check.
        homes = "/Us" + "ers/(?!you/)|/ho" + "me/(?!you/)|C:" + r"\\\\Us" + r"ers\\\\"
        private = r"\." + "claude/|serp-drift-" + "examples"
        pattern = re.compile(f"{homes}|{private}")
        offenders = []
        for name in tracked:
            path = ROOT / name
            if not path.is_file() or path.suffix in {".png", ".jpg", ".ico", ".sqlite", ".zip"}:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if pattern.search(text):
                offenders.append(name)
        self.assertEqual(offenders, [])
