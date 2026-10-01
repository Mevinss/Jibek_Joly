"""Learn a synthetic timetable, not actual delays. Split by complete SIM service."""
from pathlib import Path
import argparse
import hashlib
import json
import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.model_selection import GroupShuffleSplit
from sklearn.metrics import mean_absolute_error, mean_squared_error
from ..settings import ROOT, SERVICE

FEATURES=['distance_km','speed_limit_kmh','category_code','destination_tracks','direction']
CATEGORIES={'intercity':0,'regional':1,'freight':2}

def rows(base):
    stops=pd.read_csv(base/'run_stops.csv');services=pd.read_csv(base/'train_services.csv').set_index('train_id')
    segments=pd.read_csv(base/'segments.csv');tracks=pd.read_csv(base/'station_tracks.csv').groupby('station_id').size();limits=pd.read_csv(base/'line_speeds.csv').set_index('segment_id')
    data=[]
    for tid,group in stops.groupby('train_id'):
        ordered=list(group.sort_values('stop_order').itertuples());svc=services.loc[tid]
        for a,b in zip(ordered,ordered[1:]):
            segment=segments[((segments.from_station_id==a.station_id)&(segments.to_station_id==b.station_id))|((segments.from_station_id==b.station_id)&(segments.to_station_id==a.station_id))].iloc[0]
            target=(pd.Timestamp(b.scheduled_arrival)-pd.Timestamp(a.scheduled_departure)).total_seconds()/60
            data.append(dict(train_id=tid,segment_id=segment.segment_id,target=target,distance_km=float(segment.demo_distance_km),
                speed_limit_kmh=float(limits.loc[segment.segment_id].demo_limit_kmh),category_code=CATEGORIES[svc.category],
                destination_tracks=int(tracks[b.station_id]),direction=1 if svc.direction=='forward' else -1))
    return pd.DataFrame(data)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--data-dir',type=Path,default=ROOT/'data/kz-upload/data/KZ');args=parser.parse_args()
    data=rows(args.data_dir);ids=data.train_id.to_numpy();x=data[FEATURES];y=data.target
    trainval,test=next(GroupShuffleSplit(n_splits=1,test_size=.25,random_state=42).split(x,y,ids))
    aa,bb=next(GroupShuffleSplit(n_splits=1,test_size=.25,random_state=43).split(x.iloc[trainval],y.iloc[trainval],ids[trainval]));train,val=trainval[aa],trainval[bb]
    candidates=[]
    for leaves in (7,15):
        model=lgb.LGBMRegressor(n_estimators=220,num_leaves=leaves,min_child_samples=3,learning_rate=.06,verbosity=-1,n_jobs=1,random_state=42)
        model.fit(x.iloc[train],y.iloc[train]);candidates.append((mean_absolute_error(y.iloc[val],model.predict(x.iloc[val])),model))
    val_mae,model=min(candidates,key=lambda pair:pair[0]);pred=model.predict(x.iloc[test]);mae=mean_absolute_error(y.iloc[test],pred)
    baseline=mean_absolute_error(y.iloc[test],x.iloc[test].distance_km/x.iloc[test].speed_limit_kmh*60)
    lookup=data.iloc[train].groupby('segment_id').target.median()
    lookup_mae=mean_absolute_error(y.iloc[test],data.iloc[test].segment_id.map(lookup).fillna(y.iloc[train].median()))
    # Separate leave-one-segment-out diagnostic shows memorization/generalization limits.
    held=data.segment_id=='SHU-ALM';out_model=lgb.LGBMRegressor(**model.get_params());out_model.fit(x[~held],y[~held]);unseen=mean_absolute_error(y[held],out_model.predict(x[held]))
    out=SERVICE/'models/kz_schedule_demo';out.mkdir(exist_ok=True)
    model.booster_.save_model(str(out/'model.txt'))
    metadata=dict(model_version='kz-synthetic-schedule-v1',target='scheduled_segment_travel_min',synthetic_only=True,features=FEATURES,
        rows=dict(total=len(data),train=len(train),validation=len(val),test=len(test)),trains={name:sorted(set(ids[index])) for name,index in [('train',train),('validation',val),('test',test)]},
        metrics=dict(mae_min=float(mae),rmse_min=float(np.sqrt(mean_squared_error(y.iloc[test],pred))),validation_mae_min=float(val_mae),
            distance_over_limit_baseline_mae_min=float(baseline),unseen_shu_almaty_mae_min=float(unseen)),
        limitations=['All labels are synthetic scheduled times, not actual journeys or delays.','Service split shares route segments. A low test error can reflect timetable memorization.','Cannot measure actual Kazakhstan delay or conflict accuracy.','Not a replacement for the PKP delay model.'],
        files=[dict(path=f.name,sha256=hashlib.sha256(f.read_bytes()).hexdigest()) for f in args.data_dir.glob('*.csv')])
    metadata['metrics']['segment_median_baseline_mae_min']=float(lookup_mae)
    metadata['accepted_for_operational_use']=False
    archive=ROOT.parent/'kz_kokshetau_astana_almaty_data.zip'
    if archive.exists():metadata['archive_sha256']=hashlib.sha256(archive.read_bytes()).hexdigest()
    (out/'metrics.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
    (SERVICE/'reports/kz_schedule_training.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:metadata[k] for k in ('model_version','target','rows','metrics')},indent=2))

if __name__=='__main__':main()
