import json
import math
import pytest
from fastapi.testclient import TestClient
from services.ai.main import app
from services.ai.api.schemas import State
from services.ai.demo.simulation import geometry,snapshot,planned
from services.ai.agent.chat import fallback_calls
from services.ai.settings import SERVICE

def test_kazakhstan_only_geometry_and_services():
    g=geometry()
    assert g['country']=='KZ' and len(g['stations'])==9 and len(g['features'])==56
    assert len(g['services'])==28
    assert all(s['country']=='KZ' and 42<s['coordinates'][1]<54 and 68<s['coordinates'][0]<78 for s in g['stations'])
    assert all(s['train_id'].startswith('SIM-') for s in g['services'])
    assert len(set(f['properties']['id'] for f in g['features']))==56
    assert math.isclose(sum(f['properties']['length_km'] for f in g['features']),g['length_km'])


def test_canonical_demo_state_and_topology_routes():
    with TestClient(app) as client:
        response = client.get('/api/v2/state', params={'elapsed': 300, 'incident': 'closure',
                                                        'incident_at': 0, 'seed': 20261001})
        assert response.status_code == 200
        state = response.json()
        assert state['schema_version'] == '2.0'
        assert state['scenario_id'] == 'KZ-DEMO-ADVISORY'
        assert state['seed'] == 20261001
        assert state['source_type'] == 'SIMULATED_DEMO'
        assert any(block['state_conflict'] for block in state['blocks'])
        graph = client.get('/api/topology').json()
        assert graph['schema_version'] == '1.0'
        assert graph['geometry_source'] == 'EXTERNAL_REFERENCE_APPROXIMATE'
        assert {b['block_id'] for b in graph['blocks']} == {b['block_id'] for b in state['blocks']}

@pytest.mark.parametrize('incident',['none','closure','restriction','chaos'])
def test_playback_positions_and_closure(incident):
    before=snapshot(0);after=snapshot(300,incident,0)
    State.model_validate(after['state'])
    blocks={f['properties']['id']:f['properties'] for f in geometry()['features']}
    for t,d in zip(after['state']['trains'],after['display']):
        b=blocks[t['position']['block_id']]
        assert 0<=t['position']['km']<=b['length_km']+1e-6
        assert math.isclose(b['start_km']+t['position']['km'],d['corridor_km'])
        assert d['scheduled_km']==planned(t['train_id'],300)[0]
        if incident=='restriction':assert t['speed']<=60
        if incident in ('closure','chaos') and 65<=d['corridor_km']<=174:assert t['speed']==0
    if incident in ('closure','chaos'):assert sum(b['closed'] for b in after['state']['infra']['blocks'])==4

def test_schedule_model_separate_synthetic_target():
    info=json.loads((SERVICE/'models/kz_schedule_demo/metrics.json').read_text())
    assert info['synthetic_only'] and info['target']=='scheduled_segment_travel_min'
    assert not info['accepted_for_operational_use']
    sets=[set(info['trains'][name]) for name in ['train','validation','test']]
    assert not(sets[0]&sets[1] or sets[0]&sets[2] or sets[1]&sets[2])
    assert info['rows']['total']==128
    with TestClient(app) as c:
        state=snapshot()['state'];response=c.post('/forecast/schedule',json=state)
        assert response.status_code==200 and len(response.json())==28
        assert all(r['synthetic_only'] and r['scheduled_segment_travel_min']>0 for r in response.json())
        assert c.get('/demo/snapshot?elapsed=-1').status_code==422
        assert c.get('/demo/snapshot?incident=unknown').status_code==422
        assert c.get('/infra/geometry').json()['country']=='KZ'
        assert c.get('/forecast/model-info').json()['model_version']=='pkp-main-298694c'

def test_kz_train_id_in_offline_chat():
    assert fallback_calls('Объясни прогноз для поезда SIM-KOK_AST-F01')==[('get_forecast',{'train_id':'SIM-KOK_AST-F01'})]

