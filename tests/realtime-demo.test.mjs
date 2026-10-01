import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { diagramData, scheduledKm, speedAdvice, acceptFrame, formatClock } from '../services/ai/web/combined/realtime-data.mjs';
const geo = JSON.parse(fs.readFileSync(new URL('../services/ai/demo/corridor.json', import.meta.url)));
const ts = '2026-10-01T11:00:00+05:00';
const train = {train_id:'SIM-KOK_AST-F01',speed:60,position:{block_id:'BOR-AKK-B03',km:5},delay_s:0};
const display = {train_id:train.train_id,origin:'KOK',destination:'AST',next_station:'AKK',direction:1,corridor_km:100,distance_to_station_km:74,scheduled_arrival:'2026-10-01T12:14:00+05:00',held:false};
const snapshot={ts,elapsed_s:0,state:{trains:[train],infra:{blocks:[{id:train.position.block_id,speed_limit:80,closed:false}]}},display:[display]};
test('clock formats both ISO snapshots and numeric diagram ticks in UTC+5',()=>{
 assert.equal(formatClock(ts),'11:00:00');assert.equal(formatClock(Date.parse(ts)-900000),'10:45:00');assert.equal(formatClock('bad'),'—');
});
test('diagram exposes observed movement, timetable and continuation on four separated northern stations',()=>{
 const previous=structuredClone(snapshot);previous.ts='2026-10-01T10:59:00+05:00';previous.elapsed_s=-60;previous.display[0].corridor_km=99;
 const d=diagramData(geo,snapshot,[previous,snapshot],train.train_id,'north');
 assert.equal(d.stations.length,4);assert.ok(d.stations[1].y-d.stations[0].y>70);
 assert.equal(d.trains[0].observed.length,2);assert.ok(d.trains[0].forecast[1].km>d.trains[0].forecast[0].km);
 assert.ok(d.trains[0].planned.length>20);
});
test('all nine main stations are available and reverse train continuation follows its own route',()=>{
 const reverse=structuredClone(snapshot);reverse.display[0].direction=-1;reverse.display[0].origin='AST';reverse.display[0].destination='KOK';
 const d=diagramData(geo,reverse,[reverse],train.train_id,'all');
 assert.equal(d.stations.length,9);assert.ok(d.trains[0].forecast[1].km<100);assert.ok(d.trains[0].forecast[1].km>=0);
});
test('continuation reaches the terminal at current speed then remains stationary',()=>{
 const near=structuredClone(snapshot);near.display[0].corridor_km=260;
 const line=diagramData(geo,near,[near],train.train_id,'north').trains[0].forecast;
 assert.equal(line.length,3);assert.equal(line[1].km,269);
 assert.equal((line[1].ms-line[0].ms)/1000,540);assert.equal(line[2].km,269);
});
test('timetable keeps station dwell rather than discarding departure times',()=>{
 const arrival=Date.parse(geo.timetable.find(r=>r.train_id===train.train_id&&r.station_id==='BOR').scheduled_arrival);
 assert.equal(scheduledKm(geo,train.train_id,arrival+120000),65);
});
test('speed advice uses live distance/time, refuses closure and unreachable schedule',()=>{
 assert.equal(speedAdvice(snapshot,geo,train.train_id).recommendedKmh,60);
 const closed=structuredClone(snapshot);closed.display[0].held=true;assert.equal(speedAdvice(closed,geo,train.train_id).status,'HOLD');
 const late=structuredClone(snapshot);late.display[0].scheduled_arrival='2026-10-01T11:10:00+05:00';assert.equal(speedAdvice(late,geo,train.train_id).status,'UNREACHABLE');
});
test('realtime deduplicates, rejects stale and malformed frames, permits explicit reset',()=>{
 assert.equal(acceptFrame(snapshot,snapshot),false);
 assert.equal(acceptFrame(snapshot,{...snapshot,elapsed_s:-1}),false);
 assert.equal(acceptFrame(null,{...snapshot,display:[]}),false);
 assert.equal(acceptFrame(null,snapshot),true);
 assert.equal(acceptFrame(snapshot,{...snapshot,elapsed_s:1}),true);
});
