import test from 'node:test';
import assert from 'node:assert/strict';
import {ecoAdvice} from '../services/ai/web/jibekjoly/eco-model.js';
import {makeWorld,step,assertWorld} from '../services/ai/web/jibekjoly/corridor-engine.js';
import {stationArrivals} from '../services/ai/web/jibekjoly/arrivals.js';

test('Eco crosses the known opening without a full stop; red blocks entry',()=>{
 const baseline=makeWorld({events:false,eco:false,recordJourney:false});
 const eco=makeWorld({events:false,eco:true,recordJourney:false});
 step(eco,9);assertWorld(eco);assert.equal(eco.blocks[4].main,null);
 step(baseline,11);step(eco,2);assertWorld(eco);
 assert.equal(baseline.trains[4].fullStops,1);
 assert.equal(eco.trains[4].fullStops,0);
 assert.equal(eco.trains[4].full_stop_avoided,1);
 assert.ok(eco.trains[4].energy<baseline.trains[4].energy);
});

test('Station ETA uses only a copy of the supplied snapshot and respects a hold',()=>{
 const w=makeWorld({events:false,eco:true,recordJourney:false});
 const original=JSON.stringify(w);
 const row=stationArrivals(w,4).find(t=>t.id==='SIM-FRT-208');
 assert.ok(Math.abs(row.eta_minutes-10)<.3);
 assert.equal(JSON.stringify(w),original);
 w.trains[0].hold=true;w.actions++;
 assert.equal(stationArrivals(w,4).find(t=>t.id===w.trains[0].id).arrival,null);
});

test('Scheduled departure is not delay and a finished train has zero actual speed',()=>{
 const w=makeWorld({events:false,eco:false,recordJourney:false});
 const train=w.trains[5];
 w.trains=[train];for(const block of w.blocks){block.main=null;block.reserve=null;}
 w.signals=[];
 step(w,10);assert.equal(train.delay,0);assert.equal(train.distance_work,0);
 step(w,15);assert.ok(train.distance_work>0);
 const fleet=makeWorld({events:false,eco:true,recordJourney:false});
 step(fleet,60);assert.equal(fleet.trains[4].state,'done');
 assert.equal(fleet.trains[4].actualSpeed,0);assert.equal(fleet.done,false);
});

test('Side-by-side scenarios receive the identical incident before intervention',()=>{
 for(let scenario=0;scenario<4;scenario++){
  const before=makeWorld({scenario,auto:false,recordJourney:false});
  const after=makeWorld({scenario,auto:true,recordJourney:false});
  step(before,6);step(after,6);
  assert.deepEqual(before.incidents.map(e=>[e.block,e.type,e.time,e.until]),after.incidents.map(e=>[e.block,e.type,e.time,e.until]));
  assertWorld(before);assertWorld(after);
 }
});
test('seven km to a known green in ten minutes computes 42 and avoids a real baseline stop',()=>{
 const a=ecoAdvice({distanceKm:7,currentKmh:80,capKmh:80,nowMin:0,openMin:10,massTons:3500});
 assert.equal(a.recommended_speed_kmh,42);assert.equal(a.full_stop_avoided,true);
 assert.ok(a.cruise_speed_kmh<42);assert.equal(a.recommended_speed_profile[0].speed_kmh,80);
 assert.ok(a.energy_proxy_units<a.baseline_energy_proxy_units);
 assert.equal(a.recommended_speed_profile.at(-1).elapsed_seconds,600);
});
test('unknown or unreachable target does not invent an avoided stop',()=>{
 assert.equal(ecoAdvice({distanceKm:7,currentKmh:80,capKmh:80,nowMin:0,openMin:null}).status,'UNKNOWN');
 assert.equal(ecoAdvice({distanceKm:7,currentKmh:80,capKmh:80,nowMin:0,openMin:1}).status,'UNREACHABLE');
});
