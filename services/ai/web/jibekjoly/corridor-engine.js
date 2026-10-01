import {stationArrivals} from './arrivals.js';
import {syntheticData} from './synthetic-data.js';
import {ecoAdvice} from './eco-model.js';
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
export function makeWorld({scenario=-1,auto=false,events=true,recordJourney=true,eco=auto}={}){
 const w={tripId:crypto.randomUUID(),timeline:[],recordJourney,config:getQualityConfig(),time:0,auto,eco,scenario,events,syntheticPackage:syntheticData.package_id,signals:structuredClone(syntheticData.known_signals),trains:[],blocks:durations.map((d,i)=>({i,main:null,reserve:null,freeAt:0,reserveFreeAt:0,reserveOpen:false,preferred:null})),incidents:[],log:[],history:[],triggered:[],actions:0,done:false,initialDone:false};
 w.trains=trainDefs.map((d,i)=>({...d,index:i,node:d.start,segment:null,p:0,lane:'main',state:'ready',hold:false,wait:0,work:0,finished:null,delay:0,reason:'',plan:durations.reduce((n,x,k)=>n+((d.dir===1?k>=d.start:k<d.start)?x*speedFactor(d):0),0)}));
 for(const t of w.trains){t.stationPassages={};t.massTons ||= 1000;t.energy=0;t.distance_work=0;t.fullStops=0;t.full_stop_avoided=0;if(t.initialProgress){const block=t.dir===1?t.node:t.node-1;t.segment=block;t.p=t.dir===1?t.initialProgress:1-t.initialProgress;t.state='running';t.actualSpeed=t.maxSpeedKmh;w.blocks[block].main=t.id;t.plan-=durations[block]*speedFactor(t)*t.initialProgress;}t.plan+=t.releaseAt||0;t.lastSpeed=t.actualSpeed||0;}
 w.log.push({time:0,kind:'info',key:'start'});recordFrame(w,true);step(w,.001);return w;
}
export function targetBlock(t){return t.segment!==null?t.segment:t.dir===1?t.node:t.node-1;}
export function incidentFor(w,block){return w.incidents.filter(x=>x.block===block&&x.until>w.time).sort((a,b)=>(b.type==='closure')-(a.type==='closure')||b.until-a.until)[0]}
export function trigger(w,index,now=w.time){if(w.triggered.includes(index))return null;const d=incidentDefs[index];let block=d.block;if(d.dynamic&&w.scenario<0){const active=w.trains.filter(t=>t.finished===null);const t=active.find(t=>t.type===2&&t.segment!==null)||active.find(t=>t.segment!==null)||active[0];if(t)block=Math.max(0,Math.min(7,targetBlock(t)));}
 const event={...d,index,time:now,block,until:now+d.length,repair:false,managed:false};w.incidents.push(event);w.triggered.push(index);w.log.unshift({time:now,kind:'alert',key:'incident',index,block});return event;}
export function action(w,kind,id=null,blockId=null){const tr=w.trains.find(t=>t.id===id);const active=blockId!==null?incidentFor(w,blockId):[...w.incidents].reverse().find(x=>x.until>w.time);const block=w.blocks[blockId??active?.block??(tr?targetBlock(tr):-1)];
 if(kind==='eco'){w.eco=!w.eco;w.log.unshift({time:w.time,kind:'action',key:'eco'});}
 else if(kind==='repair'){if(!active||active.repair)return false;active.until=Math.min(active.until,w.time+6);active.repair=true;active.managed=true;w.log.unshift({time:w.time,kind:'action',key:'repair',block:active.block});}
 else if(kind==='reserve'){if(!block||block.reserveOpen)return false;block.reserveOpen=true;if(active)active.managed=true;w.log.unshift({time:w.time,kind:'action',key:'reserve',block:block.i});}
 else if(kind==='priority'){if(!tr||tr.finished!==null)return false;const next=tr.segment===null?targetBlock(tr):(tr.dir===1?tr.segment+1:tr.segment-1);if(next<0||next>7)return false;w.blocks[next].preferred=tr.id;if(active)active.managed=true;w.log.unshift({time:w.time,kind:'action',key:'priority',id:tr.id,block:next});}
 else if(kind==='hold'){if(!tr||tr.finished!==null)return false;tr.hold=!tr.hold;w.log.unshift({time:w.time,kind:'action',key:tr.hold?'hold':'release',id:tr.id});}
 else if(kind==='wait'){if(!active)return false;active.managed=true;w.log.unshift({time:w.time,kind:'action',key:'wait',block:active.block});}
 else return false;w.actions++;recordFrame(w,true);return true;}
