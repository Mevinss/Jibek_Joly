import {requestJson} from './api-client.mjs';
import {normalizeState,normalizeTopology,normalizeStationArrivals,normalizeCompareResult,
  normalizeDispatchPlan,normalizeSpeedAdvice,normalizeCascade,normalizeQualityIndex,unavailable} from './adapters.mjs';

const mockPath=name=>`/mocks/${name}.json`;
export class MockProvider {
  constructor() {this.state=null;this.topology=null;this.fixtures=new Map();this.dataset=null;this.scenarioId='SCN-ALL';}
  setScenario(id){if(!this.dataset?.profiles?.[id]&&this.dataset)throw Error('Unknown mock scenario');this.scenarioId=id;this.state=null;}
  async fixture(name) {if(!this.fixtures.has(name)){
    const value=await requestJson(mockPath(name));
    if(value.source_type!=='MOCK')throw Error(`Unlabelled mock: ${name}`);
    this.fixtures.set(name,value);
  }return this.fixtures.get(name);}
  async initialize() {
    if(this.state&&this.topology)return;
    const [dataset,coordinates,routes]=await Promise.all([
      requestJson('/assets/mock/dataset.json'),requestJson('/assets/map/station_coords.json'),
      requestJson('/assets/map/route_geometry.json')]);
    if(dataset.source!=='MOCK')throw Error('Unexpected static source');
    this.dataset=dataset;
    const coord=new Map(coordinates.map(row=>[row.station_id,[row.lon,row.lat]]));
    const geometry=new Map(routes.flatMap(row=>row.blocks.map(block=>[block.block_id,
      {type:'LineString',coordinates:[block.start_coord,block.end_coord]}])));
    this.topology=normalizeTopology({schema_version:'1.0',source_type:'MOCK',geometry_source:'EXTERNAL_REFERENCE_APPROXIMATE',
      stations:dataset.stations.map(row=>({station_id:row.station_id,name:row.name_kk,coordinates:coord.get(row.station_id)})),
      segments:dataset.segments.map(row=>({segment_id:row.segment_id,from_station_id:row.from_station_id,to_station_id:row.to_station_id})),
      blocks:dataset.blocks.map(row=>({block_id:row.block_id,segment_id:row.segment_id,
        capacity:Number(row.demo_capacity_trains),geometry:geometry.get(row.block_id)})),
      station_tracks:dataset.station_tracks.map(row=>({station_id:row.station_id,track_id:row.station_track_id,
        capacity:Number(row.demo_capacity_trains)})),
      signals:dataset.signals.map(row=>({signal_id:row.signal_id,block_id:row.block_id})),
      switches:dataset.switches.map(row=>({switch_id:row.switch_id,station_id:row.station_id,
        available_routes:String(row.controlled_tracks).split('|')}))});
    const profile=dataset.profiles[this.scenarioId],occupants=new Map(),segments=dataset.segments;
    const trains=profile.map(row=>{
      const stops=row.stops.map(stop=>stop.station_id),route=[];
      for(let i=0;i<stops.length-1;i++){
        const segment=segments.find(s=>(s.from_station_id===stops[i]&&s.to_station_id===stops[i+1])||
          (s.to_station_id===stops[i]&&s.from_station_id===stops[i+1]));
        if(!segment)throw Error(`Mock route missing: ${row.train_id}`);
        const ids=dataset.blocks.filter(block=>block.segment_id===segment.segment_id)
          .sort((a,b)=>Number(a.block_order)-Number(b.block_order)).map(block=>block.block_id);
        route.push(...(segment.from_station_id===stops[i]?ids:ids.reverse()));
      }
      const blockId=route[0];occupants.set(blockId,[...(occupants.get(blockId)||[]),row.train_id]);
      return {train_id:row.train_id,train_number:null,category:row.category,direction:row.direction,
        origin_station_id:row.origin_station_id,destination_station_id:row.destination_station_id,
        route_id:null,route,current_segment_id:dataset.blocks.find(b=>b.block_id===blockId)?.segment_id,
        current_block_id:blockId,route_progress_0_1:0,block_progress_0_1:0,
        speed_kmh:null,delay_min:row.stops[0]?.delay_min??0,next_station_id:stops[1]??null,
        scheduled_arrival:row.stops[1]?.scheduled_arrival??null,estimated_arrival:null,
        source_type:'MOCK',data_mode:'MOCK',updated_at:'2026-10-01T11:00:00+05:00',
        position_coordinates:coord.get(row.origin_station_id),status:'mock_static'};
    });
    const blocks=this.topology.blocks.map(block=>{const ids=occupants.get(block.block_id)||[];return {...block,
      occupied_train_ids:ids,closed:false,state_conflict:ids.length>block.capacity,
      speed_limit_kmh:null,direction_lock:null};});
    this.state=normalizeState({schema_version:'2.0',scenario_id:this.scenarioId,
      seed:dataset.scenarios.find(row=>row.scenario_id===this.scenarioId)?.seed??0,run_id:null,
      dataset_version:'frontend-mock-v1',virtual_time:'2026-10-01T11:00:00+05:00',
      snapshot_version:0,source_type:'MOCK',trains,blocks,station_tracks:this.topology.station_tracks.map(track=>({
        ...track,occupied_train_ids:[],available:null,occupancy_source:'UNAVAILABLE'})),
      signals:this.topology.signals.map(signal=>({...signal,aspect:null,failed:null})),
      switches:this.topology.switches.map(switchState=>({...switchState,position:null,locked:null,failed:null})),
      active_incidents:[]});
  }
  async getTopology(){await this.initialize();return this.topology;}
  async getState(){await this.initialize();return this.state;}
  getTrainDetails(trainId){return this.state?.trains.find(train=>train.train_id===trainId)??null;}
  async getStationArrivals(stationId){const fixture=await this.fixture('station-arrivals');
    return normalizeStationArrivals({...fixture,station_id:stationId,
      arrivals:fixture.station_id===stationId?fixture.arrivals:[]},stationId);}
  async getDispatchPlan(){return normalizeDispatchPlan(await this.fixture('dispatch-plan'));}
  async getCompareResult(){return normalizeCompareResult(await this.fixture('compare'));}
  async getSpeedAdvice(trainId){const advice=await this.fixture('speed-advice');
    return advice.train_id===trainId?normalizeSpeedAdvice(advice):unavailable('Mock speed advice only for selected example train');}
  async getCascade(){return normalizeCascade(await this.fixture('cascade'));}
  async getQualityIndex(){return normalizeQualityIndex(await this.fixture('quality-index'));}
  async runWhatIf(){return await this.fixture('what-if');}
  async submitHumanDecision(){return {status:'UNAVAILABLE',accepted:null,applied:false,
    reason:'Human validation is unavailable in frontend mock mode',source_type:'MOCK'};}
}
