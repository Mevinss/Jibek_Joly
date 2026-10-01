"""Export main's Kazakhstan fixture. PKP geography is never used in the UI."""
import csv
import json
import hashlib
import argparse
from pathlib import Path
from ..settings import ROOT, SERVICE

COORDINATES = {
 'KOK': (69.4233693,53.288608551025,23460), 'BOR': (70.1809032,52.921070098877,21619),
 'AKK': (70.9394568,52.014572143555,21561), 'AST': (71.4091158,51.195598602295,23469),
 'KAR': (73.094763,49.793106079102,23475), 'AKD': (72.8558257,48.263378143311,21708),
 'SAR': (73.6060678,46.119464874268,21380), 'SHU': (73.7606205,43.601261138916,21318),
 'ALM': (76.9393719,43.273998260498,21331)}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--data-dir',type=Path,default=ROOT/'data/kz-upload/data/KZ')
    base=parser.parse_args().data_dir
    def read(name):
        with (base/(name+'.csv')).open(encoding='utf-8-sig') as f: return list(csv.DictReader(f))
    stations, features = [], []
    tracks=read('station_tracks'); segments=read('segments'); blocks=read('blocks'); speeds=read('line_speeds')
    distance=0.
    for i,s in enumerate(read('stations')):
        if i: distance+=float(segments[i-1]['demo_distance_km'])
        x,y,source=COORDINATES[s['station_id']]
        stations.append(dict(id=s['station_id'],name=s['name_kk'],km=distance,coordinates=[x,y],country='KZ',
            tracks=sum(t['station_id']==s['station_id'] for t in tracks),coordinate_source=f'https://railwayz.info/photolines/station/{source}'))
    station_map={s['id']:s for s in stations}
    for segment in segments:
        a,b=station_map[segment['from_station_id']],station_map[segment['to_station_id']]
        subset=[b for b in blocks if b['segment_id']==segment['segment_id']]
        for j,block in enumerate(subset):
            f0,f1=j/len(subset),(j+1)/len(subset)
            coords=[[a['coordinates'][k]+(b['coordinates'][k]-a['coordinates'][k])*f for k in range(2)] for f in (f0,f1)]
            start=a['km']+(b['km']-a['km'])*f0;end=a['km']+(b['km']-a['km'])*f1
            features.append(dict(type='Feature',geometry=dict(type='LineString',coordinates=coords),properties=dict(
                id=block['block_id'],segment_id=segment['segment_id'],from_station=a['id'],to_station=b['id'],start_km=start,end_km=end,
                length_km=end-start,tracks=1,station_tracks=b['tracks'],direction=1,
                speed_limit=int(next(s['demo_limit_kmh'] for s in speeds if s['segment_id']==segment['segment_id'])),
                min_technical_time_min=float(segment['demo_travel_min'])/len(subset),training_rows=0)))
    files=[dict(path=f.name,sha256=hashlib.sha256(f.read_bytes()).hexdigest()) for f in base.glob('*.csv')]
    result=dict(type='FeatureCollection',features=features,stations=stations,length_km=distance,name='Көкшетау-1 — Астана-1 — Алматы-2',
        country='KZ',geometry_accuracy='Straight station connections; synthetic block lengths, not surveyed tracks.',
        provenance=dict(commit=json.loads((ROOT/'data/main-source/snapshot.json').read_text())['commit'],files=files,
            coordinate_attribution='Railwayz.info, individual station links. Non-commercial demo with attribution.'),
        services=read('train_services'),timetable=read('run_stops'),source_notice='KZ synthetic fixture; all SIM trains and times are simulated. PKP-trained ML transfer is unvalidated.')
    archive=ROOT.parent/'kz_kokshetau_astana_almaty_data.zip'
    if archive.exists():result['provenance']['archive_sha256']=hashlib.sha256(archive.read_bytes()).hexdigest()
    (SERVICE/'demo/corridor.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'Kazakhstan: {len(stations)} stations, {len(features)} blocks, {len(result["services"])} services')


if __name__=='__main__':main()
