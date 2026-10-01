from fastapi.testclient import TestClient
from services.ai.main import app
from services.ai.demo.simulation import snapshot, geometry


def test_unvalidated_domain_never_gets_numeric_advisory():
    with TestClient(app) as client:
        state=snapshot(300,'closure')['state']
        result=client.post('/forecast/advisory',json=state).json()
        assert len(result)==28
        assert all(not r['reliable'] and r['delay_interval_min'] is None and r['solver_buffer_s'] is None for r in result)
        assert any(r['known_wait_min']>0 for r in result)
        # Legacy contract remains callable for existing consumers.
        assert all('expected_delay_s' in r for r in client.post('/forecast',json=state).json())


def test_numerical_ood_suppresses_interval_and_probability():
    with TestClient(app) as client:
        state=snapshot()['state']; state['trains']=state['trains'][:1]
        state['trains'][0].update(source_domain='pkp',delay_s=604800)
        result=client.post('/forecast/advisory',json=state).json()[0]
        assert 'prev_delay_departure_min' in result['ood_features']
        assert result['delay_growth_probability'] is None


def test_closure_reopens_and_replay_is_deterministic():
    assert snapshot(700,'chaos',0)==snapshot(700,'chaos',0)
    assert snapshot(1499,'closure')['incident_active']
    assert not snapshot(1500,'closure')['incident_active']
    assert not any(b['closed'] for b in snapshot(1501,'closure')['state']['infra']['blocks'])
    before=snapshot(1499,'closure');after=snapshot(1600,'closure')
    held=[d for d in before['display'] if d['held']]
    assert held
    positions={d['train_id']:d for d in after['display']}
    assert any((positions[d['train_id']]['corridor_km']-d['corridor_km'])*d['direction']>0 for d in held)
    assert snapshot(300,'closure')['quality']['category']=='critical'


def test_all_trains_stay_on_their_route_even_at_endpoints():
    geo=geometry();stations={s['id']:s['km'] for s in geo['stations']};blocks={f['properties']['id']:f['properties'] for f in geo['features']}
    for elapsed in (0,300,1500,10000,86400):
        s=snapshot(elapsed,'closure')
        for t,d in zip(s['state']['trains'],s['display']):
            lo,hi=sorted([stations[d['origin']],stations[d['destination']]])
            b=blocks[t['position']['block_id']]
            assert lo<=d['corridor_km']<=hi
            assert b['start_km']>=lo and b['end_km']<=hi+1e-6
