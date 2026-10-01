import test from 'node:test';
import assert from 'node:assert/strict';
import {makeWorld,step,signalState,action,assertWorld} from '../services/ai/web/jibekjoly/corridor-engine.js';
import {quality} from '../services/ai/web/jibekjoly/quality.js';
import {compareEcoTrip} from '../services/ai/web/jibekjoly/trip-comparison.js';
import {frameWorld} from '../services/ai/web/jibekjoly/journey.js';

test('Healthy feasible timetable starts at 100; score drops for an actual incident',()=>{
 const w=makeWorld({eco:true,events:false,mode:'wave'});
 assert.equal(quality(w).index,100);
 step(w,35);assert.ok(quality(w).index>=99);
 const bad=makeWorld({eco:true,scenario:0,mode:'wave'});step(bad,35);
 assert.ok(quality(bad).index<quality(w).index);
});
test('All train types obey a manually red signal and resume on green',()=>{
 for(const index of [0,2,4]){
  const w=makeWorld({eco:true,events:false,mode:'wave',recordJourney:false});
  const train=w.trains[index];
  action(w,'signal',null,train.dir>0?4:3,1);
  step(w,80);assertWorld(w);
  assert.equal(signalState(w,4,1).aspect,'red');
  assert.ok(train.node<=4);assert.equal(train.finished,null);
  action(w,'signal',null,4,1);step(w,160);assertWorld(w);
  assert.ok(train.finished!==null);
 }
});
test('Freight decelerates smoothly, crosses several green gates, and records actual avoidance',()=>{
 const w=makeWorld({eco:true,events:false,mode:'wave',recordJourney:false});
 const t=w.trains[4],old=t.actualSpeed;
 step(w,.05);assert.ok(t.actualSpeed<old);assert.ok(old-t.actualSpeed<=1.31);
 step(w,160);assertWorld(w);
 for(const train of w.trains.filter(t=>t.type===2)){
  assert.equal(train.fullStops,0);
  assert.ok(train.full_stop_avoided>=3);
  assert.ok(train.passedSignals.every(s=>s.aspect==='green'));
 }
});
test('Fuel result is two identical-input simulations, signed, and leaves the live world intact',()=>{
 const w=makeWorld({eco:true,events:false,mode:'wave',recordJourney:false});
 step(w,160);const old=JSON.stringify(w);
 const report=compareEcoTrip(w);
 assert.equal(JSON.stringify(w),old);
 assert.equal(report.synthetic_only,true);assert.equal(report.complete,true);
 const t=report.trains.find(t=>t.id==='SIM-FRT-208');
 assert.ok(t.baseline_fuel_liters>t.eco_fuel_liters);
 assert.equal(t.fuel_saved_liters,t.baseline_fuel_liters-t.eco_fuel_liters);
});
test('Historical signal and passage state does not borrow future commands or passages',()=>{
 const w=makeWorld({eco:true,events:false,mode:'wave'}),initial=w.timeline[0];
 step(w,15);action(w,'signal',null,4,1);
 const past=frameWorld(w,initial);
 assert.deepEqual(past.manualRed,{});assert.equal(past.actionHistory.length,0);
 assert.equal(past.trains[4].passedSignals.length,0);
 assert.deepEqual(past.trains[4].stationPassages,{});
 assert.equal(signalState(past,4,1).reason,'window');
});
