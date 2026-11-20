"""Author-defined adapter for PR #5's rounded aggregates. No AI or DB writes."""
from copy import deepcopy
from fractions import Fraction
import hashlib
import json
import math

VERSION = 'team-results-demo-0.1'
WEIGHTS = {'C1': '0.15', 'C2': '0.15', 'C3': '0.15', 'C4': '0.20',
           'C5': '0.10', 'C6': '0.15', 'C7': '0.10'}
RULES = {'version': VERSION, 'weights': WEIGHTS, 'missing': 'no_index_no_reweighting',
         'input_precision': 'rounded_component_scores_1_decimal',
         'low_score': 'less_than_50', 'category_gap': 'at_least_25',
         'source': 'survey', 'approval_status': 'proposed'}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


class ResultsContractError(ValueError):
    pass


def number(value, *, maximum=100):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ResultsContractError('Expected a finite JSON number')
    if not math.isfinite(value) or not 0 <= value <= maximum:
        raise ResultsContractError('Number outside supported range')
    return Fraction(str(value))


def present(value):
    return None if value is None else round(float(value), 2)


def methodology():
    return {**deepcopy(RULES), 'synthetic_only': True, 'official': False,
            'formula': 'sum(component_score * component_weight)',
            'config_sha256': fingerprint(RULES),
            'limitations': [
                'Seven synthetic seed components; not the earlier three-component demo-0.2',
                'Input already rounded by /results; no raw-response precision claim',
                'No approved mapping to appendices B/V; no official maturity labels',
                'No expected cohort size or expert evidence in upstream contract',
                'Database does not yet freeze questionnaire versions per cycle']}


def _validate(data):
    if data.get('assessment', {}).get('status') != 'closed':
        raise ResultsContractError('Only closed assessments are supported')
    k = data.get('min_group_size')
    if type(k) is not int or k < 1:
        raise ResultsContractError('Invalid min_group_size')
    total = data.get('responses_total')
    if total is not None and (type(total) is not int or total < k):
        raise ResultsContractError('Invalid visible response count')
    comps = data.get('components', [])
    if len(comps) != 7 or {c['code'] for c in comps} != set(WEIGHTS):
        raise ResultsContractError('Expected exactly the seven seed components')
    categories = data.get('categories', [])
    ids = [c['category'] for c in categories]
    if len(ids) != len(set(ids)):
        raise ResultsContractError('Duplicate category')
    for cat in categories:
        if type(cat['hidden']) is not bool:
            raise ResultsContractError('hidden must be boolean')
        if not cat['hidden'] and (type(cat['responses']) is not int or cat['responses'] < k):
            raise ResultsContractError('Visible category is smaller than k')
    for c in comps:
        if number(c['weight'], maximum=1) != Fraction(WEIGHTS[c['code']]):
            raise ResultsContractError('Weights differ from the explicit demo version')
        if c['score'] is not None:
            number(c['score'])
        cells = c.get('by_category', [])
        if len(cells) != len(ids) or {x['category'] for x in cells} != set(ids):
            raise ResultsContractError('Category cells do not match categories')
        for fact in c.get('objective_indicators', []):
            if type(fact.get('confirmed')) is not bool:
                raise ResultsContractError('confirmed must be boolean')
            if fact.get('value') is not None:
                number(fact['value'])
        for cell in cells:
            if type(cell['hidden']) is not bool:
                raise ResultsContractError('hidden must be boolean')
            if cell['score'] is not None:
                number(cell['score'])


def calculate_index(data):
    """Consume /results exactly once; never recover suppressed values."""
    _validate(data)
    total_visible = data['responses_total'] is not None
    rows = []
    for comp in sorted(data['components'], key=lambda c: c['code']):
        score = number(comp['score']) if total_visible and comp['score'] is not None else None
        weight = Fraction(WEIGHTS[comp['code']])
        rows.append({'code': comp['code'], 'name': comp['name'],
                     'score': present(score), 'weight': float(weight), 'weight_exact': str(weight),
                     'contribution': present(score * weight) if score is not None else None,
                     'contribution_exact': str(score * weight) if score is not None else None,
                     'status': 'ok' if score is not None else ('missing' if total_visible else 'suppressed')})
    overall = (sum((Fraction(r['contribution_exact']) for r in rows), Fraction(0))
               if all(r['status'] == 'ok' for r in rows) else None)
    groups = []
    comps = {c['code']: c for c in data['components']}
    for cat in sorted(data['categories'], key=lambda c: c['category']):
        cells = [next(x for x in comps[code]['by_category'] if x['category'] == cat['category'])
                 for code in sorted(WEIGHTS)]
        hidden = not total_visible or cat['hidden'] or any(x['hidden'] for x in cells)
        available = not hidden and all(x['score'] is not None for x in cells)
        score = sum((number(x['score']) * Fraction(WEIGHTS[code])
                     for code, x in zip(sorted(WEIGHTS), cells)), Fraction(0)) if available else None
        groups.append({'category': cat['category'], 'hidden': hidden,
                       'responses': None if hidden else cat['responses'],
                       'status': 'suppressed' if hidden else ('ok' if available else 'missing'),
                       'index': present(score), 'index_exact': str(score) if score is not None else None})
    return {'assessment': deepcopy(data['assessment']), 'source': 'survey',
            'synthetic_only': True, 'methodology_version': VERSION, 'approval_status': 'proposed',
            'official': False, 'index': present(overall),
            'index_exact': str(overall) if overall is not None else None,
            'status': 'ok' if overall is not None else ('insufficient_data' if total_visible else 'suppressed'),
            'components': rows, 'by_category': groups,
            'coverage': {'available_components': sum(r['status'] == 'ok' for r in rows),
                         'expected_components': 7, 'response_rate': None},
            'expert': {'status': 'not_available', 'index': None},
            'audit': {'config_sha256': fingerprint(RULES), 'input_sha256': fingerprint(data)},
            'precision': 'Weighted sum of /results decimals; upstream error up to 0.05 points',
            'warnings': methodology()['limitations']}