function schedule(w){let candidates=w.trains.filter(t=>t.segment===null&&t.finished===null&&!t.hold&&w.time>=(t.releaseAt||0));candidates.sort((a,b)=>{const ba=w.blocks[targetBlock(a)],bb=w.blocks[targetBlock(b)];return (bb?.preferred===b.id?1:0)-(ba?.preferred===a.id?1:0)||(w.policy==='freight'?a.weight-b.weight:w.policy==='delay'?b.delay-a.delay:(w.auto||w.policy==='passenger')?(w.config?.priorities[b.type]||b.weight)-(w.config?.priorities[a.type]||a.weight):0)||b.wait-a.wait||a.index-b.index;});
 for(const t of candidates){const n=targetBlock(t);if(n<0||n>=8){t.finished=w.time;t.state='done';continue;}const b=w.blocks[n],inc=incidentFor(w,n);let lane=null;
 if(b.main===null&&w.time>=b.freeAt&&(!inc||inc.type!=='closure')&&!w.signals?.some(s=>s.block===n&&s.opensAt>w.time))lane='main';
 if(b.reserveOpen&&b.reserve===null&&w.time>=b.reserveFreeAt&&(!lane||inc?.type==='slow'))lane='reserve';
 if(lane){b[lane]=t.id;t.segment=n;t.p=t.dir===1?0:1;t.lane=lane;t.state='running';if(t.ecoArrivalPending&&t.ecoArrivalPending.block===n&&t.ecoArrivalPending.predicted){if(t.wait-t.ecoArrivalPending.wait<.12)t.full_stop_avoided++;t.ecoArrivalPending=null;}if(b.preferred===t.id)b.preferred=null;w.log.unshift({time:w.time,kind:'move',key:'enter',id:t.id,block:n,lane});}else t.state='queue';}}
export function step(w,delta){if(w.done)return[];const events=[];let remaining=delta;while(remaining>1e-9){const dt=Math.min(.05,remaining);remaining-=dt;w.time+=dt;
 if(w.events){for(let i=0;i<4;i++){if(w.scenario>=0&&i!==w.scenario)continue;const due=w.scenario>=0?6:incidentDefs[i].time;if(w.time+1e-6>=due&&!w.triggered.includes(i))events.push(trigger(w,i,due));}}
 for(const e of w.incidents){if(!e.cleared&&w.time>=e.until){e.cleared=true;w.log.unshift({time:w.time,kind:'good',key:'clear',block:e.block});}if(w.auto&&!e.managed&&w.time>=e.time+1){action(w,'repair',null,e.block);action(w,'reserve',null,e.block);}}
 for(const t of w.trains){if(t.finished!==null)continue;if(t.segment!==null){const b=w.blocks[t.segment],inc=incidentFor(w,t.segment);if(t.lane==='main'&&inc?.type==='closure'){t.state='blocked';t.actualSpeed=0;t.energy=(t.energy||0)+dt*.05*(t.massTons/1000);t.wait+=dt;}else{t.state='running';const nominal=durations[t.segment]*speedFactor(t);const cap=t.lane==='reserve'?t.maxSpeedKmh*.8:inc?.type==='slow'?Math.min(t.maxSpeedKmh,40):t.maxSpeedKmh,eco=w.eco&&t.type===2?approach({...w,time:w.time-dt},t):null;const target=eco?.status==='AVAILABLE'?Math.min(cap,eco.recommended_speed_kmh):cap;const dp=dt/nominal*target/(60/speedFactor(t));const rate=target/t.maxSpeedKmh;t.actualSpeed=target;t.ecoAdvice=eco;const old=t.p;t.p=Math.max(0,Math.min(1,t.p+dp*t.dir));const moved=Math.abs(t.p-old)*durations[t.segment];t.energy=(t.energy||0)+moved*(.15+.85*rate*rate)*(t.massTons/1000);if((t.lastSpeed||0)>target)t.energy+=2*((t.lastSpeed-target)/t.maxSpeedKmh)**2*(t.massTons/1000);t.distance_work=(t.distance_work||0)+moved;t.work+=Math.abs(t.p-old)*nominal;
 if((t.dir===1&&t.p>=1)||(t.dir===-1&&t.p<=0)){t.node=t.dir===1?t.segment+1:t.segment;t.stationPassages[t.node]=w.time;b[t.lane]=null;if(t.lane==='main')b.freeAt=w.time+1;else b.reserveFreeAt=w.time+1;if(w.eco&&t.ecoAdvice?.full_stop_avoided)t.ecoArrivalPending={block:t.dir===1?t.segment+1:t.segment-1,wait:t.wait,predicted:true};t.segment=null;t.state='ready';if((t.dir===1&&t.node===8)||(t.dir===-1&&t.node===0)){t.finished=w.time;t.state='done';t.actualSpeed=0;w.log.unshift({time:w.time,kind:'good',key:'finish',id:t.id});}}}}
 else{t.actualSpeed=0;t.energy=(t.energy||0)+dt*.05*(t.massTons/1000);if(w.time>=(t.releaseAt||0))t.wait+=dt;t.state=w.time<(t.releaseAt||0)?'ready':t.hold?'held':'queue';}if((t.lastSpeed||0)>5&&(t.actualSpeed||0)<.1&&t.finished===null){t.fullStops++;t.energy+=3*(t.massTons/1000);}t.lastSpeed=t.actualSpeed||0;t.energy_proxy_units=t.energy;t.delay=Math.max(0,(t.finished??w.time)-(t.releaseAt||0)-t.work);t.recommended_speed_profile=t.ecoAdvice?.recommended_speed_profile||[];t.target_arrival_time=t.ecoAdvice?.target_arrival_time||null;}
 schedule(w);recordFrame(w);if(w.history.length===0||w.time-w.history.at(-1).time>=.99)w.history.push({time:w.time,...metrics(w)});if(w.trains.every(t=>t.finished!==null)){w.done=true;for(const t of w.trains)t.actualSpeed=0;recordFrame(w,true);break;}}
 if(w.log.length>180)w.log.length=180;return events.filter(Boolean);}
