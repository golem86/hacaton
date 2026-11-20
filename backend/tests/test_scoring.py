"""Synthetic formula tests and real SQLite/API integration for participant #4."""
from copy import deepcopy
from datetime import date
from fractions import Fraction
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app.models import Cycle, Recommendation
from app.services.scoring import VERSION, WEIGHTS, calculate_index, methodology, ResultsContractError
from app.services.analytics import compare_categories, compare_periods, objective_context
from app.services.recommendations import generate_recommendations
from app.services.tracker import transition, is_overdue

client=TestClient(app)
HEADERS={'X-Role':'manager'}
PARAMS={'methodology':VERSION}

@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setenv('INTEGRITY_ANALYTICS_DEMO','1')

@pytest.fixture
def data():
    return {'assessment':{'id':901,'name':'SYNTHETIC','status':'closed'},
            'min_group_size':5,'responses_total':16,
            'categories':[{'category':'staff','responses':None,'hidden':True},
                          {'category':'npp','responses':10,'hidden':False},
                          {'category':'cadets','responses':5,'hidden':False}],
            'components':[{'code':c,'name':c,'weight':float(w),'score':50,
                           'by_category':[{'category':'staff','score':None,'hidden':True},
                                          {'category':'npp','score':75,'hidden':False},
                                          {'category':'cadets','score':50,'hidden':False}],
                           'objective_indicators':[{'name':'SYNTHETIC context','value':80,'confirmed':True}]}
                          for c,w in WEIGHTS.items()]}

def test_manual_exact_formula_immutable(data):
    before=deepcopy(data);r=calculate_index(data)
    assert r['index_exact']=='50'
    assert [c['contribution'] for c in r['components']]==[7.5,7.5,7.5,10,5,7.5,5]
    assert sum(Fraction(c['contribution_exact']) for c in r['components'])==50
    assert r==calculate_index(data) and data==before
    assert r['expert']['index'] is None and r['coverage']['response_rate'] is None

@pytest.mark.parametrize('score',[0,100,33.3])
def test_bounds_and_decimals(data,score):
    for c in data['components']:c['score']=score
    assert calculate_index(data)['index_exact']==str(Fraction(str(score)))

def test_monotonicity(data):
    old=Fraction(calculate_index(data)['index_exact']);data['components'][0]['score']+=1
    assert Fraction(calculate_index(data)['index_exact'])-old==Fraction(15,100)

@pytest.mark.parametrize('bad',[-1,101,True,'50',float('nan'),float('inf')])
def test_bad_scores(data,bad):
    data['components'][0]['score']=bad
    with pytest.raises(ResultsContractError):calculate_index(data)

@pytest.mark.parametrize('change',['weight','missing','duplicate','open','small'])
def test_bad_contract(data,change):
    if change=='weight':data['components'][0]['weight']=.2
    elif change=='missing':data['components'].pop()
    elif change=='duplicate':data['components'][-1]=data['components'][0]
    elif change=='open':data['assessment']['status']='open'
    else:data['categories'][1]['responses']=1
    with pytest.raises(ResultsContractError):calculate_index(data)

def test_missing_does_not_redistribute_weights(data):
    data['components'][0]['score']=None;r=calculate_index(data)
    assert r['index'] is None and r['status']=='insufficient_data'
    assert r['components'][1]['weight_exact']=='3/20'
    assert r['coverage']['available_components']==6

def test_hidden_never_reconstructed(data):
    for c in data['components']:c['by_category'][0]['score']=99
    r=calculate_index(data);group=next(g for g in r['by_category'] if g['category']=='staff')
    assert group['index'] is None and group['responses'] is None
    for gap in compare_categories(data):
        if 'staff' in (gap['left_category'],gap['right_category']):
            assert gap['gap_points'] is None and gap['flag'] is None
    assert all('staff' not in str(p['basis']) for p in generate_recommendations(data)['proposals'])

def test_missing_total_suppresses_all(data):
    data['responses_total']=None;r=calculate_index(data)
    assert r['index'] is None and r['status']=='suppressed'
    assert all(g['index'] is None and g['responses'] is None for g in r['by_category'])
    assert all(g['gap_points'] is None for g in compare_categories(data))

