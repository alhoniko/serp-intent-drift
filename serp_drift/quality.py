"""Provider provenance and conservative data-quality checks, independent of intent."""

import math
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


QUERY_STOP = {'a', 'an', 'the', 'and', 'or', 'for', 'with', 'from', 'what', 'how', 'why', 'are', 'is', 'to', 'of', 'in', 'on', 'at', 'by',
              'vs', 'versus', 'do', 'does', 'ja', 'tai', 'vai', 'mikä', 'miten', 'kuinka'}
# A capture is treated as a failed collection only when its organic results miss the query terms far more than this panel's own
# captures usually do. Thresholds are engineering choices from the September 2026 live data, not a validated classifier.
QUERY_MATCH_FLOOR = 0.2
QUERY_MATCH_REFERENCE = 0.35
QUERY_MATCH_RATIO = 0.4
QUERY_MATCH_UNREFERENCED = 0.1


def query_terms(query: str) -> list[str]:
    words = re.findall(r'[^\W_]+', unicodedata.normalize('NFKC', query).casefold())
    return list(dict.fromkeys(word for word in words if word not in QUERY_STOP and len(word) >= 2))


def _term_present(term: str, words: set[str]) -> bool:
    if len(term) <= 4:
        return term in words or f'{term}s' in words
    stem = term[:max(4, len(term) - 2)]
    return any(word.startswith(stem) for word in words)


def query_match(snapshot: dict) -> float | None:
    """Rank-weighted share of organic results whose title, snippet or URL contain every query term. None when not applicable.

    Single-term queries and empty captures abstain: a result set for a different single term cannot be told apart lexically."""
    terms = query_terms(str((snapshot.get('search') or {}).get('q', '')))
    results = snapshot.get('results') or []
    if len(terms) < 2 or not results:
        return None
    matched = total = 0.0
    for row in results:
        text = ' '.join([str(row.get('title', '')), str(row.get('snippet') or ''), re.sub(r'[/_.\-?=&:]+', ' ', str(row.get('url', '')))])
        words = set(re.findall(r'[^\W_]+', unicodedata.normalize('NFKC', text).casefold()))
        weight = 1 / math.log2(int(row.get('position', 1)) + 1)
        total += weight
        matched += weight if all(_term_present(term, words) for term in terms) else 0.0
    return round(matched / total, 3) if total else None


def query_check(snapshots: list[dict]) -> dict[str, dict]:
    """Flag captures whose organic results do not match the panel's own query (observed: results for one query word only).

    The reference is the best match any capture of this panel reached, so the check abstains until one capture has shown that the
    query terms normally appear in its results. It is an analysis overlay: stored observations are never modified."""
    shares = {snapshot['captured_at']: query_match(snapshot) for snapshot in snapshots}
    known = [value for value in shares.values() if value is not None]
    reference = max(known) if known else None
    checks = {}
    for captured_at, share in shares.items():
        applicable = share is not None and reference is not None and reference >= QUERY_MATCH_REFERENCE
        flagged = bool(applicable and share <= QUERY_MATCH_FLOOR and share <= reference * QUERY_MATCH_RATIO)
        checks[captured_at] = {'share': share, 'reference': reference, 'applicable': applicable, 'flagged': flagged}
    return checks


def retry_suspected(history: list[dict], snapshot: dict) -> bool:
    """Collection-time trigger for one extra request. Without a panel reference only an almost total miss qualifies;
    a needless retry costs one request and the overlay still decides what the analysis uses."""
    share = query_match(snapshot)
    if share is None:
        return False
    known = [value for value in (query_match(row) for row in history) if value is not None]
    reference = max(known) if known else None
    if reference is not None and reference >= QUERY_MATCH_REFERENCE:
        return share <= QUERY_MATCH_FLOOR and share <= reference * QUERY_MATCH_RATIO
    return share <= QUERY_MATCH_UNREFERENCED


def apply_query_check(snapshots: list[dict]) -> list[dict]:
    """Mark flagged captures ineligible in the analysis view. A human review that kept the observation overrides the flag."""
    for snapshot in snapshots:
        snapshot.pop('query_check', None)
    checks = query_check(snapshots)
    for snapshot in snapshots:
        check = checks.get(snapshot['captured_at'])
        if not check or check['share'] is None:
            continue
        snapshot['query_check'] = check
        review = snapshot.get('observation_review') or {}
        state = (snapshot.get('quality') or {}).get('state')
        if check['flagged'] and not (review and not review.get('excluded')) and state not in {'quarantined', 'excluded'}:
            snapshot['quality_ok'] = False
            snapshot['quality'] = {**(snapshot.get('quality') or {}), 'state': 'query_mismatch', 'eligible': False,
                                   'reasons': [f"Organic results do not match the query: {check['share']:.0%} of rank weight contains every query term, "
                                               f"against {check['reference']:.0%} in this panel's best capture. Treated as a failed collection; the observation is kept."]}
    return snapshots


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
