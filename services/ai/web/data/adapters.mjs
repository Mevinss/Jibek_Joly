// Presentation-only contract adapters. No dispatch, ETA or energy formula lives here.
export const SOURCE_TYPES = Object.freeze(['MOCK', 'DEMO', 'RUNTIME', 'DERIVED', 'UNAVAILABLE']);
export const unavailable = reason => ({status:'UNAVAILABLE', source_type:'UNAVAILABLE', reason});
export const finiteOrNull = value => typeof value === 'number' && Number.isFinite(value) ? value : null;
export const delayBand = minutes => minutes == null || !Number.isFinite(Number(minutes)) ? 'unknown'
  : Number(minutes) < 5 ? 'ok' : Number(minutes) < 15 ? 'warning' : Number(minutes) < 30 ? 'orange' : 'critical';
export const sourceType = (value, fallback='UNAVAILABLE') => {
  const type = String(value || fallback).toUpperCase();
  if(type==='SIMULATED_DEMO'||type==='SYNTHETIC_DEMO'||type==='KAZAKHSTAN_SYNTHETIC_TIMETABLE') return 'DEMO';
  return SOURCE_TYPES.includes(type) ? type : fallback;
};
const list = value => Array.isArray(value) ? value : [];
const unique = (values, label) => {
  if (values.some(value => !value) || new Set(values).size !== values.length) throw Error(`Invalid ${label} IDs`);
};

export function normalizeTopology(raw) {
  if (!raw || raw.schema_version !== '1.0') throw Error('Topology contract unavailable');
  const stations=list(raw.stations), segments=list(raw.segments), blocks=list(raw.blocks);
  unique(stations.map(row=>row.station_id),'station');
  unique(segments.map(row=>row.segment_id),'segment');
  unique(blocks.map(row=>row.block_id),'block');
  const stationIds=new Set(stations.map(row=>row.station_id));
  const segmentIds=new Set(segments.map(row=>row.segment_id));
  const blockIds=new Set(blocks.map(row=>row.block_id));
  for(const segment of segments) if(!stationIds.has(segment.from_station_id)||!stationIds.has(segment.to_station_id)) throw Error('Unknown topology station');
  for(const block of blocks) if(!segmentIds.has(block.segment_id)) throw Error('Unknown topology segment');
  for(const signal of list(raw.signals)) if(!blockIds.has(signal.block_id)) throw Error('Unknown signal block');
  return {...raw,stations,segments,blocks,geometry_source:raw.geometry_source||'UNAVAILABLE'};
}

export function normalizeState(raw) {
  if (!raw || raw.schema_version !== '2.0') throw Error('Canonical State v2 unavailable');
  const trains=list(raw.trains), blocks=list(raw.blocks);
  unique(trains.map(row=>row.train_id),'train');
  unique(blocks.map(row=>row.block_id),'block');
  for(const train of trains) {
    if(finiteOrNull(train.route_progress_0_1)===null||finiteOrNull(train.block_progress_0_1)===null) throw Error(`Missing explicit progress: ${train.train_id}`);
  }
  for(const block of blocks) {
    if(!Array.isArray(block.occupied_train_ids)) throw Error(`Missing block occupants: ${block.block_id}`);
    if(Boolean(block.state_conflict)!==(block.occupied_train_ids.length>Number(block.capacity))) throw Error(`Inconsistent block conflict: ${block.block_id}`);
  }
  return {...raw,trains,blocks,source_type:raw.source_type||'SIMULATED_DEMO'};
}

export function normalizeETA(raw) {
  if(!raw) return {eta:null,minutes_remaining:null,source_type:'UNAVAILABLE'};
  const value=raw.eta??raw.estimated_arrival??null;
  return {eta:typeof value==='string'&&Number.isFinite(Date.parse(value))?value:null,
    minutes_remaining:finiteOrNull(raw.minutes_remaining),
    source_type:sourceType(raw.source_type,raw.estimated_arrival_source==='DERIVED'?'DERIVED':'UNAVAILABLE')};
}

export function normalizeStationArrivals(raw, stationId) {
  if(!raw||!Array.isArray(raw.arrivals)) return unavailable('Station arrivals API unavailable');
  return {status:'READY',station_id:raw.station_id||stationId,virtual_time:raw.virtual_time??null,
    source_type:sourceType(raw.source_type,'DERIVED'),arrivals:raw.arrivals.map(row=>({
      train_id:row.train_id,train_number:row.train_number??null,category:row.category??null,
      ...normalizeETA(row),scheduled_arrival:row.scheduled_arrival??null,
      delay_min:finiteOrNull(row.delay_min),track_id:row.track_id??row.recommended_track??null,
      track_status:row.track_status??'UNKNOWN',data_source:row.data_source??row.source??raw.source_type??'UNAVAILABLE',
    }))};
}

