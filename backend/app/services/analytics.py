"""Compare only published aggregates. Objective measures stay contextual."""
from fractions import Fraction
from itertools import combinations
from .scoring import calculate_index, number, present, fingerprint


def compare_categories(data):
    report = calculate_index(data)
    hidden = {c['category'] for c in report['by_category'] if c['hidden']}
    output = []
    for comp in sorted(data['components'], key=lambda c: c['code']):
        for a, b in combinations(sorted(comp['by_category'], key=lambda x: x['category']), 2):
            visible = (a['category'] not in hidden and b['category'] not in hidden
                       and not a['hidden'] and not b['hidden']
                       and a['score'] is not None and b['score'] is not None)
            gap = number(a['score']) - number(b['score']) if visible else None
            output.append({'component_code': comp['code'], 'left_category': a['category'],
                           'right_category': b['category'], 'status': 'ok' if visible else 'unavailable',
                           'gap_points': present(gap), 'gap_exact': str(gap) if gap is not None else None,
                           'flag': abs(gap) >= 25 if gap is not None else None,
                           'threshold_points': 25,
                           'interpretation': 'Review signal, not proof of dishonesty'})
    return output


def objective_context(data):
    report = calculate_index(data)
    visible = {c['code']: c['score'] for c in report['components']}
    contexts = []
    for comp in sorted(data['components'], key=lambda c: c['code']):
        for fact in comp.get('objective_indicators', []):
            verified = fact.get('confirmed') is True
            value = number(fact['value']) if verified and fact.get('value') is not None else None
            contexts.append({'component_code': comp['code'], 'name': fact['name'],
                             'survey_score': visible[comp['code']], 'objective_value': present(value),
                             'status': 'ok' if value is not None else 'unverified',
                             'comparison_type': 'context_only', 'gap_points': None,
                             'reason': 'Metric IDs, units and evidence links are not supplied by /results'})
    return contexts


def compare_periods(before, after):
    a, b = calculate_index(before), calculate_index(after)
    if a['assessment']['id'] == b['assessment']['id']:
        raise ValueError('Select two different assessments')
    changes = []
    for x, y in zip(a['components'], b['components']):
        delta = number(y['score']) - number(x['score']) if x['score'] is not None and y['score'] is not None else None
        changes.append({'component_code': x['code'], 'change_points': present(delta),
                        'change_exact': str(delta) if delta is not None else None})
    delta = (Fraction(b['index_exact']) - Fraction(a['index_exact'])
             if a['index_exact'] is not None and b['index_exact'] is not None else None)
    return {'before_assessment': a['assessment'], 'after_assessment': b['assessment'],
            'methodology_version': a['methodology_version'],
            'status': 'limited_comparability' if delta is not None else 'unavailable',
            'change_points': present(delta), 'change_exact': str(delta) if delta is not None else None,
            'components': changes,
            'audit': {'before_input_sha256': fingerprint(before), 'after_input_sha256': fingerprint(after)},
            'warnings': ['Caller chooses before/after; chronology is not inferred from IDs',
                         'Population and historical questionnaire versions are absent from /results',
                         'Numerical change does not establish causal improvement']}
