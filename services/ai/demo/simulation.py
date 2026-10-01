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
    incident_end=incident_at+1500
    active=incident_at<=elapsed<incident_end and incident!='none'
    blocks=[dict(id=f['properties']['id'],closed=active and incident in ('closure','chaos') and f['properties']['segment_id']=='BOR-AKK',
        speed_limit=min(60,f['properties']['speed_limit']) if active and incident=='restriction' else f['properties']['speed_limit'],
        occupied=False,num_platform_tracks=f['properties']['station_tracks'],is_passing_loop=True,is_node=False) for f in geo['features']]
    trains,display=[],[]
    for i,svc in enumerate(geo['services']):
        tid=svc['train_id'];direction=1 if svc['direction']=='forward' else -1
        delay=float([0,120,300,60,600][i%5]);extra=600 if elapsed>=incident_at and incident=='chaos' and i<10 else 0
        imposed=min(extra,max(0.,elapsed-incident_at))
        effective=elapsed-delay-imposed
        wait=0.;blocked=False
        if elapsed>=incident_at and incident in ('closure','chaos'):
            at,_=planned(tid,incident_at-delay)
            stop=at if low<=at<=high else low-.02 if direction==1 and at<low else high+.02 if direction==-1 and at>high else None
            if stop is not None:
                crossing=None
                for (ta,a),(tb,b) in zip(schedules()[tid],schedules()[tid][1:]):
                    if a!=b and min(a,b)<=stop<=max(a,b):
                        crossing=ta+(stop-a)/(b-a)*(tb-ta)+delay+imposed; break
                if crossing is not None:
                    start=max(incident_at,crossing)
                    loss=max(0.,min(elapsed,incident_end)-start)
                    effective-=loss;delay+=loss
                    blocked=active and elapsed>=start
                    wait=max(0,incident_end-elapsed) if blocked else 0.
        if elapsed>=incident_at and incident=='restriction':
            lost=max(0,min(elapsed,incident_end)-incident_at)*.4
            effective-=lost;delay+=lost
        position,speed=planned(tid,effective)
        if extra and elapsed-incident_at<extra:speed=0.
        if active and incident=='restriction':speed=min(60,speed*.6)
        if blocked:position,speed=stop,0.
        delay+=imposed
        ghost,_=planned(tid,elapsed)
        endpoints=[s['km'] for s in geo['stations'] if s['id'] in (svc['origin_station_id'],svc['destination_station_id'])]
        candidates=[f for f in geo['features'] if f['properties']['start_km']-1e-7<=position<=f['properties']['end_km']+1e-7 and f['properties']['start_km']>=min(endpoints) and f['properties']['end_km']<=max(endpoints)+1e-7]
        f=candidates[-1] if direction==1 else candidates[0];p=f['properties']
        block=next(b for b in blocks if b['id']==p['id']);block['occupied']=True
        km=max(0.,min(p['length_km'],position-p['start_km']))
        next_id=p['to_station'] if direction==1 else p['from_station']; next_station=next(s for s in geo['stations'] if s['id']==next_id)
        trains.append(dict(train_id=tid,type='груз' if svc['category']=='freight' else 'пасс',priority=1 if svc['category']=='freight' else 3,
            position=dict(block_id=p['id'],km=km),speed=speed,delay_s=delay,ts=(BASE+timedelta(seconds=elapsed)).isoformat(),
            min_technical_time_min=p['min_technical_time_min'],time_reserve_min=2.,
            source_domain='kz_synthetic',deterministic_wait_s=wait,next_block_closed=blocked,
            restriction_extra_s=max(0,incident_end-elapsed)*.4 if active and incident=='restriction' else 0.))
        display.append(dict(train_id=tid,label=tid.replace('SIM-',''),corridor_km=position,scheduled_km=ghost,direction=direction,
            next_station=next_id,eta_s=abs(next_station['km']-position)*3600/speed if speed else None,
            origin=svc['origin_station_id'],destination=svc['destination_station_id'],
            distance_to_station_km=abs(next_station['km']-position),held=blocked,
            incident_end=(BASE+timedelta(seconds=incident_end)).isoformat() if active else None,
            scheduled_arrival=next((s['scheduled_arrival'] for s in geo['timetable'] if s['train_id']==tid and s['station_id']==next_id),None)))
    stations=[]
    for s in geo['stations']:
        nearby=[d['train_id'] for d in display if abs(d['corridor_km']-s['km'])<2]
        stations.append(dict(id=s['id'],occupied=min(len(nearby),s['tracks']),capacity=s['tracks'],trains=nearby,
            problem=active and incident in ('closure','chaos') and low<=s['km']<=high))
    factors=[dict(key='delay',points=min(30,sum(t['delay_s'] for t in trains)/len(trains)/60*2)),
        dict(key='closure',points=30 if active and incident in ('closure','chaos') else 0),
        dict(key='stopped',points=min(15,sum(d['held'] for d in display)*3)),
        dict(key='restriction',points=15 if active and incident=='restriction' else 0),
        dict(key='capacity',points=min(10,sum(max(0,len(s['trains'])-s['capacity']) for s in stations)*2))]
    score=round(max(0,100-sum(f['points'] for f in factors)),1)
    category='critical' if active and incident in ('closure','chaos') or score<40 else 'attention' if score<75 else 'normal'
    return dict(source='kazakhstan_synthetic_timetable',elapsed_s=elapsed,ts=(BASE+timedelta(seconds=elapsed)).isoformat(),
        state=dict(trains=trains,infra=dict(blocks=blocks,signals=[],switches=[])),display=display,stations=stations,
        incident=incident,incident_active=active,incident_end_s=incident_end,quality=dict(score=score,category=category,factors=factors,demonstration=True),
        note='Казахстанская симуляция. ML перенос с PKP не валидирован; солвер и ATO не подключены.')
