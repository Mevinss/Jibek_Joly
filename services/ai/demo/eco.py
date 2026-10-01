"""Target-time advice with synthetic speed ramps. Advisory only."""
from datetime import datetime, timedelta

BASE = datetime.fromisoformat('2026-10-02T08:00:00+05:00')

def eco_advice(*, distance_km, current_speed_kmh, speed_limit_kmh,
               now_min, signal_open_min, mass_tons=1000):
    result = dict(status='UNKNOWN', recommended_speed_kmh=None, cruise_speed_kmh=None,
        full_stop_avoided=False, recommended_speed_profile=[], target_arrival_time=None,
        energy_proxy_units=None, baseline_energy_proxy_units=None,
        energy_proxy_delta=None, synthetic_only=True,
        assumptions=['Synthetic acceleration 0.10 m/s² and deceleration 0.12 m/s²; not validated braking curves.',
            'Energy proxy is not measured diesel consumption.',
            'A red signal always takes priority over advice.'])
    if signal_open_min is None:
        return result
    result['target_arrival_time']=(BASE+timedelta(minutes=signal_open_min)).isoformat()
    seconds=(signal_open_min-now_min)*60
    if seconds<=0:
        return {**result,'status':'EXPIRED'}
    if current_speed_kmh<=0 or distance_km<=0:
        return {**result,'status':'STOPPED'}
    def profile(speed):
        rate=(.12 if speed<current_speed_kmh else .1)*3.6
        tau=min(seconds, abs(speed-current_speed_kmh)/rate)
        sign=1 if speed>current_speed_kmh else -1 if speed<current_speed_kmh else 0
        v=current_speed_kmh+sign*rate*tau
        first=(current_speed_kmh+v)/2*tau/3600
        return tau,v,first,first+v*(seconds-tau)/3600
    if profile(speed_limit_kmh)[3]<distance_km-1e-8:
        return {**result,'status':'UNREACHABLE'}
    if profile(5)[3]>distance_km+1e-8:
        return {**result,'status':'HOLD'}
    lo,hi=5.,speed_limit_kmh
    for _ in range(55):
        mid=(lo+hi)/2
        if profile(mid)[3]>distance_km: hi=mid
        else: lo=mid
    cruise=(lo+hi)/2
    tau,v,first,_=profile(cruise)
    samples=[dict(elapsed_seconds=0,distance_km=0,speed_kmh=current_speed_kmh)]
    if tau>1e-6: samples.append(dict(elapsed_seconds=tau,distance_km=first,speed_kmh=v))
    if seconds-tau>1e-6: samples.append(dict(elapsed_seconds=seconds,distance_km=distance_km,speed_kmh=v))
    baseline_seconds=distance_km/speed_limit_kmh*3600
    stops=baseline_seconds<seconds-1e-6
    mass=mass_tons/1000
    ramp=tau/3600*(.15*(current_speed_kmh+v)/2+.85*(current_speed_kmh**3+current_speed_kmh**2*v+current_speed_kmh*v*v+v**3)/4/speed_limit_kmh**2)
    before=mass*(distance_km+3*int(stops)+.05*max(0,seconds-baseline_seconds)/60)
    after=mass*(ramp+(distance_km-first)*(.15+.85*(v/speed_limit_kmh)**2)+3*max(0,v*v-current_speed_kmh**2)/speed_limit_kmh**2)
    return {**result,'status':'AVAILABLE','recommended_speed_kmh':round(distance_km*3600/seconds,6),
        'cruise_speed_kmh':cruise,'full_stop_avoided':stops,
        'baseline_energy_proxy_units':round(before,6),'energy_proxy_units':round(after,6),
        'energy_proxy_delta':round(after-before,6), 'recommended_speed_profile':samples,
        'energy_proxy_basis':'mass/1000 * [integrated distance drag + 3*positive squared-speed change/cap² + 0.05*idle_min]'}