export function metrics(w){const total=w.trains.reduce((n,t)=>n+t.delay,0);return {total,weighted:w.trains.reduce((n,t)=>n+t.delay*(w.config?.priorities?.[t.type]??t.weight),0),avg:total/w.trains.length,waiting:w.trains.filter(t=>['queue','blocked','held'].includes(t.state)).length,finished:w.trains.filter(t=>t.finished!==null).length,index:quality(w).index,passengerMinutes:w.trains.reduce((n,t)=>n+t.delay*t.people,0)};}
export function position(t){if(t.segment===null){const n=nodes[t.node];return {x:n.x+(t.index%3-1)*3,z:n.z+4+(t.index%2)*3,angle:0};}const a=nodes[t.segment],b=nodes[t.segment+1],p=t.p;const zOffset=t.lane==='reserve'?-4:0;return {x:a.x+(b.x-a.x)*p,z:a.z+(b.z-a.z)*p+zOffset,angle:Math.atan2(b.z-a.z,b.x-a.x)+(t.dir<0?Math.PI:0)};}
export function eta(w,t){return t.finished??stationArrivals(w,t.dir>0?nodes.length-1:0).find(r=>r.id===t.id)?.arrival??null;}
export function replay(time,{scenario=-1,auto=false,eco=auto}={}){const w=makeWorld({scenario,auto,eco});step(w,time);return w;}
export function assertWorld(w){for(const b of w.blocks){for(const lane of ['main','reserve']){const trains=w.trains.filter(t=>t.segment===b.i&&t.lane===lane);if(trains.length>1)throw Error('Block overlap');if((trains[0]?.id||null)!==b[lane])throw Error('Occupancy mismatch');}}for(const t of w.trains)if(!Number.isFinite(t.delay)||t.p<0||t.p>1)throw Error('Invalid train state');}

// Release estimates use only this world's current occupancy and known events.
export function nextRelease(w,t){
 if(t.segment===null||t.finished!==null)return null;
 const next=t.dir===1?t.segment+1:t.segment-1;
 if(next<0||next>=w.blocks.length)return null;
 const b=w.blocks[next],inc=incidentFor(w,next);
 let main=Math.max(w.time,b.freeAt||0,...(w.signals||[]).filter(s=>s.block===next).map(s=>s.opensAt));
 if(inc?.type==='closure')main=Math.max(main,inc.until);
 if(b.main)main=Infinity; // Occupied block: no promised release from an unverified ETA.
 if(b.reserveOpen&&!b.reserve)main=Math.min(main,Math.max(w.time,b.reserveFreeAt||0));
 return Number.isFinite(main)&&main>w.time+.0000001?main:null;
}
export function approach(w,t){
 const distance=t.segment===null?0:durations[t.segment]*(t.dir===1?1-t.p:t.p);
 const cap=t.maxSpeedKmh||(60/speedFactor(t)),inc=t.segment===null?null:incidentFor(w,t.segment);
 if(inc?.type==='closure'&&t.lane==='main')return {...ecoAdvice({distanceKm:distance,currentKmh:0,capKmh:cap,nowMin:w.time,openMin:inc.until,massTons:t.massTons}),status:'BLOCKED'};
 const next=nextRelease(w,t);
 const allowed=t.lane==='reserve'?cap*.8:inc?.type==='slow'?Math.min(cap,40):cap;return ecoAdvice({distanceKm:distance,currentKmh:allowed,capKmh:allowed,nowMin:w.time,openMin:next,massTons:t.massTons});
}
