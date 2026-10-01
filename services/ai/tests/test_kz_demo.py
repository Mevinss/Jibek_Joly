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
