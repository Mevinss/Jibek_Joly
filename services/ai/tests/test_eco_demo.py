import pytest
from fastapi.testclient import TestClient
from services.ai.main import app
from services.ai.demo.eco import eco_advice

def inputs(**overrides):
    return dict(distance_km=7, current_speed_kmh=80, speed_limit_kmh=80,
                now_min=0, signal_open_min=10, mass_tons=3500, **overrides)

def test_green_target_avoids_red_stop_and_proxy_is_computed():
    a = eco_advice(**inputs())
    assert a['recommended_speed_kmh'] == 42
    assert 35 < a['cruise_speed_kmh'] < 42
    assert a['recommended_speed_profile'][0]['speed_kmh'] == 80
    assert a['recommended_speed_profile'][1]['speed_kmh'] < 80
    assert a['full_stop_avoided'] is True
    assert a['target_arrival_time'].endswith('08:10:00+05:00')
    assert a['energy_proxy_units'] < a['baseline_energy_proxy_units']
    assert a['recommended_speed_profile'][-1]['distance_km'] == 7
    assert a['recommended_speed_profile'][-1]['elapsed_seconds'] == 600

@pytest.mark.parametrize('change,status', [({'signal_open_min': None}, 'UNKNOWN'),
    ({'signal_open_min': 1}, 'UNREACHABLE'), ({'current_speed_kmh': 0}, 'STOPPED'),
    ({'signal_open_min': 100}, 'HOLD'), ({'signal_open_min': -1}, 'EXPIRED')])
def test_no_fake_avoidance_on_invalid_target(change, status):
    values=inputs();values.update(change)
    a=eco_advice(**values)
    assert a['status'] == status
    assert a['full_stop_avoided'] is False
    assert a['recommended_speed_profile'] == []

def test_api_schema_and_validation():
    with TestClient(app) as c:
        payload={**inputs(), 'train_id':'SIM-FRT-208'}
        r=c.post('/eco/advice', json=payload)
        assert r.status_code == 200
        assert r.json()['train_id'] == payload['train_id']
        payload['distance_km']=-1
        assert c.post('/eco/advice',json=payload).status_code == 422
