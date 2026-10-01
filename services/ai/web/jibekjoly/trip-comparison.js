import {makeWorld,step,action} from './corridor-engine.js';
import {syntheticData} from './synthetic-data.js';
const cache=new WeakMap();
// Same starting input and observed incidents/dispatcher commands; vary only Eco.
export function compareEcoTrip(input){
 const signature=[input.time,input.actions,input.done].join('|');
 if(cache.get(input)?.signature===signature)return cache.get(input).report;
 if(!input.done)return {complete:false,synthetic_only:true,trains:[]};
 const run=eco=>{
  const w=makeWorld({...input.initialInput,mode:input.mode,auto:false,eco,events:false,recordJourney:false});
  w.policy=input.initialInput?.auto?'passenger':undefined;w.config=structuredClone(input.config);
  const commands=(input.actionHistory||[]).filter(a=>a.kind!=='eco');let ci=0;
  const incidents=(input.incidents||[]).map(e=>({...e,until:e.time+e.length,repair:false,managed:false,cleared:false})).sort((a,b)=>a.time-b.time);let ii=0;
  while(!w.done&&w.time<Math.max(240,input.time+120)){
   while(ii<incidents.length&&incidents[ii].time<=w.time+.000001)w.incidents.push(structuredClone(incidents[ii++]));
   while(ci<commands.length&&commands[ci].time<=w.time+.000001){const a=commands[ci++];action(w,a.kind,a.id,a.blockId,a.dir);}
   step(w,.05);
  }
  return w;
 };
 const before=run(false),after=run(true),coefficient=syntheticData.demo_physics.fuel_liters_per_proxy_unit;
 const trains=before.trains.filter(t=>t.type===2).map(t=>{
  const a=after.trains.find(x=>x.id===t.id),baseline=t.energy*coefficient,eco=a.energy*coefficient;
  return {id:t.id,baseline_fuel_liters:baseline,eco_fuel_liters:eco,fuel_saved_liters:baseline-eco,baseline_stops:t.fullStops,eco_stops:a.fullStops,full_stop_avoided:a.full_stop_avoided,baseline_arrival:t.finished,eco_arrival:a.finished};
 });
 const report={complete:before.done&&after.done,synthetic_only:true,calibrated:false,fuel_liters_per_proxy_unit:coefficient,trains};
 cache.set(input,{signature,report});return report;
}
