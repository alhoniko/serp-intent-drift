"""Provider provenance and conservative data-quality checks, independent of intent."""

import re
import unicodedata

CONTEXT_FIELDS = ('q', 'engine', 'gl', 'hl', 'device', 'location', 'page')


def folded(value: object) -> str:
    return ' '.join(unicodedata.normalize('NFKC', str(value)).casefold().split())


def provenance(payload: dict, search: dict) -> dict:
    """Retain only explicitly allowed metadata; never URLs, bearer tokens or arbitrary fields."""
    returned = payload.get('search_parameters')
    returned = returned if isinstance(returned, dict) else {}
    actual = {key: str(returned[key])[:500] for key in CONTEXT_FIELDS if isinstance(returned.get(key), (str, int))}
    metadata = payload.get('search_metadata')
    metadata = metadata if isinstance(metadata, dict) else {}
    info = payload.get('search_information')
    info = info if isinstance(info, dict) else {}
    mismatches = [key for key in CONTEXT_FIELDS if key in actual and key in search and folded(actual[key]) != folded(search[key])]
    corrections = {key: str(info[key])[:500] for key in ('query_displayed', 'query_detected', 'showing_results_for', 'spelling_fix') if isinstance(info.get(key), str)}
    corrected = any(folded(value) != folded(search.get('q', '')) for value in corrections.values())
    return {'requested': {key: search[key] for key in CONTEXT_FIELDS if key in search}, 'returned': actual,
            'request_id': str(metadata.get('id', ''))[:160], 'created_at': str(metadata.get('created_at', ''))[:80],
            'corrections': corrections, 'mismatches': mismatches, 'corrected_query': corrected,
            'verified_fields': sorted(key for key in actual.keys() & search.keys() if key not in mismatches)}


def assess(payload: dict, search: dict, results: list[dict], minimum: int) -> dict:
    trace = provenance(payload, search)
    reasons = []
    if trace['mismatches']:
        reasons.append('Returned search context differs: ' + ', '.join(trace['mismatches']) + '.')
    if trace['corrected_query']:
        reasons.append('The provider reports a corrected or substituted query. Check it before comparing.')
    if len(results) < minimum:
        reasons.append(f'Only {len(results)} usable results; {minimum} required.')
    blocked = bool(reasons)
    return {'state': ('quarantined' if trace['mismatches'] or trace['corrected_query'] else 'insufficient') if blocked else 'accepted', 'eligible': not blocked,
            'provenance': 'verified' if 'q' in trace['verified_fields'] else 'unverified',
            'reasons': reasons, 'trace': trace}


def topic_terms(snapshot: dict) -> set[str]:
    """A lexical inspection aid, never an automatic rejection or a semantic diagnosis."""
    stop = {'the', 'and', 'for', 'with', 'from', 'this', 'that', 'what', 'how', 'your', 'you', 'are', 'can', 'our', 'into', 'ja', 'tai', 'on'}
    text = ' '.join(row.get('title', '') for row in snapshot.get('results', []))
    return {term for term in re.findall(r'[^\W\d_]{3,}', text.casefold()) if term not in stop}


def topic_check(left: list[dict], latest: dict) -> dict:
    before = set().union(*(topic_terms(s) for s in left))
    after = topic_terms(latest)
    overlap = len(before & after) / max(1, len(before | after))
    unusual = [s['captured_at'] for s in left if len(topic_terms(s)) >= 5 and after and len(topic_terms(s) & after) / max(1, len(topic_terms(s) | after)) < .08]
    return {'lexical_overlap': round(overlap, 3), 'inspection_suggested': bool(before and after and (overlap < .08 or unusual)), 'unusual_baseline_captures': unusual,
            'before_terms': sorted(before - after)[:20], 'after_terms': sorted(after - before)[:20],
            'caveat': 'Title vocabulary only. A topic change can be real; this check does not reject observations.'}
