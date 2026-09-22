"""Regression tests for false alerts, isolation, reversible decisions and provider failures."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import timedelta
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from test_monitor import SEARCH, START, TARGET, response, snapshot

from serp_drift import labeling, packs
from serp_drift.analysis import analyze, compare_sets
from serp_drift.config import DEFAULTS, load_config, update_project
from serp_drift.normalize import normalize
from serp_drift.server import ProjectState
from serp_drift.storage import Store
from serp_drift.workspace import Workspace


class EvidenceTests(unittest.TestCase):
    def tearDown(self):
        packs.reset()

    def test_wrong_query_is_retained_but_never_confirms(self):
        payload = response('commercial') | {'search_parameters': SEARCH | {'q': 'different query', 'api_key': 'never-store'}}
        bad = normalize(payload, SEARCH, (START + timedelta(days=4)).isoformat(), None)
        self.assertFalse(bad['quality_ok'])
        self.assertNotIn('never-store', json.dumps(bad))
        report = analyze(TARGET, [snapshot(i) for i in range(3)] + [snapshot(3, 'commercial'), bad], DEFAULTS, now=START + timedelta(days=4))
        self.assertEqual(report['status'], 'data_quality')
        self.assertFalse(report['confirmed_intent_shift'])
        self.assertEqual(report['dimensions']['data'], 'quarantined')

    def test_missing_provenance_is_disclosed_not_fabricated(self):
        row = snapshot()
        self.assertEqual(row['quality']['provenance'], 'unverified')
        verified = normalize(response() | {'search_parameters': SEARCH}, SEARCH, START.isoformat(), None)
        self.assertEqual(verified['quality']['provenance'], 'verified')

    def test_query_rewrite_requires_review(self):
        row = normalize(response() | {'search_information': {'showing_results_for': 'other query'}}, SEARCH, START.isoformat(), None)
        self.assertFalse(row['quality_ok'])

    def test_baseline_uses_all_memberships_and_is_order_invariant(self):
        original = snapshot()
        outlier = snapshot(1, 'commercial')
        a = compare_sets([original, original, outlier], [original])
        b = compare_sets([outlier, original, original], [original])
        self.assertEqual(a['score'], b['score'])
        self.assertGreater(a['components']['url_turnover'], 0)
        self.assertLess(a['components']['url_turnover'], 1)

    def test_high_turnover_does_not_promise_intent_confirmation(self):
        history = [snapshot(i) for i in range(5)]
        for row in history[3:]:
            for result in row['results']:
                result['url'] += '/new'
            row['features'] = ['ads', 'ai_overview']
        report = analyze(TARGET, history, DEFAULTS)
        self.assertNotEqual(report['status'], 'review')
        self.assertIn('high change score alone', report['decision']['next_action'])

    def test_different_analysis_versions_do_not_confirm(self):
        history = [snapshot(i) for i in range(3)] + [snapshot(i, 'commercial') for i in (3, 4)]
        history[-1]['analysis_version'] = 'other-model'
        self.assertFalse(analyze(TARGET, history, DEFAULTS)['confirmed_intent_shift'])

    def test_exclusion_preserves_original_and_restore_is_reversible(self):
        with tempfile.TemporaryDirectory() as tmp, Store(Path(tmp) / 'db') as store:
            store.add(TARGET, snapshot(source='searchapi'), response())
            original = store.connection.execute('SELECT normalized FROM snapshots').fetchone()[0]
            date = store.history(TARGET)[0]['captured_at']
            store.review_observation(TARGET, date, True, 'Wrong topic; retained for inspection')
            self.assertFalse(store.history(TARGET)[0]['quality_ok'])
            self.assertEqual(store.connection.execute('SELECT normalized FROM snapshots').fetchone()[0], original)
            store.review_observation(TARGET, date, False, 'Verified query context')
            self.assertTrue(store.history(TARGET)[0]['quality_ok'])
            self.assertEqual(len(store.events(TARGET)), 2)

    def test_review_episode_survives_acknowledgement_and_recurs_after_recovery(self):
        report = analyze(TARGET, [snapshot(i) for i in range(3)] + [snapshot(i, 'commercial') for i in (3, 4)], DEFAULTS)
        with tempfile.TemporaryDirectory() as tmp, Store(Path(tmp) / 'db') as store:
            first = store.sync_case(report)
            self.assertIsNotNone(first)
            store.decide(TARGET, first['id'], 'closed', 'no_action', 'An existing comparison page already serves this intent')
            store.sync_case(report)
            self.assertEqual(len(store.cases(TARGET)), 1)
            stable = analyze(TARGET, [snapshot(i) for i in range(5)], DEFAULTS)
            store.sync_case(stable)
            store.sync_case(report)
            self.assertEqual(len(store.cases(TARGET)), 2)
            self.assertTrue(store.cases(TARGET)[0]['active'])

    def test_failed_collection_does_not_resolve_an_active_review(self):
        report = analyze(TARGET, [snapshot(i) for i in range(3)] + [snapshot(i, 'commercial') for i in (3, 4)], DEFAULTS)
        with tempfile.TemporaryDirectory() as tmp, Store(Path(tmp) / 'db') as store:
            store.sync_case(report)
            store.sync_case(report | {'status': 'collection_error', 'signal_key': None})
            self.assertTrue(store.cases(TARGET)[0]['active'])

    def test_migration_preserves_normalized_documents_and_keeps_analysis_separate(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'db'
            with Store(path) as store:
                store.add(TARGET, snapshot(), response())
                original = store.connection.execute('SELECT normalized FROM snapshots').fetchone()[0]
            with closing(sqlite3.connect(path)) as connection:
                connection.execute('PRAGMA user_version=5')
            with Store(path) as store:
                report = analyze(TARGET, [snapshot()], DEFAULTS)
                store.record_analysis(report)
                store.record_analysis(report)
                self.assertEqual(store.connection.execute('SELECT COUNT(*) FROM analysis_runs').fetchone()[0], 1)
                self.assertEqual(store.connection.execute('SELECT normalized FROM snapshots').fetchone()[0], original)

    def test_concurrent_configuration_edits_do_not_lose_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'monitor.toml'
            path.write_text('version = 1\n')
            with ThreadPoolExecutor(2) as pool:
                jobs = [pool.submit(update_project, path, {'name': 'Project'}), pool.submit(update_project, path, {'site': 'example.com'})]
                for job in jobs:
                    job.result()
            self.assertEqual(load_config(path)['project'], {'name': 'Project', 'site': 'example.com'})

    def test_invalid_external_config_disables_cached_configuration(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Workspace(Path(tmp)); workspace.config.write_text('version = 1\n')
            project = ProjectState(workspace)
            workspace.config.write_text('version = 8\n')
            project.config_mtime = None
            self.assertIsNone(project.current_config())

    def test_each_workspace_has_isolated_rule_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ('a', 'b'):
                (root / name).mkdir()
                (root / name / 'monitor.toml').write_text('version = 1\n[[targets]]\nid = "a"\nquery = "same"\n')
            (root / 'a/rules').mkdir()
            (root / 'a/rules/en.toml').write_text('language = "en"\n[rules]\ninformational = ["zebra"]\n')
            a = load_config(root / 'a/monitor.toml')['analysis_version']
            b = load_config(root / 'b/monitor.toml')['analysis_version']
            self.assertNotEqual(a, b)
            self.assertEqual(load_config(root / 'a/monitor.toml')['analysis_version'], a)


class LabelSafetyTests(unittest.TestCase):
    class Opener:
        def __init__(self, content):
            self.content = content
        def open(self, *args, **kwargs):
            import io
            return io.BytesIO(json.dumps({'choices': [{'message': {'content': self.content}}]}).encode())

    def test_null_and_invalid_contents_are_nonfatal(self):
        for content in (None, [], {}, 'not json'):
            client = labeling.Labeler(labeling.validate({'provider': 'openai', 'model': 'x'}), 'test', opener=self.Opener(content))
            self.assertEqual(client.complete([]), {})

    def test_endpoint_prompt_and_query_participate_in_identity(self):
        a = labeling.validate({'provider': 'openai', 'model': 'same', 'base_url': 'https://a.example/v1'})
        b = a | {'base_url': 'https://b.example/v1'}
        self.assertNotEqual(labeling.identity_tag(a), labeling.identity_tag(b))
        self.assertNotEqual(labeling.item_key('a', 'b', 'c', 'm', 'q1'), labeling.item_key('a', 'b', 'c', 'm', 'q2'))

    def test_transient_failures_do_not_poison_cache(self):
        section = labeling.validate({'provider': 'openai', 'model': 'x'})
        client = labeling.Labeler(section, 'test', opener=self.Opener(None))
        items = [{'key': 'a', 'title': 'title', 'snippet': '', 'url': '', 'query': 'query'}]
        with tempfile.TemporaryDirectory() as tmp, Store(Path(tmp) / 'db') as store:
            self.assertEqual(client.label(items, store), {})
            self.assertEqual(store.cached_labels(['a']), {})
            answer = json.dumps({"intent": "informational", "format": "guide", "task": "read", "evidence": "title"})
            client.opener = self.Opener('{"a":' + answer + '}')
            self.assertEqual(json.loads(client.label(items, store)['a'])['intent'], 'informational')

    def test_semantic_labels_require_evidence_from_input(self):
        section = labeling.validate({'provider': 'openai', 'model': 'x'})
        content = json.dumps({'a': {'intent': 'commercial', 'format': 'comparison', 'task': 'choose software', 'evidence': 'invented'}})
        client = labeling.Labeler(section, 'test', opener=self.Opener(content))
        self.assertEqual(client.complete([{'id': 'a', 'title': 'Real title', 'snippet': '', 'url': ''}]), {})
        self.assertIn('unsupported_evidence', client.errors)

    def test_strong_rules_can_be_reviewed_by_full_semantic_mode(self):
        row = snapshot()
        section = labeling.validate({'provider': 'openai', 'model': 'x', 'mode': 'all'})
        class Model:
            section = None
            errors = []
            def label(self, items, store):
                return {i['key']: json.dumps({'intent': 'commercial', 'format': 'comparison', 'task': 'choose', 'evidence': 'guide'}) for i in items}
        model = Model(); model.section = section
        with tempfile.TemporaryDirectory() as tmp, Store(Path(tmp) / 'db') as store:
            labeling.apply(row, model, store)
        self.assertTrue(row['results'][0]['label_disagreement'])
        self.assertEqual(row['results'][0]['rule_label']['intent'], 'informational')
        self.assertEqual(row['dominant_intent'], 'commercial')


DECAY = SEARCH | {'q': 'content decay'}
DECAY_TARGET = {'id': 'content-decay', 'query': 'content decay', 'search': DECAY, 'identity': 'decay-panel'}


def decay_payload(degraded=False):
    """Observed September 2026 pattern: some captures return results for one query word only."""
    rows = [{'position': i, 'link': f'https://site-{i}.example/{"content-hub" if degraded else "content-decay"}',
             'title': 'Content organization and creators' if degraded else 'What is content decay? How to fix it',
             'snippet': 'Build a content business.' if degraded else 'Content decay is a slow decline in traffic.'} for i in range(1, 10)]
    return {'search_metadata': {'status': 'Success'}, 'search_parameters': DECAY, 'organic_results': rows}


def decay_snapshot(hours, degraded=False):
    return normalize(decay_payload(degraded), DECAY, (START + timedelta(hours=hours)).isoformat(), None)


class QueryCheckTests(unittest.TestCase):
    def test_single_word_results_are_flagged_against_the_panels_own_reference(self):
        from serp_drift.quality import query_check, query_match
        good, bad = decay_snapshot(0), decay_snapshot(24, degraded=True)
        self.assertEqual(query_match(good), 1.0)
        self.assertEqual(query_match(bad), 0.0)
        checks = query_check([good, bad])
        self.assertTrue(checks[bad['captured_at']]['flagged'])
        self.assertFalse(checks[good['captured_at']]['flagged'])

    def test_check_abstains_without_a_reference_or_for_single_terms(self):
        from serp_drift.quality import query_check, query_match
        bad = decay_snapshot(0, degraded=True)
        self.assertFalse(query_check([bad])[bad['captured_at']]['flagged'])
        single = normalize(response(), SEARCH | {'q': 'eeat'}, START.isoformat(), None)
        self.assertIsNone(query_match(single))

    def test_history_overlay_keeps_the_observation_and_a_human_can_keep_it(self):
        with tempfile.TemporaryDirectory() as temporary, Store(Path(temporary) / 'm.sqlite') as store:
            good, bad = decay_snapshot(0), decay_snapshot(24, degraded=True)
            store.add(DECAY_TARGET, good, decay_payload())
            store.add(DECAY_TARGET, bad, decay_payload(True))
            rows = store.history(DECAY_TARGET)
            self.assertEqual(rows[1]['quality']['state'], 'query_mismatch')
            self.assertFalse(rows[1]['quality_ok'])
            self.assertEqual(json.loads(store.connection.execute('SELECT document FROM observations ORDER BY snapshot_id DESC').fetchone()[0])['quality']['state'], 'accepted')
            self.assertEqual(len(store.history(DECAY_TARGET, since=rows[1]['captured_at'])), 1)
            store.review_observation(DECAY_TARGET, bad['captured_at'], False, 'Checked the live SERP: results are correct.')
            self.assertTrue(store.history(DECAY_TARGET)[1]['quality_ok'])

    def test_mismatched_captures_do_not_occupy_samples_or_confirm(self):
        rows = [decay_snapshot(0), decay_snapshot(24), decay_snapshot(48)]
        bad = decay_snapshot(72, degraded=True)
        retry = decay_snapshot(72.05)
        from serp_drift.quality import apply_query_check
        report = analyze(DECAY_TARGET, apply_query_check([*rows, bad, retry]), DEFAULTS, now=START + timedelta(hours=73))
        self.assertEqual(report['status'], 'stable')
        self.assertEqual(report['latest']['captured_at'], retry['captured_at'])
        self.assertIn('query_mismatch', [point.get('quality_state') for point in report['timeline']])
        # A rejected newest capture is a failed collection: status comes from the newest valid capture, with the rejection disclosed.
        latest_bad = analyze(DECAY_TARGET, apply_query_check([*rows, bad]), DEFAULTS, now=START + timedelta(hours=73))
        self.assertEqual(latest_bad['status'], 'baseline_ready')
        self.assertEqual(latest_bad['latest']['captured_at'], rows[-1]['captured_at'])
        self.assertEqual(latest_bad['rejected_after_latest'], [bad['captured_at']])
        self.assertTrue(any('different query' in reason for reason in latest_bad['reasons']))
        overdue = analyze(DECAY_TARGET, apply_query_check([*rows, bad]), DEFAULTS, now=START + timedelta(hours=100))
        self.assertEqual(overdue['status'], 'stale')
        only_bad = analyze(DECAY_TARGET, apply_query_check([rows[0], bad])[1:], DEFAULTS, now=START + timedelta(hours=73))
        self.assertEqual(only_bad['status'], 'data_quality')
        self.assertEqual(only_bad['decision']['title'], 'Latest capture did not match the query')

    def test_collector_retries_a_mismatched_capture_once_and_records_both(self):
        from serp_drift.cli import collect

        class Fake:
            requests = 0
            def __init__(self, payloads): self.payloads, self.pauses = payloads, []
            def sleep(self, seconds): self.pauses.append(seconds)
            expansions = 0
            def ai_overview(self, token, resolve_links=True):
                self.requests += 1; self.expansions += 1
                return {'text_blocks': [{'type': 'paragraph', 'answer': 'Content decay is a decline.'}], 'reference_links': []}
            def search(self, params):
                self.requests += 1
                return self.payloads.pop(0)
        with tempfile.TemporaryDirectory() as temporary:
            db = Path(temporary) / 'm.sqlite'
            with Store(db) as store:
                store.add(DECAY_TARGET, decay_snapshot(-24), decay_payload())
            settings = DEFAULTS | {'retry_query_mismatch': 1}
            token = {'ai_overview': {'page_token': 'deferred'}}
            fake = Fake([decay_payload(True) | token, decay_payload() | token])
            summary = collect({'settings': settings, 'targets': [DECAY_TARGET]}, db, client=fake)
            # The rejected response spends no Overview expansion; the capture of record does.
            self.assertEqual((summary['collected'], fake.requests, fake.expansions, fake.pauses), (1, 3, 1, [30]))
            with Store(db) as store:
                codes = [row['code'] for row in store.attempts(DECAY_TARGET)]
                self.assertEqual(store.total_requests(), 3)
                states = [row['quality']['state'] for row in store.history(DECAY_TARGET)]
            self.assertEqual(codes, ['ok', 'query_check_retry'])
            self.assertEqual(states, ['accepted', 'query_mismatch', 'accepted'])
            fake = Fake([decay_payload(True)])
            collect({'settings': DEFAULTS, 'targets': [DECAY_TARGET]}, db, client=fake, force=True)
            self.assertEqual(fake.requests, 1)
        with tempfile.TemporaryDirectory() as temporary:
            # A new panel has no reference yet; an almost total miss still earns the single retry.
            db = Path(temporary) / 'm.sqlite'
            fake = Fake([decay_payload(True), decay_payload()])
            collect({'settings': settings, 'targets': [DECAY_TARGET]}, db, client=fake)
            self.assertEqual(fake.requests, 2)
            with Store(db) as store:
                self.assertEqual([row['quality']['state'] for row in store.history(DECAY_TARGET)], ['query_mismatch', 'accepted'])

    def test_total_request_cap_stops_collection_and_scheduling(self):
        from serp_drift.cli import collect
        from serp_drift.client import SearchApi
        from serp_drift.scheduler import due_panels, next_due_at

        class Opener:
            calls = 0
            def open(self, request, timeout):
                Opener.calls += 1
                body = json.dumps(decay_payload()).encode()
                return type('R', (), {'read': lambda self, n: body, '__enter__': lambda self: self, '__exit__': lambda self, *a: None})()
        other = DECAY_TARGET | {'id': 'other', 'identity': 'other-panel'}
        settings = DEFAULTS | {'max_total_requests': 1, 'request_delay_seconds': 0, 'ai_overview': 'skip'}
        config = {'settings': settings, 'targets': [DECAY_TARGET, other]}
        with tempfile.TemporaryDirectory() as temporary:
            db = Path(temporary) / 'm.sqlite'
            summary = collect(config, db, client=SearchApi('k', settings, opener=Opener(), sleep=lambda s: None))
            self.assertEqual((summary['collected'], Opener.calls), (1, 1))
            self.assertEqual(summary['budget'], {'cap': 1, 'used': 1, 'exhausted': True})
            summary = collect(config, db, client=SearchApi('k', settings, opener=Opener(), sleep=lambda s: None), force=True)
            self.assertEqual((summary['collected'], Opener.calls), (0, 1))
            self.assertEqual(due_panels(config, db), [])
            self.assertIsNone(next_due_at(config, db))

    def test_collection_window_end_stops_collection_and_scheduling(self):
        from serp_drift.cli import collect
        from serp_drift.config import load_config
        from serp_drift.scheduler import due_panels

        class Fake:
            requests = 0
            def search(self, params):
                self.requests += 1
                return decay_payload()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'monitor.toml'
            path.write_text('version = 1\n[settings]\ncollect_until = "2026-08-01"\n', encoding='utf-8')
            with self.assertRaises(ValueError):
                load_config(path)
            config = {'settings': DEFAULTS | {'collect_until': '2026-08-01T00:00:00Z'}, 'targets': [DECAY_TARGET]}
            db = Path(temporary) / 'm.sqlite'
            fake = Fake()
            self.assertEqual(collect(config, db, client=fake, force=True)['skipped'], 1)
            self.assertEqual(fake.requests, 0)
            Store(db).connection.close()
            self.assertEqual(due_panels(config, db), [])
            self.assertEqual(len(due_panels(config | {'settings': DEFAULTS}, db)), 1)

    def test_ended_collection_is_one_notice_not_overdue_panels(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'monitor.toml').write_text('version = 1\n[settings]\ncollect_until = "2026-08-02T00:00:00Z"\n[[targets]]\nid = "content-decay"\nquery = "content decay"\n', encoding='utf-8')
            project = ProjectState(Workspace(root))
            target = project.target('content-decay')
            with Store(root / 'data' / 'monitor.sqlite') as store:
                for hours in (0, 24, 48, 72):
                    store.add(target, decay_snapshot(hours), decay_payload())
            query = project.report()['queries'][0]
            self.assertEqual(query['status'], 'stale')
            self.assertEqual(query['decision']['title'], 'Collection ended')
            attention = project.attention()
            self.assertEqual([item['title'] for item in attention if item['kind'] != 'config' or item['title'] == 'Collection ended'], ['Collection ended'])
            self.assertTrue(project.budget()['stopped'])

    def test_annotation_sample_is_fixed_and_skips_mismatched_captures(self):
        from serp_drift import evaluation
        with tempfile.TemporaryDirectory() as temporary, Store(Path(temporary) / 'm.sqlite') as store:
            for hours, bad in ((0, False), (24, True), (48, False), (72, False)):
                store.add(DECAY_TARGET, decay_snapshot(hours, degraded=bad), decay_payload(bad))
            config = {'settings': DEFAULTS, 'targets': [DECAY_TARGET]}
            first = evaluation.export_annotation(config, store, Path(temporary) / 'a', sample_results=5, latest_windows=True)
            evaluation.export_annotation(config, store, Path(temporary) / 'b', sample_results=5, latest_windows=True)
            self.assertEqual((first['windows'], first['results'], first['skipped_query_mismatch_captures']), (1, 5, 1))
            self.assertEqual((Path(temporary) / 'a/predictions.jsonl').read_text(), (Path(temporary) / 'b/predictions.jsonl').read_text())
            observed = evaluation.read_jsonl(Path(temporary) / 'a/observations.jsonl')
            self.assertNotIn('content-hub', json.dumps(observed))
