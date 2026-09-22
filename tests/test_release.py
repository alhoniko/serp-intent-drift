"""Release-risk coverage for annotation, backup, delayed recovery and notification delivery."""

from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
import tempfile
import unittest

import test_evidence as evidence_fixtures
from test_monitor import SEARCH, TARGET, response, snapshot

from serp_drift import evaluation, labeling, notify
from serp_drift.analysis import analyze
from serp_drift.config import DEFAULTS
from serp_drift.maintenance import backup
from serp_drift.storage import Store
from serp_drift.workspace import Workspace


class ReleaseTests(unittest.TestCase):
    def report(self):
        return analyze(TARGET, [snapshot(i) for i in range(3)] + [snapshot(i, 'commercial') for i in (3, 4)], DEFAULTS)

    def test_recovery_requires_repeated_spaced_observations(self):
        data = [snapshot(i) for i in range(3)] + [snapshot(i, 'commercial') for i in (3, 4)]
        data.append(snapshot(5))
        self.assertFalse(analyze(TARGET, data, DEFAULTS)['confirmed_recovery'])
        data.append(snapshot(6))
        self.assertTrue(analyze(TARGET, data, DEFAULTS)['confirmed_recovery'])

    def test_model_failures_cannot_confirm_even_if_rules_are_confident(self):
        data = [snapshot(i) for i in range(3)] + [snapshot(i, 'commercial') for i in (3, 4)]
        data[-1]['labeling'] = {'errors': ['http_500']}
        self.assertFalse(analyze(TARGET, data, DEFAULTS)['confirmed_intent_shift'])

    def test_full_semantic_mode_does_not_hide_model_abstention(self):
        data = snapshot()
        section = labeling.validate({'provider': 'openai', 'mode': 'all', 'model': 'test'})
        class Abstain:
            section = None
            errors = []
            def label(self, items, store):
                return {i['key']: '{"intent":"unknown","format":"unknown","task":"","evidence":""}' for i in items}
        model = Abstain(); model.section = section
        with tempfile.TemporaryDirectory() as tmp, Store(Path(tmp) / 'db') as store:
            labeling.apply(data, model, store)
        self.assertEqual(data['dominant_intent'], 'unknown')
        self.assertEqual(data['results'][0]['rule_label']['intent'], 'informational')

    def test_unstructured_labels_are_rejected(self):
        model = labeling.Labeler(labeling.validate({'provider':'openai','model':'test'}), 'key', opener=evidence_fixtures.LabelSafetyTests.Opener('{"a":"commercial"}'))
        self.assertEqual(model.complete([{'id':'a','title':'x','snippet':'','url':''}]), {})

    def test_same_review_episode_notifies_once_and_retries_failed_delivery(self):
        config = {'notify': {'webhook_url': 'https://example.com/hooks', 'format': 'json', 'on': ['review']}}
        q = self.report()
        attempts = []
        def sender(*args):
            attempts.append(args)
            return {'ok': len(attempts) > 1, 'status': 500 if len(attempts) == 1 else 200}
        with tempfile.TemporaryDirectory() as tmp, Store(Path(tmp) / 'db') as store:
            store.sync_case(q)
            q['reviews'] = store.cases(TARGET)
            report = {'queries': [q]}
            notify.after_run(config, store, report, sender=sender)
            notify.after_run(config, store, report, sender=sender)
            self.assertEqual(len(attempts), 2)
            notify.after_run(config, store, {'queries': [q | {'status':'collection_error'}]}, sender=sender)
            notify.after_run(config, store, report, sender=sender)
            self.assertEqual(len(attempts), 2)
            self.assertIsNone(store.get_meta('pending_notifications'))

    def test_backup_is_consistent_and_excludes_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Workspace(Path(tmp) / 'study'); workspace.root.mkdir()
            workspace.config.write_text('version=1\n')
            workspace.save_key('secret')
            with Store(workspace.database) as store:
                store.add(TARGET, snapshot(), response())
            out = Path(tmp) / 'backup'
            result = backup(workspace, out)
            self.assertEqual(result['snapshots'], 1)
            self.assertFalse((out / 'searchapi.key').exists())
            with Store(out / 'monitor.sqlite') as store:
                self.assertEqual(store.snapshot_count('synthetic'), 1)
            with self.assertRaises(ValueError):
                backup(workspace, out)

    def test_annotation_export_is_blind_and_empty_labels_never_claim_accuracy(self):
        with tempfile.TemporaryDirectory() as tmp, Store(Path(tmp) / 'db') as store:
            for i in range(5):
                store.add(TARGET, snapshot(i, source='searchapi'), response())
            directory = Path(tmp) / 'annotation'
            config = {'targets':[TARGET], 'settings':DEFAULTS}
            evaluation.export_annotation(config, store, directory)
            observations = evaluation.read_jsonl(directory / 'observations.jsonl')
            self.assertNotIn('predicted_intent', json.dumps(observations))
            self.assertNotIn('dominant_intent', json.dumps(observations))
            scored = evaluation.evaluate(directory / 'predictions.jsonl', directory / 'labels.template.jsonl')
            self.assertEqual(scored['state'], 'awaiting_human_labels')
            self.assertIsNone(scored['by_split']['test']['intent_shift']['precision'])
            with self.assertRaises(ValueError):
                evaluation.export_annotation(config, store, directory)

    def test_metrics_count_false_negatives_and_detection_delay(self):
        pairs = []
        from test_monitor import START
        for i, (predicted, gold) in enumerate([(False, False), (False, True), (True, True), (True, False)]):
            p = {'kind':'window', 'search':SEARCH, 'captured_at':(START + timedelta(days=i)).isoformat(), 'intent_shift':predicted}
            pairs.append((p, {'intent_shift':gold}))
        metrics = evaluation.binary_metrics(pairs, 'intent_shift')
        self.assertEqual((metrics['tp'], metrics['fp'], metrics['fn'], metrics['tn']), (1, 1, 1, 1))
        self.assertEqual(metrics['precision'], .5)
        self.assertEqual(metrics['recall'], .5)
        self.assertEqual(metrics['mean_detection_delay_hours'], 24)

    def test_unknown_human_labels_break_detection_episodes(self):
        pairs = []
        from test_monitor import START
        for i, gold in enumerate([True, None, True]):
            p = {'kind':'window', 'search':SEARCH, 'captured_at':(START + timedelta(days=i)).isoformat(), 'intent_shift':i == 2}
            pairs.append((p, {'intent_shift':gold}))
        metrics = evaluation.binary_metrics(pairs, 'intent_shift')
        self.assertEqual(metrics['episodes'], 2)
        self.assertEqual(metrics['mean_detection_delay_hours'], 0)

    def test_original_observation_is_stored_once_separately_from_semantic_labels(self):
        data = snapshot()
        data['observation'] = deepcopy(data)
        data['results'][0]['intent'] = 'commercial'
        with tempfile.TemporaryDirectory() as tmp, Store(Path(tmp) / 'db') as store:
            store.add(TARGET, data, response())
            raw = store.connection.execute('SELECT document FROM observations').fetchone()[0]
            normalized = store.connection.execute('SELECT normalized FROM snapshots').fetchone()[0]
            self.assertEqual(json.loads(raw)['results'][0]['intent'], 'informational')
            self.assertNotIn('observation', json.loads(normalized))

    def test_annotation_split_keeps_query_variants_together_and_has_holdout(self):
        targets = [TARGET | {'id': str(i), 'query': q, 'search': SEARCH | {'q':q, 'hl':hl}, 'identity':str(i)}
                   for i, (q, hl) in enumerate([('Example Query','en'), ('example query','fi'), ('Other Topic','en')])]
        with tempfile.TemporaryDirectory() as tmp, Store(Path(tmp) / 'db') as store:
            for t in targets:
                store.add(t, snapshot(source='searchapi'), response())
            evaluation.export_annotation({'targets':targets,'settings':DEFAULTS}, store, Path(tmp) / 'benchmark')
            rows = evaluation.read_jsonl(Path(tmp) / 'benchmark/predictions.jsonl')
            self.assertIn('test', {r['split'] for r in rows})
            same = [r['split'] for r in rows if r['query'].lower() == 'example query']
            self.assertEqual(len(set(same)), 1)

    def test_followup_date_survives_signal_recovery(self):
        from serp_drift.server import ProjectState
        q = self.report() | {'status':'stable', 'signal_key':None,
                             'reviews':[{'id':1,'active':0,'status':'monitoring','review_on':'2020-01-01','signal_key':'past'}]}
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Workspace(Path(tmp)); workspace.config.write_text('version=1\n')
            project = ProjectState(workspace)
            items = project.attention({'queries':[q]})
            self.assertTrue(any(item['panel'] == TARGET['id'] and 'Review date' in item['why'] for item in items))