def test_threshold_rules_and_stable_ids(data):
    visible=[g for g in compare_categories(data) if g['status']=='ok']
    assert len(visible)==7 and all(g['gap_points']==-25 and g['flag'] for g in visible)
    r=generate_recommendations(data)
    assert len(r['proposals'])==7 and r==generate_recommendations(data)
    assert len({p['id'] for p in r['proposals']})==7
    assert all(p['status']=='proposed' and p['owner_role'] is None for p in r['proposals'])
    data['components'][0]['score']=49.9
    low=[p for p in generate_recommendations(data)['proposals'] if p['rule_id']=='LOW_SCORE_LT_50_V1']
    assert len(low)==1 and low[0]['component_code']=='C1'

def test_objective_context_separate(data):
    r=objective_context(data)[0]
    assert r['objective_value']==80 and r['survey_score']==50 and r['gap_points'] is None
    data['components'][0]['objective_indicators'][0]['confirmed']=False
    assert objective_context(data)[0]['objective_value'] is None
    assert calculate_index(data)['index']==50

def test_limited_comparison(data):
    after=deepcopy(data);after['assessment']['id']=902
    for c in after['components']:c['score']=75
    r=compare_periods(data,after)
    assert r['change_points']==25 and r['status']=='limited_comparability'
    with pytest.raises(ValueError):compare_periods(data,data)

@pytest.mark.parametrize('role,status',[('admin',200),('manager',200),('auditor',200),
    ('anticorruption',200),('respondent',403),('expert',403),('data_officer',403),('unknown',401),(None,401)])
def test_api_roles(enabled,role,status):
    headers={'X-Role':role} if role else {}
    assert client.get('/api/assessments/1/index',params=PARAMS,headers=headers).status_code==status

def test_explicit_demo_and_version(enabled,monkeypatch):
    path='/api/assessments/1/index'
    assert client.get(path,headers=HEADERS).status_code==422
    assert client.get(path,headers=HEADERS,params={'methodology':'official'}).status_code==422
    monkeypatch.delenv('INTEGRITY_ANALYTICS_DEMO')
    assert client.get(path,headers=HEADERS,params=PARAMS).status_code==503

@pytest.mark.parametrize('suffix',['index','recommendations'])
def test_api_open_and_missing(enabled,suffix):
    assert client.get(f'/api/assessments/3/{suffix}',params=PARAMS,headers=HEADERS).status_code==409
    assert client.get(f'/api/assessments/999999/{suffix}',params=PARAMS,headers=HEADERS).status_code==404

def test_real_api_database_formula_and_suppression(enabled):
    upstream=client.get('/api/assessments/1/results',headers=HEADERS).json()
    actual=client.get('/api/assessments/1/index',params=PARAMS,headers=HEADERS)
    assert actual.status_code==200
    expected=sum(Fraction(str(c['score']))*Fraction(str(c['weight'])) for c in upstream['components'])
    assert actual.json()['index_exact']==str(expected)
    assert actual.json()==calculate_index(upstream)
    # D4: приховані категорії (staff, mgmt) у /results не перелічуються взагалі
    assert {c['category'] for c in upstream['categories']}=={'cadets','npp'} and upstream['suppressed'] is True
    assert {c['category'] for c in actual.json()['by_category']}=={'cadets','npp'}
    assert all(c['index'] is not None for c in actual.json()['by_category'])

def test_api_recommendations_no_database_writes(enabled):
    with SessionLocal() as db:before=db.query(Recommendation).count()
    path='/api/assessments/1/recommendations'
    r=client.get(path,params=PARAMS,headers=HEADERS)
    assert r.status_code==200 and r.json()==client.get(path,params=PARAMS,headers=HEADERS).json()
    assert all(p['status']=='proposed' for p in r.json()['proposals'])
    with SessionLocal() as db:assert db.query(Recommendation).count()==before

def test_api_comparison(enabled):
    params={**PARAMS,'assessment_id':1,'comparison_assessment_id':2}
    r=client.get('/api/analytics/comparisons',params=params,headers=HEADERS)
    assert r.status_code==200 and r.json()['period_comparison']['status']=='limited_comparability'
    params['comparison_assessment_id']=1
    assert client.get('/api/analytics/comparisons',params=params,headers=HEADERS).status_code==422

def test_api_empty_cycle(enabled):
    with SessionLocal() as db:
        c=Cycle(name='SYN_EMPTY',start_date=date(2026,1,1),status='closed');db.add(c);db.commit();id=c.id
    r=client.get(f'/api/assessments/{id}/index',params=PARAMS,headers=HEADERS)
    assert r.status_code==200 and r.json()['index'] is None and r.json()['status']=='suppressed'

