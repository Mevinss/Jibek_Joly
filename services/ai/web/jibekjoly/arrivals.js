import {nodes,durations,speedFactor,step} from './corridor-engine.js';

// Forecast the supplied snapshot only. Future, untriggered incidents are unknown.
const cache=new WeakMap();
const location=t=>t.segment===null?t.node:t.segment+t.p;
export function stationArrivals(input,station){
 if(!Number.isInteger(station)||station<0||station>=nodes.length)return [];
 const signature=[Math.floor(input.time*2),input.actions,input.eco,input.trains.map(t=>`${t.id}:${t.hold}`).join(),input.incidents.map(e=>e.until).join()].join('|');
 let cached=cache.get(input);
 if(!cached||cached.signature!==signature){
  const w=structuredClone({...input,timeline:[],history:[],log:[]});
  w.events=false;w.recordJourney=false;
  const times=new Map(input.trains.map(t=>[t.id,new Map(t.segment===null&&t.finished===null?[[t.node,input.time]]:[])]));
  while(!w.done&&w.time<input.time+240){
   const old=w.trains.map(location);step(w,.25);
   w.trains.forEach((t,i)=>{const at=location(t);for(let s=0;s<nodes.length;s++)if(t.dir>0?old[i]<s&&at>=s:old[i]>s&&at<=s)times.get(t.id).set(s,t.stationPassages?.[s]??w.time);});
   if(w.trains.every(t=>t.finished!==null||t.hold&&t.segment===null))break;
  }
  cached={signature,times};cache.set(input,cached);
 }
 return input.trains.filter(t=>t.finished===null&&(t.dir>0?station>=location(t):station<=location(t))).map(t=>{
  const arrival=cached.times.get(t.id).get(station)??null;
  let planned=t.releaseAt||0;
  for(let b=Math.min(t.start,station);b<Math.max(t.start,station);b++)planned+=durations[b]*speedFactor(t);
  if(t.initialProgress)planned-=durations[t.dir>0?t.start:t.start-1]*speedFactor(t)*t.initialProgress;
  planned=t.timetable?.stations?.[station]??planned;
  const delay=arrival===null?null:Math.max(0,arrival-Math.max(0,planned)-.15);
  return {id:t.id,color:t.color,type:t.type,arrival,eta_minutes:arrival===null?null:Math.max(0,arrival-input.time),delay_minutes:delay,severity:delay===null?'unknown':delay<=5?'good':delay<=15?'warn':'bad',held:t.hold&&t.segment===null};
 }).sort((a,b)=>(a.arrival??Infinity)-(b.arrival??Infinity));
}