export function normalizeCompareResult(raw) {
  if(raw?.fifo||raw?.cp_sat){
    const rows=['fifo','cp_sat','human'].filter(key=>raw[key]).map(key=>{
      const run=raw[key],completed=run.valid===true&&run.status==='COMPLETED';
      return {policy:run.policy??key.toUpperCase(),total_delay_min:completed?finiteOrNull(run.total_arrival_delay_min):null,
        incident_delay_min:completed?finiteOrNull(run.added_delay_after_incident_min):null,
        conflicts:completed?finiteOrNull(run.conflict_count):null,compute_ms:finiteOrNull(run.planner_ms),
        energy_proxy_units:completed?finiteOrNull(run.energy_proxy_units):null,
        validation:run.status+(run.termination_reason?` · ${run.termination_reason}`:'')};
    });
    return {status:'READY',source_type:sourceType(raw.source_type,'DEMO'),snapshot_id:raw.fifo?.initial_conditions?.snapshot_hash??null,
      comparable:raw.comparable===true,scope:raw.scope??null,cohort_size:raw.cohort_size??null,
      improvement_vs_fifo_pct:raw.comparable?finiteOrNull(raw.improvement_vs_fifo_pct):null,rows};
  }
  if(!raw||!Array.isArray(raw.rows)) return unavailable('CompareResult API unavailable');
  return {status:'READY',source_type:sourceType(raw.source_type,'UNAVAILABLE'),snapshot_id:raw.snapshot_id??null,
    rows:raw.rows.map(row=>({policy:row.policy??row.strategy??'UNKNOWN',
      total_delay_min:finiteOrNull(row.total_delay_min),incident_delay_min:finiteOrNull(row.incident_delay_min),
      conflicts:finiteOrNull(row.conflicts),compute_ms:finiteOrNull(row.compute_ms),
      energy_proxy_units:finiteOrNull(row.energy_proxy_units),validation:row.validation??'UNAVAILABLE'}))};
}

export function normalizeDispatchPlan(raw) {
  if(!raw) return unavailable('Dispatch plan API unavailable');
  const legacy=Boolean(raw.cp_sat);
  const result=legacy?raw.cp_sat:raw;
  const valid=result.valid===true,fullyValidated=result.fully_validated===true;
  return {status:'READY',source_type:legacy?'DEMO':sourceType(raw.source_type),
    plan_id:result.plan_id??raw.snapshot_id??null,policy:result.policy??'CP-SAT',
    solver_status:result.solver_status??result.status??'UNAVAILABLE',
    solver_wall_time_ms:finiteOrNull(result.solver_wall_time_ms??
      (finiteOrNull(result.solver_wall_time_seconds)!==null?result.solver_wall_time_seconds*1000:null)),
    valid:result.valid??null,fully_validated:result.fully_validated??null,
    validation_scope:Array.isArray(result.validation?.validation_scope)?result.validation.validation_scope.join(', '):
      result.validation_scope??(legacy?'PAIR_BLOCK_ONLY':null),
    unverified_scope:list(result.validation?.unverified_scope??result.unverified_scope),fallback_used:result.fallback_used??false,
    fallback_reason:result.fallback_reason??null,holding_minutes:finiteOrNull(result.holding_minutes),
    selected_station_track:result.selected_station_track??null,
    pair_train_ids:list(raw.pair_train_ids),fifo_order:list(raw.fifo?.ordered_train_ids),
    reservations:list(result.resource_intervals??result.reservations),snapshot_overlaps:list(raw.snapshot_overlaps),
    validation_status:!valid&&result.valid===false?'INVALID':valid&&fullyValidated?'VALIDATED':valid?'PARTIALLY_VALIDATED':'UNAVAILABLE'};
}

