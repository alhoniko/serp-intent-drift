"""Blind human annotation exports and held-out evaluation. Never manufacture ground truth."""

from datetime import date
import hashlib
import json
from pathlib import Path
from statistics import mean

from .analysis import analyze
from .report import atomic_write
from .storage import parse_time

INTENTS = {'informational', 'commercial', 'transactional', 'navigational', 'unknown', 'mixed'}


def identifier(*parts) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()[:24]


def export_annotation(config: dict, store, directory: Path, holdout_after: str | None = None, *, sample_results: int | None = None,
                      latest_windows: bool = False) -> dict:
    """Split by query family and optionally reserve a later temporal holdout as well.

    `sample_results` keeps a deterministic, hash-ordered subset of result rows; `latest_windows` keeps one window per panel (its
    newest capture). Captures of another query are never annotation material: they are counted, not exported."""
    if holdout_after:
        date.fromisoformat(holdout_after)
    rows, predictions, labels = [], [], []
    skipped = 0
    families = sorted({identifier(t['query'].strip().casefold()) for t in config['targets']})
    test_families = set(families[:(len(families) + 4) // 5])
    for target in config['targets']:
        history = store.history(target)
        skipped += sum(1 for capture in history if capture.get('quality', {}).get('state') == 'query_mismatch')
        history = [capture for capture in history if capture.get('quality', {}).get('state') != 'query_mismatch']
        group = identifier(target['query'].strip().casefold())
        split = 'test' if group in test_families else 'calibration'
        for index, capture in enumerate(history):
            split_here = 'temporal_test' if holdout_after and capture['captured_at'][:10] > holdout_after and split == 'calibration' else split
            case_id = identifier(target['search'], capture['captured_at'])
            context = {'query': target['query'], 'search': target['search'], 'captured_at': capture['captured_at'], 'group': group,
                       'language': target['search']['hl'], 'split': split_here}
            def evidence(c):
                return {'captured_at': c['captured_at'], 'results': [{k: r.get(k) for k in ('position', 'url', 'title', 'snippet')} for r in c['results']],
                                  'features': c['features'], 'quality': c.get('quality', {})}
            if not latest_windows or index == len(history) - 1:
                report = analyze(target, history[:index + 1], config['settings'], now=parse_time(capture['captured_at']))
                rows.append({'id': case_id, 'kind': 'window', **context, 'baseline': [evidence(s) for s in report['baseline']],
                             'recent': [evidence(s) for s in history[max(0, index - config['settings']['confirmations']):index + 1]], 'settings': config['settings'],
                             'page': capture.get('page')})
                predictions.append({'id': case_id, 'kind': 'window', **context, 'intent_shift': report['confirmed_intent_shift'],
                                    'page_mismatch': report['confirmed_mismatch'], 'eligible': report['evidence']['support'] == 'available',
                                    'method': report['method'], 'classifier': capture.get('analysis_version')})
                labels.append({'id': case_id, 'kind': 'window', 'intent_shift': None, 'page_mismatch': None, 'reviewer': '', 'source': 'human', 'note': ''})
            for result in capture['results']:
                item_id = identifier(case_id, result['position'], result['url'])
                rows.append({'id': item_id, 'kind': 'result', **context, **{k: result[k] for k in ('position', 'url', 'title', 'snippet')}})
                predictions.append({'id': item_id, 'kind': 'result', **context, 'intent': result['intent'], 'format': result['type'], 'classifier': capture.get('analysis_version')})
                labels.append({'id': item_id, 'kind': 'result', 'intent': None, 'format': None, 'reviewer': '', 'source': 'human', 'note': ''})
    if sample_results is not None:
        # Hash order is a fixed pseudo-random order: the same export always selects the same results.
        keep = {row['id'] for row in sorted((row for row in rows if row['kind'] == 'result'), key=lambda row: row['id'])[:sample_results]}
        rows, predictions, labels = ([row for row in values if row['kind'] == 'window' or row['id'] in keep] for values in (rows, predictions, labels))
    for name in ('observations.jsonl', 'predictions.jsonl', 'labels.template.jsonl'):
        path = directory / name
        if path.exists():
            raise ValueError(f'Refusing to overwrite annotation work: {path}')
    for name, values in [('observations.jsonl', rows), ('predictions.jsonl', predictions), ('labels.template.jsonl', labels)]:
        atomic_write(directory / name, ''.join(json.dumps(v, ensure_ascii=False) + '\n' for v in values))
    return {'directory': str(directory), 'rows': len(rows), 'queries': len(config['targets']), 'ground_truth': 'pending human annotation',
            'windows': sum(row['kind'] == 'window' for row in rows), 'results': sum(row['kind'] == 'result' for row in rows),
            'skipped_query_mismatch_captures': skipped,
            'splits': {s: sum(r['split'] == s for r in rows) for s in ('calibration', 'test', 'temporal_test')}}


def read_jsonl(path: Path) -> list[dict]:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if any(not isinstance(row, dict) or not row.get('id') for row in rows) or len({r['id'] for r in rows}) != len(rows):
        raise ValueError('Every JSONL row must have a unique id.')
    return rows


def binary_metrics(rows: list[tuple[dict, dict]], field: str) -> dict:
    pairs = [(p, g) for p, g in rows if p['kind'] == 'window' and type(g.get(field)) is bool]
    tp = sum(p[field] and g[field] for p, g in pairs)
    fp = sum(p[field] and not g[field] for p, g in pairs)
    fn = sum(not p[field] and g[field] for p, g in pairs)
    tn = len(pairs) - tp - fp - fn
    precision, recall = (tp / (tp + fp) if tp + fp else None), (tp / (tp + fn) if tp + fn else None)
    # Capture-time delay for each annotated episode; gaps in gold labels are not bridged.
    delays, detected, episodes = [], 0, 0
    groups = {}
    for p, g in rows:
        if p['kind'] != 'window':
            continue
        groups.setdefault(identifier(p['search']), []).append((p, g))
    for group in groups.values():
        start = None
        found = False
        for p, g in sorted(group, key=lambda pair: pair[0]['captured_at']):
            if g.get(field) is not True:
                start, found = None, False
            elif start is None:
                start = parse_time(p['captured_at'])
                episodes += 1
            if g.get(field) is True and p[field] and not found:
                delays.append((parse_time(p['captured_at']) - start).total_seconds() / 3600)
                detected += 1
                found = True
    return {'labeled_windows': len(pairs), 'tp': tp, 'fp': fp, 'fn': fn, 'tn': tn, 'precision': precision, 'recall': recall,
            'episodes': episodes, 'detected_episodes': detected, 'mean_detection_delay_hours': mean(delays) if delays else None}


def metrics(rows: list[tuple[dict, dict]]) -> dict:
    classified = [(p, g) for p, g in rows if p['kind'] == 'result' and g.get('intent') in INTENTS]
    known = [(p, g) for p, g in classified if p['intent'] != 'unknown']
    return {'human_labeled_results': len(classified), 'coverage': len(known) / len(classified) if classified else None,
            'accuracy_all': sum(p['intent'] == g['intent'] for p, g in classified) / len(classified) if classified else None,
            'accuracy_classified': sum(p['intent'] == g['intent'] for p, g in known) / len(known) if known else None,
            'intent_shift': binary_metrics(rows, 'intent_shift'), 'page_mismatch': binary_metrics(rows, 'page_mismatch')}


def evaluate(predictions_path: Path, labels_path: Path) -> dict:
    predictions = {r['id']: r for r in read_jsonl(predictions_path)}
    labels = read_jsonl(labels_path)
    rows = []
    for gold in labels:
        if gold['id'] not in predictions:
            raise ValueError('Annotation id does not exist in these predictions.')
        filled = gold.get('intent') is not None or gold.get('intent_shift') is not None or gold.get('page_mismatch') is not None
        if not filled:
            continue
        if gold.get('source') != 'human' or not str(gold.get('reviewer', '')).strip():
            raise ValueError('Filled labels require a named human reviewer and source=human.')
        if gold.get('intent') is not None and gold['intent'] not in INTENTS:
            raise ValueError('Invalid human intent label.')
        if any(gold.get(k) is not None and type(gold[k]) is not bool for k in ('intent_shift', 'page_mismatch')):
            raise ValueError('Window labels must be true, false or null (uncertain).')
        rows.append((predictions[gold['id']], gold))
    return {'state': 'measured' if rows else 'awaiting_human_labels', 'human_labeled_rows': len(rows),
            'by_split': {s: metrics([(p, g) for p, g in rows if p['split'] == s]) for s in ('calibration', 'test', 'temporal_test')},
            'held_out_by_language': {lang: metrics([(p, g) for p, g in rows if p['language'] == lang and p['split'] != 'calibration']) for lang in sorted({p['language'] for p, _ in rows})},
            'limitation': 'No release verdict is inferred from small samples. Query families and later captures must stay out of tuning. Coverage is not accuracy.'}
