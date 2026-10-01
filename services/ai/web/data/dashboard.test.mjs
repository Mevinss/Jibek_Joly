import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {delayBand,normalizeETA,normalizeStationArrivals,normalizeCascade,normalizeSpeedAdvice,
  normalizeCompareResult,normalizeDispatchPlan,normalizeQualityIndex,normalizeWhatIf,
  normalizeState,normalizeTopology} from './adapters.mjs';
import {MockProvider} from './mock-provider.mjs';
import {LiveProvider} from './live-provider.mjs';

const web=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const read=name=>JSON.parse(fs.readFileSync(path.join(web,name),'utf8'));
const example=name=>JSON.parse(fs.readFileSync(path.resolve(web,'../../../docs/examples',`person3_${name}.json`),'utf8'));
const fixtures=['compare','station-arrivals','dispatch-plan','speed-advice','cascade','quality-index','what-if','cities'];

test('all frontend mock JSON is labelled and contains no physical energy claim',()=>{
  for(const name of fixtures){const value=read(`mocks/${name}.json`);assert.equal(value.source_type,'MOCK');
    const text=JSON.stringify(value).toLowerCase();assert.doesNotMatch(text,/energy_kwh|co2|tenge|liters/);}
  assert.equal(normalizeCompareResult(read('mocks/compare.json')).source_type,'MOCK');
});
test('RU and KK dashboard locale keys match and cover rendered labels',()=>{
  const ru=read('locales/dashboard-ru.json'),kk=read('locales/dashboard-kk.json');
  assert.deepEqual(Object.keys(ru).sort(),Object.keys(kk).sort());
  const html=fs.readFileSync(path.join(web,'dispatch-dashboard.html'),'utf8');
  const js=fs.readFileSync(path.join(web,'dashboard.mjs'),'utf8');
  const keys=[...html.matchAll(/data-i18n="([^"]+)"/g),...js.matchAll(/T\(['"](d[^'"]+)['"]/g)]
    .map(match=>match[1]).filter(key=>!key.endsWith('_'));
  for(const key of keys)assert.ok(Object.hasOwn(ru,key),`Missing locale: ${key}`);
  for(const name of ['MOCK','DEMO','RUNTIME','DERIVED','UNAVAILABLE'])assert.ok(ru[`dSource_${name}`]);
  for(const name of ['ONLINE','STALE','OFFLINE','PAUSED','MOCK','CONNECTING'])assert.ok(ru[`dConnection_${name}`]);
  for(const name of ['UNKNOWN','FREE','OCCUPIED','UNAVAILABLE'])assert.ok(ru[`dTrack_${name}`]);
});
test('dashboard controls referenced by the controller exist in the page',()=>{
  const html=fs.readFileSync(path.join(web,'dispatch-dashboard.html'),'utf8');
  const js=fs.readFileSync(path.join(web,'dashboard.mjs'),'utf8');
  const ids=new Set([...html.matchAll(/\bid="([^"]+)"/g)].map(match=>match[1]));
  for(const match of js.matchAll(/\$\('([^']+)'\)/g))
    assert.ok(ids.has(match[1]),`Missing dashboard element: ${match[1]}`);
  assert.equal(ids.size,[...html.matchAll(/\bid="([^"]+)"/g)].length,'Duplicate HTML ID');
  read('locales/ru.json');read('locales/kk.json');
});
test('IDs and references in static map dataset are stable',()=>{
  const data=read('assets/mock/dataset.json');
  const stationIds=data.stations.map(row=>row.station_id),blockIds=data.blocks.map(row=>row.block_id);
  assert.equal(new Set(stationIds).size,stationIds.length);assert.equal(new Set(blockIds).size,blockIds.length);
  const segments=new Set(data.segments.map(row=>row.segment_id));
  for(const block of data.blocks)assert.ok(segments.has(block.segment_id));
  const profiles=Object.values(data.profiles).map(rows=>rows.map(row=>row.train_id).sort());
  for(const ids of profiles){assert.equal(new Set(ids).size,ids.length);assert.deepEqual(ids,profiles[0]);}
});
test('delay bands are demo thresholds and null stays unknown',()=>{
  assert.equal(delayBand(4.9),'ok');assert.equal(delayBand(5),'warning');
  assert.equal(delayBand(15),'orange');assert.equal(delayBand(30),'critical');
  assert.equal(delayBand(null),'unknown');
});
test('null ETA and unknown station track never become a fabricated arrival or free track',()=>{
  assert.equal(normalizeETA({eta:null}).eta,null);
  const arrivals=normalizeStationArrivals(read('mocks/station-arrivals.json'),'AST');
  assert.equal(arrivals.arrivals[1].eta,null);
  assert.equal(arrivals.arrivals[1].track_status,'UNKNOWN');
  assert.equal(arrivals.arrivals[1].track_id,null);
});
test('cascade cycle is bounded and each train appears once',()=>{
  const value=read('mocks/cascade.json');value.edges.push({from_train_id:value.nodes.at(-1).train_id,to_train_id:value.nodes[0].train_id});
  const result=normalizeCascade(value);
  assert.equal(result.nodes.length,value.nodes.length);
  assert.equal(new Set(result.nodes.map(row=>row.train_id)).size,result.nodes.length);
});
test('null advice remains unavailable and proxy is not converted to physical energy',()=>{
  assert.equal(normalizeSpeedAdvice(null).status,'UNAVAILABLE');
  const advice=normalizeSpeedAdvice(read('mocks/speed-advice.json'));
  assert.equal(advice.full_stop_avoided,null);
  assert.equal(advice.energy_proxy_delta,-.4);
  assert.ok(!('energy_kwh' in advice));
});
test('Person 2 speed advice fields map without changing their units or meaning',()=>{
  const advice=normalizeSpeedAdvice({train_id:'SIM-1',plan_id:'PLAN-1',source_type:'SIMULATED_DEMO',
    target_resource_id:'BLK-1',target_arrival_time:'2026-10-01T12:00:00+05:00',
    energy_proxy_units_before:2.1,energy_proxy_units_after:1.7,energy_proxy_delta:-.4,
    profile_points:[{distance_km:1,speed_kmh:42,elapsed_seconds:90}]});
  assert.equal(advice.target_arrival,'2026-10-01T12:00:00+05:00');
  assert.equal(advice.target_resource_id,'BLK-1');
  assert.equal(advice.resource_opens,null);
  assert.equal(advice.energy_proxy_before,2.1);
  assert.equal(advice.profile_points[0].time_s,90);
  assert.equal(advice.source_type,'DEMO');
});
test('canonical state requires explicit progress and complete occupancy list',()=>{
  const sample={schema_version:'2.0',trains:[{train_id:'SIM-1',route_progress_0_1:.5,block_progress_0_1:.2}],
    blocks:[{block_id:'B1',capacity:1,occupied_train_ids:['SIM-1'],state_conflict:false}]};
  assert.equal(normalizeState(sample).trains[0].block_progress_0_1,.2);
  assert.throws(()=>normalizeState({...sample,trains:[{train_id:'SIM-1',progress:.5}]}),/explicit progress/);
  assert.throws(()=>normalizeState({...sample,blocks:[{block_id:'B1',capacity:1,occupied_train_ids:['SIM-1','SIM-2'],state_conflict:false}]}),/Inconsistent/);
});
test('topology rejects broken references and labels approximate geometry',()=>{
  const graph={schema_version:'1.0',geometry_source:'EXTERNAL_REFERENCE_APPROXIMATE',
    stations:[{station_id:'A'},{station_id:'B'}],segments:[{segment_id:'S',from_station_id:'A',to_station_id:'B'}],
    blocks:[{block_id:'B',segment_id:'S'}],signals:[{signal_id:'SIG',block_id:'B'}]};
  assert.equal(normalizeTopology(graph).geometry_source,'EXTERNAL_REFERENCE_APPROXIMATE');
  assert.throws(()=>normalizeTopology({...graph,signals:[{signal_id:'SIG',block_id:'MISSING'}]}),/Unknown signal block/);
});
test('mock provider serves 28 stable SIM trains without claiming runtime',async()=>{
  const previous=globalThis.fetch;
  globalThis.fetch=async url=>{try{return new Response(fs.readFileSync(path.join(web,String(url).replace(/^\//,''))),{status:200});}
    catch{return new Response('not found',{status:404});}};
  try{const provider=new MockProvider(),state=await provider.getState(),topology=await provider.getTopology();
    assert.equal(state.source_type,'MOCK');assert.equal(state.trains.length,28);
    assert.equal(topology.geometry_source,'EXTERNAL_REFERENCE_APPROXIMATE');
    const blocks=new Set(topology.blocks.map(row=>row.block_id));
    for(const train of state.trains)for(const id of train.route)assert.ok(blocks.has(id));
    provider.setScenario('SCN-01');const changed=await provider.getState();
    assert.equal(changed.scenario_id,'SCN-01');
    assert.deepEqual(changed.trains.map(row=>row.train_id).sort(),state.trains.map(row=>row.train_id).sort());
  }finally{globalThis.fetch=previous;}
});
test('live provider does not silently return mock comparison or advice',async()=>{
  const previous=globalThis.fetch;
  globalThis.fetch=async()=>new Response('Not found',{status:404});
  try{const live=new LiveProvider();live.setScenario('SCN-ALL');
    await assert.rejects(()=>live.getCompareResult(),/HTTP 404/);
    await assert.rejects(()=>live.getSpeedAdvice('SIM-KOK_AST-F03'),/HTTP 404/);
  }finally{globalThis.fetch=previous;}
});
test('runtime provider uses one canonical run and exact identity for incident, preview and apply',async()=>{
  const calls=[],previous=globalThis.fetch;
  const state={...example('initial_snapshot'),schema_version:'2.0',run_id:'run-1',snapshot_version:7,snapshot_id:'run-1:7'};
  globalThis.fetch=async(path,options={})=>{calls.push({path,body:options.body?JSON.parse(options.body):null});
    const value=path==='/api/runtime/state'?state:path==='/api/runtime/incidents'?{state,incident:{type:'TRAIN_DELAY'}}:
      path==='/api/runtime/preview'?{applied:false}:path==='/api/runtime/apply'?{applied:true}:{};
    return new Response(JSON.stringify(value),{status:200,headers:{'Content-Type':'application/json'}});};
  try{const live=new LiveProvider();await live.getState();await live.createIncident('TRAIN_DELAY','T-1',5);
    await live.previewRuntime('B',30);await live.applyRuntime('B');
    assert.deepEqual(calls.map(row=>row.path),['/api/runtime/state','/api/runtime/incidents','/api/runtime/preview','/api/runtime/apply']);
    for(const row of calls.slice(1))assert.equal(row.body.run_id,'run-1');
    for(const row of calls.slice(1))assert.equal(row.body.snapshot_version,7);
    assert.equal(calls[2].body.horizon_minutes,30);
  }finally{globalThis.fetch=previous;}
});
test('Person 2 and Person 3 actual contracts feed the dashboard adapters',()=>{
  const state=normalizeState(example('initial_snapshot'));
  const comparison=normalizeCompareResult(example('compare'));
  const arrivals=normalizeStationArrivals(example('station_arrivals'),'BOR');
  const cascade=normalizeCascade(example('cascade'));
  const quality=normalizeQualityIndex({...example('quality_index'),source_type:'SIMULATED_DEMO'});
  const counterfactual=normalizeWhatIf(example('what_if'));
  assert.equal(state.trains.length,3);
  assert.equal(comparison.comparable,true);
  assert.equal(comparison.rows.length,2);
  assert.equal(comparison.rows[0].total_delay_min,3.05);
  assert.equal(arrivals.arrivals.length,3);
  assert.equal(arrivals.arrivals[0].track_status,'UNKNOWN');
  assert.equal(cascade.nodes.length,5);
  assert.ok(quality.score>0);
  assert.equal(counterfactual.original_snapshot_unchanged,true);
  assert.ok(counterfactual.delta.delay_min>0);
  assert.equal(normalizeDispatchPlan(example('compare').fifo).source_type,'DEMO');
});
