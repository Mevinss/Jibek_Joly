const clamp = (v,a,b) => Math.max(a,Math.min(b,v));
export function formatClock(value){const ms=typeof value==='number'?value:Date.parse(value);return Number.isFinite(ms)?new Date(ms).toLocaleTimeString('ru-RU',{timeZone:'Asia/Qyzylorda',hour:'2-digit',minute:'2-digit',second:'2-digit'}):'—';}

export function acceptFrame(previous, next) {
  if (!next || !Number.isFinite(next.elapsed_s) || next.elapsed_s < 0 || !Number.isFinite(Date.parse(next.ts))) return false;
  const trains=next.state?.trains, display=next.display;
  if (!Array.isArray(trains)||!trains.length||!Array.isArray(display)||display.length!==trains.length||!Array.isArray(next.state?.infra?.blocks)) return false;
  const ids=new Set();
  for (const t of trains) {
    if(typeof t.train_id!=='string'||!t.train_id.startsWith('SIM-')||ids.has(t.train_id)||![t.speed,t.delay_s,t.position?.km].every(Number.isFinite)||t.speed<0||t.delay_s<0||t.position.km<0)return false;
    ids.add(t.train_id);
  }
  const shown=new Set();
  for(const d of display){if(!ids.has(d.train_id)||shown.has(d.train_id)||!Number.isFinite(d.corridor_km)||![1,-1].includes(d.direction))return false;shown.add(d.train_id);}
  return !previous || next.elapsed_s>previous.elapsed_s;
}

export function scheduledKm(geo, id, ms) {
  const stations=Object.fromEntries(geo.stations.map(s=>[s.id,s.km]));
  const points=geo.timetable.filter(r=>r.train_id===id).flatMap(r=>['scheduled_arrival','scheduled_departure'].filter(k=>r[k]).map(k=>[Date.parse(r[k]),stations[r.station_id]])).filter(p=>p.every(Number.isFinite)).sort((a,b)=>a[0]-b[0]);
  if(!points.length)return null;
  if(ms<=points[0][0])return points[0][1];
  for(let i=1;i<points.length;i++)if(ms<=points[i][0]){const [a,x]=points[i-1],[b,y]=points[i];return x+(y-x)*(ms-a)/(b-a||1);}
  return points.at(-1)[1];
}

export function diagramData(geo,snapshot,history,selected,section='north') {
  const boundary=geo.stations.find(s=>s.id==='AST').km;
  const stations=geo.stations.filter(s=>section==='all'||(section==='north'?s.km<=boundary:s.km>=boundary));
  const height=Math.max(390,(stations.length-1)*48), first=stations[0].km, last=stations.at(-1).km;
  const y=km=>{
    if(km<=first)return 34;if(km>=last)return height-30;
    const i=stations.findIndex((s,j)=>j<stations.length-1&&km>=s.km&&km<=stations[j+1].km);
    return 34+(i+(km-stations[i].km)/(stations[i+1].km-stations[i].km))*(height-64)/(stations.length-1);
  };
  const now=Date.parse(snapshot.ts), start=now-15*60000, end=now+30*60000;
  const x=ms=>170+(ms-start)/(end-start)*760;
  const trains=[];
  for(const t of snapshot.state.trains){
    const d=snapshot.display.find(d=>d.train_id===t.train_id);
    if(d.corridor_km<first||d.corridor_km>last)continue;
    const ends=[d.origin,d.destination].map(id=>geo.stations.find(s=>s.id===id)?.km).filter(Number.isFinite);
    if(ends.length!==2)continue;
    const planned=Array.from({length:91},(_,i)=>{const ms=start+(end-start)*i/90;return {ms,km:scheduledKm(geo,t.train_id,ms)};}).filter(p=>p.km!==null);
    const observed=history.filter(h=>Date.parse(h.ts)>=start&&Date.parse(h.ts)<=now).map(h=>({ms:Date.parse(h.ts),km:h.display.find(r=>r.train_id===t.train_id)?.corridor_km})).filter(p=>Number.isFinite(p.km));
    const terminal=d.direction===1?Math.max(...ends):Math.min(...ends);
    const arrival=t.speed>0?now+Math.abs(terminal-d.corridor_km)/t.speed*3600000:Infinity;
    const forecast=[{ms:now,km:d.corridor_km}];
    if(arrival>now&&arrival<end)forecast.push({ms:arrival,km:terminal});
    forecast.push({ms:end,km:clamp(d.corridor_km+d.direction*t.speed*.5,Math.min(...ends),Math.max(...ends))});
    trains.push({id:t.train_id,selected:t.train_id===selected,freight:t.type==='груз',planned,observed,forecast,current:{ms:now,km:d.corridor_km}});
  }
  return {stations:stations.map(s=>({...s,y:y(s.km)})),trains,x,y,height,start,end,now};
}

export function speedAdvice(snapshot,geo,id){
  const train=snapshot.state.trains.find(t=>t.train_id===id),d=snapshot.display.find(t=>t.train_id===id);
  if(!train||!d)return {status:'UNKNOWN',recommendedKmh:null};
  const next=geo.stations.find(s=>s.id===d.next_station),now=Date.parse(snapshot.ts),target=Date.parse(d.scheduled_arrival);
  const distance=d.distance_to_station_km;
  const lo=Math.min(d.corridor_km,next?.km),hi=Math.max(d.corridor_km,next?.km);
  const blocks=snapshot.state.infra.blocks.filter(b=>b.id===train.position.block_id||geo.features.some(f=>f.properties.id===b.id&&f.properties.start_km<hi&&f.properties.end_km>lo));
  const caps=blocks.map(b=>b.speed_limit).filter(v=>Number.isFinite(v)&&v>0),capKmh=caps.length?Math.min(...caps):null;
  const base={recommendedKmh:null,currentKmh:train.speed,distanceKm:distance,capKmh,target:d.scheduled_arrival,stationId:d.next_station};
  if(d.held||blocks.some(b=>b.closed))return {...base,status:'HOLD'};
  if(!Number.isFinite(distance)||distance<0||!capKmh||!Number.isFinite(target))return {...base,status:'UNKNOWN'};
  if(distance<.05)return {...base,status:'ARRIVED'};
  const remaining=(target-now)/3600000;
  if(remaining<=0)return {...base,status:'LATE'};
  const required=distance/remaining;
  if(required>capKmh)return {...base,status:'UNREACHABLE'};
  if(required<5)return {...base,status:'HOLD'};
  return {...base,status:'AVAILABLE',recommendedKmh:required,points:[{distanceKm:0,speedKmh:required},{distanceKm:distance,speedKmh:required}]};
}
