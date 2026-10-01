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


def test_demo_assets_and_state(client):
    assert client.get('/').status_code == 200
    assert 'TurkiSib' in client.get('/').text
    assert client.get('/app.js').status_code == 200
    response = client.get('/demo/state').json()
    assert response['source'] == 'fixture'
    State.model_validate(response['state'])
    assert client.get('/.env').status_code == 404


@pytest.mark.asyncio
async def test_snapshot_isolation_and_no_unrelated_solver_results(state):
    f = Forecaster()
    snapshot = State.model_validate(state)
    snapshot.trains[0].delay_s = 1200
    tools = Tools(f, snapshot=snapshot)
    result = await tools.call('get_train_status', {'train_id': snapshot.trains[0].train_id})
    assert result['source'] == 'demo_snapshot'
    assert result['data']['delay_s'] == 1200
    original = await Tools(f).call('get_train_status', {'train_id': snapshot.trains[0].train_id})
    assert original['data']['delay_s'] == state['trains'][0]['delay_s']
    forecasts = await tools.call('get_forecast', {})
    assert [{k: v for k, v in r.items() if k != 'display'} for r in forecasts['data']] == f.forecast(snapshot)
    assert forecasts['data'][0]['display']['expected_delay_min'] == round(f.forecast(snapshot)[0]['expected_delay_s'] / 60, 2)
    for name in ['get_plan', 'get_index', 'get_incidents']:
        result = await tools.call(name, {})
        assert result['data']['error'] == 'not_computed_for_demo_snapshot'


def test_chat_passes_request_snapshot_without_global_mutation(client, state, monkeypatch):
    async def fake_stream(request, tools):
        result = await tools.call('get_train_status', {'train_id': '1001'})
        yield 'token', {'text': str(result['data']['delay_s'])}
        yield 'done', {'mode': 'test'}
    monkeypatch.setattr('services.ai.main.stream_chat', fake_stream)
    state['trains'][0]['delay_s'] = 900
    payload = {'messages': [{'role': 'user', 'content': 'Поезд 1001'}], 'state': state}
    assert '900.0' in client.post('/chat', json=payload).text
    payload.pop('state')
    assert '900.0' not in client.post('/chat', json=payload).text


@pytest.mark.asyncio
async def test_forecast_summary_rejects_semantic_relabeling(state):
    counter = 0
    async def responder(items, **kwargs):
        nonlocal counter
        counter += 1
        if counter == 1:
            return {'output': [{'type': 'function_call', 'name': 'get_forecast', 'arguments': '{"train_id":"1001"}', 'call_id': 'f1'}]}
        return {'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': 'Конфликт подтверждён. Нарушения уменьшают задержку.'}]}]}
    request = ChatRequest(messages=[{'role': 'user', 'content': 'Прогноз 1001'}])
    events = [e async for e in stream_chat(request, Tools(Forecaster(), snapshot=State.model_validate(state)), responder=responder)]
    text = ''.join(p['text'] for e,p in events if e == 'token')
    assert 'Конфликт подтверждён' not in text
    assert 'не подтверждает конфликт' in text
    assert 'expected_delay_s' not in text
    assert events[-1][1]['mode'] == 'tool_summary'


@pytest.mark.asyncio
async def test_whatif_fallback_and_no_mutation():
    tools = Tools(Forecaster())
    before = tools.fixture('state')
    request = ChatRequest(messages=[{'role': 'user', 'content': 'Что будет, если закрыть перегон Б–В на 20 минут?'}])
    events = [e async for e in stream_chat(request, tools, use_llm=False)]
    assert any(e[0] == 'tool_call' and e[1]['name'] == 'run_whatif' for e in events)
    text = ''.join(p['text'] for e, p in events if e == 'token')
    assert '720' in text and 'фикстуры' in text
    assert events[-1][1]['mode'] == 'tool_summary'
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
