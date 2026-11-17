"""Read-only deterministic proposals. No acceptance or index changes."""
from fractions import Fraction
from .scoring import calculate_index, fingerprint
from .analytics import compare_categories, objective_context


def generate_recommendations(data):
    report = calculate_index(data)
    proposals = []

    def add(rule_id, code, basis, action):
        identity = {'assessment_id': data['assessment']['id'], 'rule_id': rule_id,
                    'component_code': code, 'basis': basis, 'audit': report['audit']}
        proposals.append({'id': fingerprint(identity)[:24], **identity,
                          'text': action, 'status': 'proposed', 'owner_role': None,
                          'due_date': None, 'requires_human_decision': True})

    for row in report['components']:
        if row['status'] != 'ok':
            add('DATA_QUALITY_V1', row['code'], {'status': row['status']},
                'Перевірити допустимість агрегованих даних; не розкривати приховані групи.')
        elif Fraction(str(row['score'])) < 50:
            add('LOW_SCORE_LT_50_V1', row['code'], {'score': row['score'], 'threshold': 50},
                'Переглянути практики компонента «' + row['name'] + '» та погодити план покращення.')
    for gap in compare_categories(data):
        if gap['flag']:
            add('CATEGORY_GAP_GE_25_V1', gap['component_code'], gap,
                'Перевірити трактування питання й причини розбіжності між видимими категоріями.')
    return {'assessment': report['assessment'], 'methodology_version': report['methodology_version'],
            'approval_status': 'proposed', 'proposals': sorted(proposals, key=lambda x: x['id']),
            'objective_context': objective_context(data), 'audit': report['audit'],
            'persistence': 'none; human acceptance and Tracker storage are a separate command'}
