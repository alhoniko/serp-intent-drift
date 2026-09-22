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
