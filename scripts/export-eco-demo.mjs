import fs from 'node:fs';
import {makeWorld,step,metrics,assertWorld,incidentDefs} from '../services/ai/web/jibekjoly/corridor-engine.js';
const folder=new URL('../services/ai/web/jibekjoly/',import.meta.url);
const example=makeWorld({auto:true,eco:true});
example.tripId='SIM-ECO-EXAMPLE-20261002';
step(example,200);assertWorld(example);
fs.writeFileSync(new URL('demo-trip.json',folder),JSON.stringify(example));
const scenarios=incidentDefs.map((incident,scenario)=>{
 const results=[false,true].map(auto=>{
  const w=makeWorld({scenario,auto,recordJourney:false});
  step(w,200);assertWorld(w);
  return {...metrics(w),energy_proxy_units:w.trains.reduce((s,t)=>s+t.energy,0),full_stops:w.trains.reduce((s,t)=>s+t.fullStops,0),full_stop_avoided:w.trains.reduce((s,t)=>s+t.full_stop_avoided,0)};
 });
 return {scenario,title:incident.title[0],before:results[0],after:results[1]};
});
fs.writeFileSync(new URL('../docs/eco-demo-evaluation.json',import.meta.url),JSON.stringify({package_id:'kz-eco-synthetic-v1',seed:20261002,synthetic_only:true,method:'Same initial state, 200 model minutes. After: repair/reserve/priority plus freight Eco. No ML accuracy or real fuel claims.',scenarios},null,2)+'\n');
console.log(scenarios.map(s=>({scenario:s.scenario,index:`${s.before.index} -> ${s.after.index}`,delay:`${s.before.total.toFixed(1)} -> ${s.after.total.toFixed(1)}`,energy:`${s.before.energy_proxy_units.toFixed(1)} -> ${s.after.energy_proxy_units.toFixed(1)}`})));