@pytest.mark.asyncio
async def test_synthetic_model_chat_is_explicit():
    from services.ai.agent.tools import Tools
    from services.ai.agent.chat import stream_chat
    from services.ai.api.schemas import ChatRequest
    from services.ai.ml.infer import Forecaster
    state=State.model_validate(snapshot()['state'])
    request=ChatRequest(messages=[{'role':'user','content':'Объясни учебную модель KZ для SIM-KOK_AST-F01'}],state=state)
    events=[event async for event in stream_chat(request,Tools(Forecaster(),snapshot=state),use_llm=False)]
    answer=''.join(e[1]['text'] for e in events if e[0]=='token')
    assert 'синтетическое расписание' in answer and 'SIM-KOK_AST-F01' in answer
    assert events[-1][1]['mode']=='tool_summary'


@pytest.mark.asyncio
async def test_kz_snapshot_chat_suppresses_unvalidated_pkp_numbers():
    from services.ai.agent.tools import Tools
    from services.ai.agent.chat import stream_chat
    from services.ai.api.schemas import ChatRequest
    from services.ai.ml.infer import Forecaster
    state=State.model_validate(snapshot()['state'])
    tools=Tools(Forecaster(),snapshot=state)
    result=await tools.call('get_forecast',{'train_id':state.trains[0].train_id})
    row=result['data'][0]
    assert not row['reliable'] and row['ml_delta_min'] is None
    assert row['delay_growth_probability'] is None
    assert 'expected_delay_s' not in row and 'p_conflict_15m' not in row
    request=ChatRequest(messages=[{'role':'user','content':f'Прогноз {state.trains[0].train_id}'}],state=state)
    events=[event async for event in stream_chat(request,tools,use_llm=False)]
    answer=''.join(e[1]['text'] for e in events if e[0]=='token')
    assert 'Численная ML-добавка и риск недоступны' in answer
    assert 'синтетический Казахстан' in answer


def test_dispatch_analysis_uses_one_snapshot_and_validates_pair_plan():
    from services.ai.demo.integration import analyze
    first=analyze(300,'closure',0,42)
    again=analyze(300,'closure',0,42,solve=False)
    assert first['snapshot_id']==again['snapshot_id']
    assert first['pair_train_ids']==['SIM-KOK_AST-F01','SIM-KOK_AST-R01']
    assert set(first['fifo']['ordered_train_ids'])==set(first['pair_train_ids'])
    assert first['cp_sat']['status'] in ('OPTIMAL','FEASIBLE')
    assert first['cp_sat']['valid'] is True
    assert first['cp_sat']['reservation_count']>0
    assert all(row['train_id'] in first['pair_train_ids'] for row in first['cp_sat']['reservations'])
    assert first['snapshot_overlaps']
    assert all(len(item['train_ids'])>1 for item in first['snapshot_overlaps'])
    assert first['full_cp_sat']['status'] in ('OPTIMAL','FEASIBLE','INFEASIBLE','TIMEOUT')
    assert analyze(300,'restriction',0,42)['cp_sat']['status']=='UNSUPPORTED_SCENARIO'


def test_dispatch_analysis_endpoint():
    with TestClient(app) as c:
        response=c.post('/dispatch/analysis',json={'elapsed_s':300,'incident':'closure','incident_at_s':0,'seed':42})
        assert response.status_code==200
        assert response.json()['cp_sat']['valid'] is True
        assert c.post('/dispatch/analysis',json={'elapsed_s':-1}).status_code==422


def test_game_decision_uses_same_snapshot_and_platform_validator():
    from services.ai.demo.integration import analyze, check_decision
    analysis=analyze(300,'closure',0,42,solve=False)
    first=check_decision(300,'closure',0,42,'A')
    hold=check_decision(300,'closure',0,42,'C')
    assert first['snapshot_id']==hold['snapshot_id']==analysis['snapshot_id']
    assert not first['accepted'] and 'BLOCK_CLOSED' in first['actions'][0]['issue_codes']
    assert hold['accepted'] and all(row['action']=='HOLD_TRAIN' for row in hold['actions'])
    assert not first['applied'] and not hold['applied']
    with TestClient(app) as c:
        body={'elapsed_s':300,'incident':'closure','incident_at_s':0,'seed':42,'choice':'A'}
        assert c.post('/dispatch/decision',json=body).json()==first
        assert c.post('/dispatch/decision',json={**body,'choice':'D'}).status_code==422
