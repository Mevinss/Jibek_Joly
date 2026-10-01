import asyncio
import json
from pathlib import Path
import numpy as np
import pytest
from fastapi.testclient import TestClient
from jsonschema import validate
from services.ai.main import app, requests
from services.ai.settings import SERVICE
from services.ai.api.schemas import State, Forecast, ChatRequest
from services.ai.ml.infer import Forecaster
from services.ai.ml.features import FEATURES, serving_frame
from services.ai.agent.tools import Tools, SPECS
from services.ai.agent.chat import stream_chat
from services.ai.agent.grounding import unsupported_numbers


@pytest.fixture
def state():
    return json.loads((SERVICE / 'fixtures/state.json').read_text(encoding='utf-8'))


@pytest.fixture
def client():
    requests.clear()
    with TestClient(app) as c:
        yield c


def test_forecast_contract_determinism(client, state):
    one = client.post('/forecast', json=state)
    assert one.status_code == 200
    assert one.json() == client.post('/forecast', json=state).json()
    assert len(one.json()) == 25
    schema = json.loads((SERVICE.parents[1] / 'contracts/Forecast.schema.json').read_text())
    for row in one.json(): validate(row, schema)


def test_validation(client, state):
    state['trains'][0]['delay_s'] = -1
    assert client.post('/forecast', json=state).status_code == 422
    state['trains'][0]['delay_s'] = 0
    state['trains'][1]['train_id'] = state['trains'][0]['train_id']
    assert client.post('/forecast', json=state).status_code == 422


def test_fallback_unknown_type(tmp_path, state):
    f = Forecaster(tmp_path)
    result = f.forecast(State.model_validate(state))
    assert all(r['model_version'] == 'rule_fallback' for r in result)
    assert all(r['degraded'] for r in result)
    state['trains'][0]['type'] = 'unknown'
    assert Forecaster().forecast(State.model_validate(state))[0]['model_version'] == 'rule_fallback'


def test_no_leakage_and_feature_parity(state):
    assert 'difficulty_id' not in FEATURES
    assert 'delta_delay' not in FEATURES
    x, _ = serving_frame(State.model_validate(state), {})
    assert list(x.columns) == FEATURES
    path = SERVICE / 'models/forecast_v1/features.json'
    if path.exists(): assert json.loads(path.read_text())['features'] == FEATURES


def test_grounding():
    assert unsupported_numbers('Задержка 12 минут', {'delay_min': 12}) == []
    assert unsupported_numbers('Задержка 999 минут', {'delay_min': 12}) == ['999']
    assert not unsupported_numbers('Вероятность 0,13', {'p': .126})
    assert unsupported_numbers('Поезд 1002', {'train_id': '1001'})


def test_health_secrets(client):
    response = client.get('/health')
    assert response.status_code == 200
    assert 'sk-' not in response.text
    assert response.json()['advisory_only']


def test_read_only_tools():
    assert set(SPECS) == {'get_plan', 'get_index', 'get_train_status', 'list_trains', 'get_forecast', 'get_advice', 'get_incidents', 'run_whatif'}


@pytest.mark.asyncio
async def test_whatif_fallback_and_no_mutation():
    tools = Tools(Forecaster())
    before = tools.fixture('state')
    request = ChatRequest(messages=[{'role': 'user', 'content': 'Что будет, если закрыть перегон Б–В на 20 минут?'}])
    events = [e async for e in stream_chat(request, tools, use_llm=False)]
    assert any(e[0] == 'tool_call' and e[1]['name'] == 'run_whatif' for e in events)
    text = ''.join(p['text'] for e, p in events if e == 'token')
    assert '720' in text and 'фикстуры' in text
    assert before == tools.fixture('state')


@pytest.mark.asyncio
async def test_unknown_whatif_does_not_reuse_numbers():
    tools = Tools(Forecaster())
    request = ChatRequest(messages=[{'role': 'user', 'content': 'Закрыть перегон А-Б на 30 минут'}])
    events = [e async for e in stream_chat(request, tools, use_llm=False)]
    text = ''.join(p['text'] for e, p in events if e == 'token')
    assert '720' not in text and 'не рассчитан' in text


@pytest.mark.asyncio
async def test_invalid_tool_and_refusal():
    tools = Tools(Forecaster())
    assert (await tools.call('get_train_status', {}))['error'] == 'invalid_tool_arguments'
    req = ChatRequest(messages=[{'role': 'user', 'content': 'Отправь поезд на красный'}])
    events = [e async for e in stream_chat(req, tools, use_llm=False)]
    assert events[-1][1]['mode'] == 'refusal'
    assert not any(e == 'tool_call' for e, _ in events)


@pytest.mark.asyncio
async def test_whatif_duration_schema():
    tools = Tools(Forecaster())
    incident = {'id': 'demo', 'kind': 'block_closed', 'target_id': 'Б-В',
                'params': {'duration_min': 20}, 'ts': '2026-10-01T10:00:00+05:00'}
    assert (await tools.call('run_whatif', {'incident': incident}))['error'] == 'invalid_tool_arguments'
    incident['params'] = {'minutes': 20}
    result = await tools.call('run_whatif', {'incident': incident})
    assert len(result['data']['variants']) == 3


@pytest.mark.asyncio
async def test_llm_unconfirmed_numbers_rejected():
    async def fake(items, **kwargs):
        return {'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': 'Задержка 9999 минут'}]}]}
    req = ChatRequest(messages=[{'role': 'user', 'content': 'Какой индекс?'}])
    events = [e async for e in stream_chat(req, Tools(Forecaster()), responder=fake)]
    assert '9999' not in ''.join(p['text'] for e, p in events if e == 'token')


def test_texts(client):
    incident = json.loads((SERVICE / 'fixtures/incidents.json').read_text(encoding='utf-8'))[0]
    result = client.post('/telegram', json={'incident': incident}).json()
    assert len(result['text']) <= 400 and 'СРОЧНО' in result['text']
    report = client.post('/report', json={'analytics': {'summary': {'trains': 25}}}).json()['markdown']
    assert report.count('## ') == 6 and '25' in report


def test_rate_limit(client, monkeypatch):
    from services.ai.main import settings
    monkeypatch.setattr(settings, 'requests_per_minute', 1)
    payload = {'analytics': {}}
    assert client.post('/report', json=payload).status_code == 200
    assert client.post('/report', json=payload).status_code == 429
