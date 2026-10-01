"""Kazakhstan timetable playback with advisory incident examples, not an optimizer."""
import json
from functools import lru_cache
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE=datetime(2026,10,1,11,tzinfo=timezone(timedelta(hours=5)))

@lru_cache
def geometry():
    return json.loads((Path(__file__).parent/'corridor.json').read_text(encoding='utf-8'))

@lru_cache
def schedules():
    geo=geometry(); stations={s['id']:s for s in geo['stations']}
    result={}
    for service in geo['services']:
        stops=[s for s in geo['timetable'] if s['train_id']==service['train_id']]
        points=[]
        for s in stops:
            for field in ('scheduled_arrival','scheduled_departure'):
                if s[field]:points.append(((datetime.fromisoformat(s[field])-BASE).total_seconds(),stations[s['station_id']]['km']))
        result[service['train_id']]=sorted(set(points))
    return result

def planned(tid,t):
    points=schedules()[tid]
    if t<=points[0][0]:return points[0][1],0.
    for (ta,a),(tb,b) in zip(points,points[1:]):
        if t<=tb:return a+(b-a)*(t-ta)/(tb-ta),abs(b-a)*3600/(tb-ta)
    return points[-1][1],0.

def snapshot(elapsed=0.,incident='none',incident_at=0.):
    geo=geometry(); low,high=65.,174. # BOR-AKK in the synthetic fixture
    active=elapsed>=incident_at and incident!='none'
    blocks=[dict(id=f['properties']['id'],closed=active and incident in ('closure','chaos') and f['properties']['segment_id']=='BOR-AKK',
        speed_limit=min(60,f['properties']['speed_limit']) if active and incident=='restriction' else f['properties']['speed_limit'],
        occupied=False,num_platform_tracks=f['properties']['station_tracks'],is_passing_loop=True,is_node=False) for f in geo['features']]
    trains,display=[],[]
    for i,svc in enumerate(geo['services']):
        tid=svc['train_id'];direction=1 if svc['direction']=='forward' else -1
        delay=float([0,120,300,60,600][i%5]);extra=600 if active and incident=='chaos' and i<10 else 0
        imposed=min(extra,max(0.,elapsed-incident_at))
        effective=elapsed-delay-imposed
        if active and incident=='restriction':effective=min(effective,incident_at-delay)+max(0,effective-(incident_at-delay))*.6
        position,speed=planned(tid,effective)
        if extra and elapsed-incident_at<extra:speed=0.
        if active and incident=='restriction':speed*=.6
        if active and incident in ('closure','chaos'):
            at,_=planned(tid,incident_at-delay)
            stop=at if low<=at<=high else low-.02 if direction==1 and at<low else high+.02 if direction==-1 and at>high else None
            if stop is not None and (position-stop)*direction>=0:
                # Find schedule time at stop for a growing, consistent delay.
                lost=abs(position-stop)*3600/max(speed,1)
                position,speed=stop,0.;delay+=lost
        delay+=imposed
        ghost,_=planned(tid,elapsed)
        candidates=[f for f in geo['features'] if f['properties']['start_km']-1e-7<=position<=f['properties']['end_km']+1e-7]
        f=candidates[-1] if direction==1 else candidates[0];p=f['properties']
        block=next(b for b in blocks if b['id']==p['id']);block['occupied']=True
        km=max(0.,min(p['length_km'],position-p['start_km']))
        next_id=p['to_station'] if direction==1 else p['from_station']; next_station=next(s for s in geo['stations'] if s['id']==next_id)
        trains.append(dict(train_id=tid,type='груз' if svc['category']=='freight' else 'пасс',priority=1 if svc['category']=='freight' else 3,
            position=dict(block_id=p['id'],km=km),speed=speed,delay_s=delay,ts=(BASE+timedelta(seconds=elapsed)).isoformat(),
            min_technical_time_min=p['min_technical_time_min'],time_reserve_min=2.))
        display.append(dict(train_id=tid,label=tid.replace('SIM-',''),corridor_km=position,scheduled_km=ghost,direction=direction,
            next_station=next_id,eta_s=abs(next_station['km']-position)*3600/speed if speed else None,
            origin=svc['origin_station_id'],destination=svc['destination_station_id']))
    stations=[]
    for s in geo['stations']:
        nearby=[d['train_id'] for d in display if abs(d['corridor_km']-s['km'])<2]
        stations.append(dict(id=s['id'],occupied=min(len(nearby),s['tracks']),capacity=s['tracks'],trains=nearby,
            problem=active and incident in ('closure','chaos') and low<=s['km']<=high))
    return dict(source='kazakhstan_synthetic_timetable',elapsed_s=elapsed,ts=(BASE+timedelta(seconds=elapsed)).isoformat(),
        state=dict(trains=trains,infra=dict(blocks=blocks,signals=[],switches=[])),display=display,stations=stations,
        incident=incident,note='Казахстанская симуляция. ML перенос с PKP не валидирован; солвер и ATO не подключены.')
