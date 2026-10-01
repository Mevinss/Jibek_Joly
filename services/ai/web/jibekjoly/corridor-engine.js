import {stationArrivals} from './arrivals.js';
import {syntheticData} from './synthetic-data.js';
import {ecoAdvice} from './eco-model.js';
import {waveTimetable} from './timetable-data.js';
import {recordFrame} from './journey.js';
import {quality,getQualityConfig} from './quality.js';
export const nodes=[
{name:'Көкшетау',x:-80,z:-5},{name:'Бурабай',x:-60,z:4},{name:'Ақкөл',x:-40,z:-2},{name:'Астана',x:-19,z:8},{name:'Қарағанды',x:4,z:2},{name:'Мойынты',x:25,z:-8},{name:'Шу',x:47,z:-3},{name:'Алматы-1',x:67,z:7},{name:'Алматы-2',x:85,z:0}];
export const durations=[9,11,8,14,12,10,9,7];
export const trainDefs=[
{id:'SIM-TAL-021',name:['Скоростной · Көкшетау → Алматы','Жүрдек · Көкшетау → Алматы'],type:0,color:'#36d9bc',weight:3,people:320,start:0,dir:1},
{id:'SIM-TAL-022',name:['Скоростной · Алматы → Көкшетау','Жүрдек · Алматы → Көкшетау'],type:0,color:'#69b6ff',weight:3,people:300,start:8,dir:-1},
{id:'SIM-PAS-043',name:['Пассажирский · Бурабай → Алматы','Жолаушы · Бурабай → Алматы'],type:1,color:'#bf9bff',weight:2,people:480,start:1,dir:1},
{id:'SIM-PAS-044',name:['Пассажирский · Алматы → Көкшетау','Жолаушы · Алматы → Көкшетау'],type:1,color:'#ff91b9',weight:2,people:420,start:7,dir:-1},
{id:'SIM-FRT-208',name:['Грузовой · Астана → Алматы','Жүк · Астана → Алматы'],type:2,color:'#f5b956',weight:1,people:0,start:3,dir:1},
{id:'SIM-FRT-209',name:['Грузовой · Мойынты → Көкшетау','Жүк · Мойынты → Көкшетау'],type:2,color:'#a0c774',weight:1,people:0,start:5,dir:-1}];
export const incidentDefs=[
{title:['Отказ сигнала у Ақкөл','Ақкөл маңындағы сигнал ақауы'],description:['Основной путь закрыт. Поезда останавливаются перед сигналом. На участке доступен резервный путь.','Негізгі жол жабық. Пойыздар сигнал алдында тоқтайды. Учаскеде резервтік жол бар.'],type:'closure',block:2,time:6,length:22},
{title:['Ограничение скорости у Қарағанды','Қарағанды маңындағы жылдамдық шектеуі'],description:['На основном пути действует 40 км/ч. Очередь растёт. Выберите очерёдность или направьте поезда через резерв.','Негізгі жолда 40 км/сағ шектеуі бар. Кезек өсуде. Өткізу кезегін таңдаңыз немесе резервке бағыттаңыз.'],type:'slow',block:4,time:18,length:24},
{title:['Заблокирован подход к Алматы','Алматыға кіреберіс жабық'],description:['Основной путь на подходе занят ремонтными работами. Откройте предусмотренный моделью резерв или дождитесь освобождения.','Кіреберістегі негізгі жолда жөндеу жүріп жатыр. Модельдегі резервті ашыңыз немесе босауын күтіңіз.'],type:'closure',block:6,time:32,length:20},
{title:['Неисправность на загруженном участке','Жүктемесі жоғары учаскедегі ақау'],description:['Новый сбой возникает на пути действующего поезда. Выберите ремонт и приоритет, исходя из текущего положения составов.','Қозғалыстағы пойыз жолында жаңа ақау пайда болды. Қазіргі жағдайға қарай жөндеу мен басымдықты таңдаңыз.'],type:'closure',block:3,time:45,length:20,dynamic:true}];
for(const t of trainDefs)Object.assign(t,syntheticData.trains.find(row=>row.id===t.id));
export const speedFactor=t=>60/(t.maxSpeedKmh||(t.type===0?60:t.type===1?60/1.13:60/1.38));
export function makeWorld({scenario=-1,auto=false,events=true,recordJourney=true,eco=auto,mode='crowded',useTimetable=true}={}){
 const wave=mode==='wave',signals=wave?syntheticData.green_wave.known_signals:syntheticData.known_signals;
 const w={tripId:crypto.randomUUID(),timeline:[],recordJourney,config:getQualityConfig(),time:0,auto,eco,mode,scenario,events,syntheticPackage:syntheticData.package_id,signals:structuredClone(signals),manualRed:{},actionHistory:[],trains:[],blocks:durations.map((d,i)=>({i,main:null,reserve:null,freeAt:0,reserveFreeAt:0,reserveOpen:wave,preferred:null})),incidents:[],log:[],history:[],triggered:[],actions:0,done:false,initialDone:false};
 w.initialInput={scenario,auto,events,eco,mode};
 w.trains=trainDefs.map((d,i)=>{
  const def={...d,...(wave?syntheticData.green_wave.trains.find(t=>t.id===d.id):{})};
  const t={...def,index:i,node:def.start,segment:null,p:0,lane:wave&&def.dir<0?'reserve':'main',state:'ready',hold:false,wait:0,work:0,finished:null,delay:0,reason:'',stationPassages:{},passedSignals:[],energy:0,distance_work:0,fullStops:0,full_stop_avoided:0,actualSpeed:0,lastSpeed:0,signalViolations:0,movingSinceStop:false};
  t.plan=durations.reduce((n,x,k)=>n+((t.dir===1?k>=t.start:k<t.start)?x*speedFactor(t):0),0)+(t.releaseAt||0);
  if(t.initialProgress){const block=t.dir===1?t.node:t.node-1;t.segment=block;t.p=t.dir===1?t.initialProgress:1-t.initialProgress;t.state='running';t.actualSpeed=t.maxSpeedKmh*(t.lane==='reserve'?.8:1);w.blocks[block][t.lane]=t.id;t.plan-=durations[block]*speedFactor(t)*t.initialProgress;}
  t.lastSpeed=t.actualSpeed;
  if(wave&&useTimetable&&waveTimetable[t.id]){t.timetable=waveTimetable[t.id];t.plan=t.timetable.finish;}
  return t;
 });
 w.log.push({time:0,kind:'info',key:'start'});schedule(w);recordFrame(w,true);return w;
}
export function targetBlock(t){return t.segment!==null?t.segment:t.dir===1?t.node:t.node-1;}
export function incidentFor(w,block){return w.incidents.filter(x=>x.block===block&&x.until>w.time).sort((a,b)=>(b.type==='closure')-(a.type==='closure')||b.until-a.until)[0];}
export function signalState(w,block,dir=1,lane=null,owner=null){
 const b=w.blocks[block];if(!b)return {id:null,aspect:'green',reason:'terminal',opensAt:null,block,dir};
 const track=lane||(w.mode==='wave'&&dir<0?'reserve':'main'),key=`${block}:${dir}`,inc=incidentFor(w,block);
 const window=Math.max(0,...(w.signals||[]).filter(s=>s.block===block&&(s.dir===undefined||s.dir===dir)).map(s=>s.opensAt));
 const headway=track==='main'?b.freeAt:b.reserveFreeAt;
 let opensAt=Math.max(window,headway||0),reason=opensAt>w.time+1e-7?(window>w.time?'window':'headway'):'clear';
 if(track==='main'&&inc?.type==='closure'){opensAt=Math.max(opensAt,inc.until);reason='incident';}
 if(b[track]&&b[track]!==owner){opensAt=null;reason='occupied';}
 if(w.manualRed?.[key]){opensAt=null;reason='manual';}
 return {id:`SIM-S-${String(block+1).padStart(2,'0')}${dir>0?'E':'W'}`,block,dir,lane:track,aspect:opensAt===null||opensAt>w.time+1e-7?'red':'green',reason,opensAt};
}
export function trigger(w,index,now=w.time){if(w.triggered.includes(index))return null;const d=incidentDefs[index];let block=d.block;if(d.dynamic&&w.scenario<0){const active=w.trains.filter(t=>t.finished===null);const t=active.find(t=>t.type===2&&t.segment!==null)||active.find(t=>t.segment!==null)||active[0];if(t)block=Math.max(0,Math.min(7,targetBlock(t)));}
 const event={...d,index,time:now,block,until:now+d.length,repair:false,managed:false};w.incidents.push(event);w.triggered.push(index);w.log.unshift({time:now,kind:'alert',key:'incident',index,block});return event;}
