"""Target-time advice for synthetic signal windows. Idealized, advisory only."""
from datetime import datetime, timedelta

BASE = datetime.fromisoformat('2026-10-02T08:00:00+05:00')

def eco_advice(*, distance_km, current_speed_kmh, speed_limit_kmh,
               now_min, signal_open_min, mass_tons=1000):
    result = dict(status='UNKNOWN', recommended_speed_kmh=None,
        full_stop_avoided=False, recommended_speed_profile=[], target_arrival_time=None,
        energy_proxy_units=None, baseline_energy_proxy_units=None,
        energy_proxy_delta=None, synthetic_only=True,
        assumptions=['Instantaneous speed transition; no braking-distance validation.',
            'Energy proxy is a synthetic index, not litres, kWh or validated fuel saving.',
            'A red signal always takes priority over advice.'])
    if signal_open_min is None:
        return result
    result['target_arrival_time']=(BASE+timedelta(minutes=signal_open_min)).isoformat()
    seconds=(signal_open_min-now_min)*60
    if seconds<=0:
        return {**result,'status':'EXPIRED'}
    if current_speed_kmh<=0 or distance_km<=0:
        return {**result,'status':'STOPPED'}
    required=distance_km*3600/seconds
    if required>speed_limit_kmh:
        return {**result,'status':'UNREACHABLE'}
    if required<5:
        return {**result,'status':'HOLD'}
    baseline_seconds=distance_km/current_speed_kmh*3600
    stops=baseline_seconds<seconds-1e-6
    mass=mass_tons/1000
    rolling=lambda speed: distance_km*(.15+.85*(speed/speed_limit_kmh)**2)
    before=mass*(rolling(current_speed_kmh)+3*int(stops)+.05*max(0,seconds-baseline_seconds)/60)
    after=mass*(rolling(required)+2*((current_speed_kmh-required)/speed_limit_kmh)**2)
    return {**result,'status':'AVAILABLE','recommended_speed_kmh':round(required,6),
        'full_stop_avoided':stops,'baseline_energy_proxy_units':round(before,6),
        'energy_proxy_units':round(after,6),'energy_proxy_delta':round(after-before,6),
        'energy_proxy_basis':'mass/1000 * [distance*(0.15+0.85*(speed/cap)^2) + 3*stops + 0.05*idle_min + squared_speed_changes]',
        'recommended_speed_profile':[{'elapsed_seconds':0,'distance_km':0,'speed_kmh':required},
            {'elapsed_seconds':seconds/2,'distance_km':distance_km/2,'speed_kmh':required},
            {'elapsed_seconds':seconds,'distance_km':distance_km,'speed_kmh':required}]}
