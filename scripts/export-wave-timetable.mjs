import fs from 'node:fs';
import {makeWorld,step,assertWorld} from '../services/ai/web/jibekjoly/corridor-engine.js';
const w=makeWorld({mode:'wave',eco:true,events:false,recordJourney:false,useTimetable:false});
const rows=Object.fromEntries(w.trains.map(t=>[t.id,{progress:[[0,0]],stations:{}}]));
while(!w.done&&w.time<240){
 step(w,.05);assertWorld(w);
 for(const t of w.trains){const r=rows[t.id];if(t.finished===null&&(w.time-r.progress.at(-1)[0]>=.499))r.progress.push([+w.time.toFixed(4),+t.distance_work.toFixed(7)]);}
}
if(!w.done)throw Error('Feasible schedule did not finish');
for(const t of w.trains){const r=rows[t.id];r.finish=t.finished;r.stations=t.stationPassages;r.progress.push([t.finished,t.distance_work]);}
fs.writeFileSync('services/ai/web/jibekjoly/timetable-data.js','// Generated from a complete, incident-free Eco run. Do not edit times by hand.\nexport const waveTimetable='+JSON.stringify(rows)+';\n');
console.log(w.trains.map(t=>({id:t.id,finish:t.finished,stops:t.fullStops,avoided:t.full_stop_avoided,energy:t.energy})));