export function action(w,kind,id=null,blockId=null,dir=1){
 const tr=w.trains.find(t=>t.id===id),active=blockId!==null?incidentFor(w,blockId):[...w.incidents].reverse().find(x=>x.until>w.time),block=w.blocks[blockId??active?.block??(tr?targetBlock(tr):-1)];
 if(kind==='signal'){if(!block)return false;const key=`${block.i}:${dir}`;w.manualRed[key]=!w.manualRed[key];w.log.unshift({time:w.time,kind:'action',key:'signal',block:block.i,dir});}
 else if(kind==='eco'){w.eco=!w.eco;w.log.unshift({time:w.time,kind:'action',key:'eco'});}
 else if(kind==='repair'){if(!active||active.repair)return false;active.until=Math.min(active.until,w.time+6);active.repair=true;active.managed=true;w.log.unshift({time:w.time,kind:'action',key:'repair',block:active.block});}
 else if(kind==='reserve'){if(!block||block.reserveOpen)return false;block.reserveOpen=true;if(active)active.managed=true;w.log.unshift({time:w.time,kind:'action',key:'reserve',block:block.i});}
 else if(kind==='priority'){if(!tr||tr.finished!==null)return false;const next=tr.segment===null?targetBlock(tr):(tr.dir===1?tr.segment+1:tr.segment-1);if(next<0||next>7)return false;w.blocks[next].preferred=tr.id;if(active)active.managed=true;w.log.unshift({time:w.time,kind:'action',key:'priority',id:tr.id,block:next});}
 else if(kind==='hold'){if(!tr||tr.finished!==null)return false;tr.hold=!tr.hold;w.log.unshift({time:w.time,kind:'action',key:tr.hold?'hold':'release',id:tr.id});}
 else if(kind==='wait'){if(!active)return false;active.managed=true;w.log.unshift({time:w.time,kind:'action',key:'wait',block:active.block});}
 else return false;
 w.actionHistory ||= [];w.actionHistory.push({time:w.time,kind,id,blockId,dir});w.actions++;recordFrame(w,true);return true;
}
function schedule(w){
 const candidates=w.trains.filter(t=>t.segment===null&&t.finished===null&&!t.hold&&w.time>=(t.releaseAt||0));
 candidates.sort((a,b)=>{const ba=w.blocks[targetBlock(a)],bb=w.blocks[targetBlock(b)];return (bb?.preferred===b.id?1:0)-(ba?.preferred===a.id?1:0)||(w.policy==='freight'?a.weight-b.weight:w.policy==='delay'?b.delay-a.delay:(w.auto||w.policy==='passenger')?(w.config?.priorities[b.type]||b.weight)-(w.config?.priorities[a.type]||a.weight):0)||b.wait-a.wait||a.index-b.index;});
 for(const t of candidates){
  const n=targetBlock(t);if(n<0||n>=8){finish(w,t);continue;}
  const b=w.blocks[n],inc=incidentFor(w,n);let lane=w.mode==='wave'?(t.dir<0?'reserve':'main'):null;
  if(lane&&signalState(w,n,t.dir,lane).aspect!=='green')lane=null;
  if(w.mode!=='wave'){
   if(signalState(w,n,t.dir,'main').aspect==='green')lane='main';
   if(b.reserveOpen&&signalState(w,n,t.dir,'reserve').aspect==='green'&&(!lane||inc?.type==='slow'))lane='reserve';
  }
  if(lane){
   const gate=signalState(w,n,t.dir,lane);t.passedSignals.push({id:gate.id,block:n,dir:t.dir,time:w.time,aspect:gate.aspect,speed:t.actualSpeed});
   if(t.ecoArrivalPending?.block===n&&t.actualSpeed>5&&t.fullStops===t.ecoArrivalPending.stops)t.full_stop_avoided++;
   t.ecoArrivalPending=null;b[lane]=t.id;t.segment=n;t.p=t.dir===1?0:1;t.lane=lane;t.state='running';
   if(b.preferred===t.id)b.preferred=null;w.log.unshift({time:w.time,kind:'move',key:'enter',id:t.id,block:n,lane});
  }else t.state=t.hold?'held':'queue';
 }
}
function finish(w,t){t.finished=w.time;t.state='done';t.actualSpeed=0;w.log.unshift({time:w.time,kind:'good',key:'finish',id:t.id});}
const acceleration=t=>t.type===2?.1:.25,deceleration=t=>t.type===2?.12:.3;
export function speedCap(w,t){const inc=incidentFor(w,t.segment);return t.lane==='reserve'?t.maxSpeedKmh*.8:inc?.type==='slow'?Math.min(t.maxSpeedKmh,40):t.maxSpeedKmh;}
export function nextSignal(w,t){const n=t.segment===null?targetBlock(t):t.dir>0?t.segment+1:t.segment-1;return signalState(w,n,t.dir,w.mode==='wave'?(t.dir<0?'reserve':'main'):t.lane);}
export function nextRelease(w,t){if(t.segment===null||t.finished!==null)return null;const s=nextSignal(w,t);return s.aspect==='red'&&s.opensAt!==null&&s.opensAt>w.time?s.opensAt:null;}
export function approach(w,t){
 const distance=t.segment===null?0:durations[t.segment]*(t.dir===1?1-t.p:t.p),cap=speedCap(w,t),inc=t.segment===null?null:incidentFor(w,t.segment);
 if(inc?.type==='closure'&&t.lane==='main')return {...ecoAdvice({distanceKm:distance,currentKmh:0,capKmh:cap,nowMin:w.time,openMin:inc.until,massTons:t.massTons}),status:'BLOCKED'};
 return ecoAdvice({distanceKm:distance,currentKmh:t.actualSpeed||0,capKmh:cap,nowMin:w.time,openMin:nextRelease(w,t),massTons:t.massTons});
}
function expectedTime(t){
 const samples=t.timetable?.progress;if(!samples?.length)return (t.releaseAt||0)+t.work;
 const x=t.distance_work;let left=samples[0];
 for(const right of samples){if(right[1]<=x+1e-7){left=right;continue;}const span=right[1]-left[1];return span>0?left[0]+(right[0]-left[0])*Math.max(0,x-left[1])/span:left[0];}
 return samples.at(-1)[0];
}
export function step(w,delta){
 if(w.done)return [];const events=[];let remaining=delta;
 while(remaining>1e-9){
  const dt=Math.min(.05,remaining),start=w.time;remaining-=dt;w.time+=dt;
  if(w.events)for(let i=0;i<4;i++){if(w.scenario>=0&&i!==w.scenario)continue;const due=w.scenario>=0?6:incidentDefs[i].time;if(w.time+1e-6>=due&&!w.triggered.includes(i))events.push(trigger(w,i,due));}
  for(const e of w.incidents){if(!e.cleared&&w.time>=e.until){e.cleared=true;w.log.unshift({time:w.time,kind:'good',key:'clear',block:e.block});}if(w.auto&&!e.managed&&w.time>=e.time+1){action(w,'repair',null,e.block);if(w.mode!=='wave')action(w,'reserve',null,e.block);}}
  for(const t of w.trains){
   if(t.finished!==null)continue;const oldSpeed=t.actualSpeed||0;
   if(t.segment!==null){
    const b=w.blocks[t.segment],inc=incidentFor(w,t.segment),cap=speedCap(w,t),distance=durations[t.segment]*(t.dir>0?1-t.p:t.p),gate=nextSignal(w,t);
    const eco=w.eco&&t.type===2?approach({...w,time:start},t):null;
    let target=eco?.status==='AVAILABLE'?Math.min(cap,eco.cruise_speed_kmh):cap;
    if(eco?.full_stop_avoided)t.ecoArrivalPending={block:t.dir>0?t.segment+1:t.segment-1,stops:t.fullStops};
    const closed=inc?.type==='closure'&&t.lane==='main';
    if(closed)target=0;
    else if(gate.aspect==='red'&&eco?.status!=='AVAILABLE'){
     const brake=deceleration(t),seconds=dt*60;
     target=Math.min(target,Math.max(0,Math.sqrt(2*brake*distance*1000+(brake*seconds/2)**2)-brake*seconds/2)*3.6);
    }
    const rate=target<oldSpeed?deceleration(t):acceleration(t),change=rate*3.6*dt*60;
    let v=Math.max(0,oldSpeed+Math.max(-change,Math.min(change,target-oldSpeed)));
    let moved=Math.min(distance,(oldSpeed+v)/2*dt/60);
    if(closed){moved=0;v=0;t.state='blocked';t.wait+=dt;}
    else t.state='running';
    t.ecoAdvice=eco;t.actualSpeed=v;t.p=Math.max(0,Math.min(1,t.p+t.dir*moved/durations[t.segment]));
    t.energy+=moved*(.15+.85*((oldSpeed+v)/2/t.maxSpeedKmh)**2)*(t.massTons/1000)+3*Math.max(0,v*v-oldSpeed*oldSpeed)/t.maxSpeedKmh**2*(t.massTons/1000);
    t.distance_work+=moved;t.work+=moved*speedFactor(t);
    if(distance-moved<1e-5&&(!closed)){
     t.node=t.dir>0?t.segment+1:t.segment;t.stationPassages[t.node]=w.time;b[t.lane]=null;
     if(t.lane==='main')b.freeAt=w.time+1;else b.reserveFreeAt=w.time+1;
     t.segment=null;t.state='ready';
     if(t.dir>0?t.node===8:t.node===0)finish(w,t);
     else if(nextSignal(w,t).aspect==='red'||t.hold)t.actualSpeed=0;
    }
   }else{
    t.actualSpeed=0;if(w.time>=(t.releaseAt||0)){t.wait+=dt;t.state=t.hold?'held':'queue';}else t.state='ready';
   }
   if(t.actualSpeed<.1&&w.time>=(t.releaseAt||0))t.energy+=dt*.05*(t.massTons/1000);
   if(t.actualSpeed>5)t.movingSinceStop=true;
   if(t.movingSinceStop&&t.actualSpeed<.1&&t.finished===null){t.fullStops++;t.movingSinceStop=false;}
   t.lastSpeed=t.actualSpeed;t.energy_proxy_units=t.energy;t.fuel_liters=t.energy*syntheticData.demo_physics.fuel_liters_per_proxy_unit;
   t.delay=Math.max(0,(t.finished??w.time)-(t.finished!==null?t.plan:expectedTime(t))-.15);
   t.recommended_speed_profile=t.ecoAdvice?.recommended_speed_profile||[];t.target_arrival_time=t.ecoAdvice?.target_arrival_time||null;
  }
  schedule(w);recordFrame(w);
  if(w.history.length===0||w.time-w.history.at(-1).time>=.99)w.history.push({time:w.time,...metrics(w)});
  if(w.trains.every(t=>t.finished!==null)){w.done=true;recordFrame(w,true);break;}
 }
 if(w.log.length>180)w.log.length=180;return events.filter(Boolean);
}
export function metrics(w){const total=w.trains.reduce((n,t)=>n+t.delay,0);return {total,weighted:w.trains.reduce((n,t)=>n+t.delay*(w.config?.priorities?.[t.type]??t.weight),0),avg:total/w.trains.length,waiting:w.trains.filter(t=>['queue','blocked','held'].includes(t.state)).length,finished:w.trains.filter(t=>t.finished!==null).length,index:quality(w).index,passengerMinutes:w.trains.reduce((n,t)=>n+t.delay*t.people,0)};}
export function position(t){
 if(t.segment===null){const n=nodes[t.node];if(['queue','held'].includes(t.state)){const other=nodes[Math.max(0,Math.min(8,t.node+t.dir))];return {x:n.x,z:n.z+(t.lane==='reserve'?-4:0),angle:Math.atan2(other.z-n.z,other.x-n.x)};}return {x:n.x+(t.index%3-1)*3,z:n.z+4+(t.index%2)*3,angle:0};}
 const a=nodes[t.segment],b=nodes[t.segment+1],p=t.p,zOffset=t.lane==='reserve'?-4:0;return {x:a.x+(b.x-a.x)*p,z:a.z+(b.z-a.z)*p+zOffset,angle:Math.atan2(b.z-a.z,b.x-a.x)+(t.dir<0?Math.PI:0)};
}
export function eta(w,t){return t.finished??stationArrivals(w,t.dir>0?nodes.length-1:0).find(r=>r.id===t.id)?.arrival??null;}
export function replay(time,{scenario=-1,auto=false,eco=auto,mode='crowded'}={}){const w=makeWorld({scenario,auto,eco,mode});step(w,time);return w;}
export function assertWorld(w){for(const b of w.blocks)for(const lane of ['main','reserve']){const trains=w.trains.filter(t=>t.segment===b.i&&t.lane===lane);if(trains.length>1)throw Error('Block overlap');if((trains[0]?.id||null)!==b[lane])throw Error('Occupancy mismatch');}for(const t of w.trains)if(!Number.isFinite(t.delay)||t.p<0||t.p>1||t.actualSpeed<0)throw Error('Invalid train state');}