export function normalizeSpeedAdvice(raw) {
  if(!raw||raw.status==='UNAVAILABLE') return unavailable(raw?.reason||'Speed advice API unavailable');
  if(raw.profile_type==='advisory_limit_profile')return {
    status:'LIMIT_ONLY_ILLUSTRATION',source_type:sourceType(raw.source_type,'DEMO'),train_id:raw.train_id,
    profile_points:list(raw.profile).flatMap(row=>[
      {distance_km:finiteOrNull(row.distance_from_km),speed_limit_kmh:finiteOrNull(row.recommended_speed_kmh),recommended_speed_kmh:null},
      {distance_km:finiteOrNull(row.distance_to_km),speed_limit_kmh:finiteOrNull(row.recommended_speed_kmh),recommended_speed_kmh:null}]),
    segments:list(raw.profile),current_speed_kmh:null,recommended_speed_kmh:null,
    full_stop_avoided:null,energy_proxy_before:null,energy_proxy_after:null,energy_proxy_delta:null,
    reason:raw.limitations?.join(' ')||null,snapshot_id:raw.snapshot_id};
  const points=list(raw.profile_points).map(row=>({distance_km:finiteOrNull(row.distance_km),
    time_s:finiteOrNull(row.time_s??row.elapsed_seconds),recommended_speed_kmh:finiteOrNull(row.recommended_speed_kmh??row.speed_kmh),
    speed_limit_kmh:finiteOrNull(row.speed_limit_kmh)}));
  return {status:'READY',source_type:sourceType(raw.source_type),train_id:raw.train_id??null,
    current_speed_kmh:finiteOrNull(raw.current_speed_kmh),recommended_speed_kmh:finiteOrNull(raw.recommended_speed_kmh),
    target_arrival:raw.target_arrival_time??raw.target_arrival??null,resource_opens:raw.resource_opens??null,
    target_resource_id:raw.target_resource_id??null,
    full_stop_avoided:typeof raw.full_stop_avoided==='boolean'?raw.full_stop_avoided:null,
    energy_proxy_before:finiteOrNull(raw.energy_proxy_units_before??raw.energy_proxy_before??raw.energy_proxy?.before),
    energy_proxy_after:finiteOrNull(raw.energy_proxy_units_after??raw.energy_proxy_after??raw.energy_proxy?.after),
    energy_proxy_delta:finiteOrNull(raw.energy_proxy_delta??raw.energy_proxy?.delta),
    reason:raw.reason??null,profile_points:points,plan_id:raw.plan_id??null};
}

export function normalizeCascade(raw) {
  if(raw?.affected_trains&&Array.isArray(raw.chain)){
    const nodes=[{train_id:raw.root_train_id,added_delay_min:finiteOrNull(raw.root_delay_min),cause:'ROOT'},
      ...raw.affected_trains.map(row=>({train_id:row.train_id,added_delay_min:finiteOrNull(row.added_delay_min),cause:row.cause??null}))];
    return normalizeCascade({source_type:raw.source_type,total_added_delay_min:raw.network_added_delay_min,
      nodes,edges:raw.chain,connections:raw.chain.filter(row=>row.station_id).map(row=>({
        from_train_id:row.from_train_id,to_train_id:row.to_train_id,station_id:row.station_id,
        minimum_transfer_min:null}))});
  }
  if(!raw||!Array.isArray(raw.nodes)) return unavailable('CascadingDelayResult API unavailable');
  const byId=new Map();
  for(const node of raw.nodes) if(node.train_id&&!byId.has(node.train_id)) byId.set(node.train_id,{
    train_id:node.train_id,added_delay_min:finiteOrNull(node.added_delay_min),cause:node.cause??null});
  const edges=list(raw.edges).filter(edge=>byId.has(edge.from_train_id)&&byId.has(edge.to_train_id));
  // A cycle may be present in a future graph. Traversal is bounded by IDs.
  const ordered=[],seen=new Set(),queue=[...byId.keys()];
  while(queue.length&&seen.size<byId.size){const id=queue.shift();if(seen.has(id))continue;seen.add(id);ordered.push(byId.get(id));
    for(const edge of edges)if(edge.from_train_id===id&&!seen.has(edge.to_train_id))queue.push(edge.to_train_id);}
  return {status:'READY',source_type:sourceType(raw.source_type,'UNAVAILABLE'),nodes:ordered,edges,
    total_added_delay_min:finiteOrNull(raw.total_added_delay_min),connections:list(raw.connections)};
}

export function normalizeQualityIndex(raw) {
  if(!raw||finiteOrNull(raw.score)===null) return unavailable('QualityIndex API unavailable');
  return {status:'READY',source_type:sourceType(raw.source_type,'UNAVAILABLE'),score:raw.score,
    factors:list(raw.factors).map(row=>({key:row.key??row.name??'unknown',points:finiteOrNull(row.points??row.impact??row.contribution)}))};
}

export function normalizeWhatIf(raw) {
  if(!raw||!raw.base||!raw.scenario)return unavailable('What-if result unavailable');
  const policy='cp_sat';
  const metrics=run=>({delay_min:finiteOrNull(run?.total_arrival_delay_min),conflicts:finiteOrNull(run?.conflict_count),
    stops:finiteOrNull(run?.stop_count),energy_proxy_units:finiteOrNull(run?.energy_proxy_units),affected_trains:null});
  const current=metrics(raw.base[policy]),what_if=metrics(raw.scenario[policy]);
  const delta={delay_min:finiteOrNull(raw.delta?.[policy]),conflicts:null,stops:null,energy_proxy_units:null,affected_trains:null};
  return {status:'READY',source_type:sourceType(raw.source_type,'DEMO'),current,what_if,delta,
    note:null,policy:'CP_SAT',original_snapshot_unchanged:raw.original_snapshot_unchanged===true,
    affected_resource_ids:[]};
}