def test_methodology_endpoint():
    r=client.get('/api/index-methodologies/'+VERSION,headers=HEADERS)
    assert r.status_code==200 and r.json()==methodology()
    assert sum(Fraction(v) for v in r.json()['weights'].values())==1
    assert r.json()['approval_status']=='proposed'
    assert client.get('/api/index-methodologies/unknown',headers=HEADERS).status_code==404

def test_human_tracker(data):
    p=generate_recommendations(data)['proposals'][0]
    args=dict(actor_id='SYN_MANAGER',human_decision=True,on_date='2026-11-16',reason='Синтетичне рішення')
    with pytest.raises(ValueError):transition(p,'accepted',**args)
    a=transition(p,'accepted',owner_id='SYN_OWNER',due_date='2026-12-01',**args)
    assert p['status']=='proposed' and is_overdue(a,as_of='2026-12-02')
    with pytest.raises(ValueError):transition(a,'completed',**args)
    assert calculate_index(data)['index']==50

@pytest.mark.parametrize('suffix',['recommendations','index'])
def test_no_role_for_each_assessment_route(enabled,suffix):
    assert client.get(f'/api/assessments/1/{suffix}',params=PARAMS).status_code==401
    assert client.get(f'/api/assessments/1/{suffix}',params=PARAMS,headers={'X-Role':'respondent'}).status_code==403


def test_comparison_roles_and_open_cycle(enabled):
    path='/api/analytics/comparisons'
    p={**PARAMS,'assessment_id':1}
    assert client.get(path,params=p).status_code==401
    assert client.get(path,params=p,headers={'X-Role':'respondent'}).status_code==403
    p['comparison_assessment_id']=3
    assert client.get(path,params=p,headers=HEADERS).status_code==409


def test_cell_hidden_flag_is_stricter_than_category(data):
    cell=next(c for c in data['components'][0]['by_category'] if c['category']=='npp')
    cell['hidden']=True
    assert next(c for c in calculate_index(data)['by_category'] if c['category']=='npp')['index'] is None
    assert all(g['gap_points'] is None for g in compare_categories(data))


def test_gap_below_boundary(data):
    for c in data['components']:
        next(x for x in c['by_category'] if x['category']=='npp')['score']=74.9
    assert all(g['flag'] is False for g in compare_categories(data) if g['status']=='ok')


def test_route_handles_incompatible_upstream(enabled,monkeypatch,data):
    from app.routes import analytics
    data['components'][0]['weight']=.9
    monkeypatch.setattr(analytics,'assessment_results',lambda id,db:data)
    r=client.get('/api/assessments/1/index',params=PARAMS,headers=HEADERS)
    assert r.status_code==409


def test_tracker_rejects_automatic_acceptance(data):
    p=generate_recommendations(data)['proposals'][0]
    with pytest.raises(ValueError):
        transition(p,'accepted',actor_id='SYN_BOT',human_decision=False,
                   on_date='2026-11-16',reason='test',owner_id='SYN_OWNER',due_date='2026-12-01')


@pytest.mark.parametrize('same_id', ['901', '0901'])
def test_tracker_cannot_verify_with_same_assessment_id(data, same_id):
    p = generate_recommendations(data)['proposals'][0]
    accepted = transition(p, 'accepted', actor_id='SYN_MANAGER', human_decision=True,
                          on_date='2026-11-16', reason='Прийнято',
                          owner_id='SYN_OWNER', due_date='2026-12-01')
    in_progress = transition(accepted, 'in_progress', actor_id='SYN_OWNER',
                             human_decision=True, on_date='2026-11-17', reason='Почато')
    completed = transition(in_progress, 'completed', actor_id='SYN_OWNER',
                           human_decision=True, on_date='2026-11-18', reason='Виконано',
                           evidence_refs=('SYN-EVIDENCE',))
    with pytest.raises(ValueError, match='different assessment ID'):
        transition(completed, 'verified', actor_id='SYN_MANAGER', human_decision=True,
                   on_date='2026-11-19', reason='Перевірено',
                   evidence_refs=('SYN-REVIEW',), next_assessment_id=same_id)
    assert completed['status'] == 'completed' and 'next_assessment_id' not in completed
