"""Inference from the explicitly synthetic Kazakhstan timetable model."""
import json
import pandas as pd
from ..settings import SERVICE
from ..demo.simulation import geometry
from ..training.train_kz_schedule import FEATURES,CATEGORIES

class ScheduleForecaster:
    def __init__(self):
        import lightgbm as lgb
        directory=SERVICE/'models/kz_schedule_demo'
        self.info=json.loads((directory/'metrics.json').read_text(encoding='utf-8'))
        self.model=lgb.Booster(model_file=str(directory/'model.txt'))

    def forecast(self,state):
        geo=geometry();services={s['train_id']:s for s in geo['services']};stations={s['id']:s for s in geo['stations']};rows=[];metadata=[]
        for t in state.trains:
            svc=services.get(t.train_id);block=next((f['properties'] for f in geo['features'] if f['properties']['id']==t.position.block_id),None)
            if not svc or not block:continue
            segment=[f['properties'] for f in geo['features'] if f['properties']['segment_id']==block['segment_id']]
            direction=1 if svc['direction']=='forward' else -1
            destination=block['to_station'] if direction==1 else block['from_station'];length=sum(b['length_km'] for b in segment)
            current=block['start_km']+t.position.km
            rows.append(dict(distance_km=length,speed_limit_kmh=block['speed_limit'],category_code=CATEGORIES[svc['category']],destination_tracks=stations[destination]['tracks'],direction=direction))
            metadata.append((t.train_id,block['segment_id'],min(1.,max(0.,abs(stations[destination]['km']-current)/length))))
        if not rows:return []
        values=self.model.predict(pd.DataFrame(rows)[FEATURES],num_threads=1)
        return [dict(train_id=tid,segment_id=segment,scheduled_segment_travel_min=round(max(0.,float(value)),2),
            nominal_remaining_min=round(max(0.,float(value))*fraction,2),model_version=self.info['model_version'],synthetic_only=True,
            warning='Learned synthetic timetable; excludes incidents, waiting and actual delays.') for (tid,segment,fraction),value in zip(metadata,values)]
