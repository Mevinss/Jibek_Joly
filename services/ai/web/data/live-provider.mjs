import {requestJson} from './api-client.mjs';
import {normalizeState,normalizeTopology,normalizeStationArrivals,normalizeCompareResult,
  normalizeDispatchPlan,normalizeSpeedAdvice,normalizeCascade,normalizeQualityIndex,normalizeWhatIf,unavailable} from './adapters.mjs';

const query = values => new URLSearchParams(Object.entries(values).filter(([,value])=>value!==undefined&&value!==null)).toString();

export class LiveProvider {
  constructor(endpoints={}) {this.endpoints=endpoints;this.state=null;this.topology=null;this.demo=null;
    this.pending=new Map();this.scenario='SCN-RUNTIME';this.context={elapsed:0,incident:'none',incident_at:0,seed:42};}
  setScenario(id){this.scenario=id;this.state=null;this.demo=null;this.topology=null;}
  get short(){return this.scenario==='SCN-SHORT';}
  get runtime(){return this.scenario==='SCN-RUNTIME';}
  once(key,task) {if(this.pending.has(key))return this.pending.get(key);
    const promise=Promise.resolve().then(task).finally(()=>this.pending.delete(key));this.pending.set(key,promise);return promise;}
  async getTopology() {if(this.topology)return this.topology;
    return this.once('topology',async()=>this.topology=normalizeTopology(await requestJson(this.runtime?'/api/runtime/topology':'/api/topology')));}
  async getState({elapsed=0,incident='none',incident_at=0,seed=42}={}) {
    this.context={elapsed,incident,incident_at,seed};
    const path=this.runtime?'/api/runtime/state':this.short?'/api/dashboard/short/state':'/api/v2/state?'+query(this.context);
    return this.once(path,async()=>this.state=normalizeState(await requestJson(path)));}
  async getDemoSnapshot({elapsed=0,incident='none',incident_at=0}={}) {
    return this.demo=await requestJson('/demo/snapshot?'+query({elapsed,incident,incident_at}));}
  getTrainDetails(trainId) {return this.state?.trains.find(train=>train.train_id===trainId)??null;}
  async getStationArrivals(stationId) {
    if(this.endpoints.stationArrivals) return normalizeStationArrivals(await requestJson(this.endpoints.stationArrivals+'?'+query({station_id:stationId})),stationId);
    const path=this.runtime?`/api/runtime/stations/${encodeURIComponent(stationId)}/arrivals`:
      this.short?`/api/dashboard/short/stations/${encodeURIComponent(stationId)}/arrivals`:
      `/api/dashboard/stations/${encodeURIComponent(stationId)}/arrivals?`+query({
        elapsed_s:this.context.elapsed,incident:this.context.incident,incident_at_s:this.context.incident_at,seed:this.context.seed});
    return normalizeStationArrivals(await requestJson(path),stationId);
  }
  async getDispatchPlan({elapsed_s=0,incident='none',incident_at_s=0,seed=42}={}) {
    if(this.endpoints.dispatchPlan) {
      const raw=await requestJson(this.endpoints.dispatchPlan,{method:'POST',body:{elapsed_s,incident,incident_at_s,seed}});
      return normalizeDispatchPlan({...raw,source_type:raw.source_type??this.state?.source_type});
    }
    if(this.runtime)return normalizeDispatchPlan(await requestJson('/api/runtime/plan',{timeoutMs:15000}));
    if(this.short)return normalizeDispatchPlan(await requestJson('/api/dashboard/short/plan',{timeoutMs:15000}));
    return normalizeDispatchPlan(await requestJson('/api/dashboard/plan',{
      method:'POST',body:{elapsed_s,incident,incident_at_s,seed},timeoutMs:15000}));
  }
  async getCompareResult() {
    if(this.runtime)return unavailable('Runtime comparison is shown in decision alternatives');
    const path=this.endpoints.compare??(this.short?'/api/dashboard/short/compare':
      '/api/dashboard/compare?'+query({elapsed_s:this.context.elapsed,incident:this.context.incident,
        incident_at_s:this.context.incident_at,seed:this.context.seed}));
    return normalizeCompareResult(await requestJson(path,{timeoutMs:20000}));
  }
  async getSpeedAdvice(trainId) {
    if(this.runtime)return normalizeSpeedAdvice(await requestJson(`/api/runtime/trains/${encodeURIComponent(trainId)}/speed-profile`));
    const path=this.endpoints.speedAdvice?.replace('{train_id}',encodeURIComponent(trainId))??
      (this.short?`/api/dashboard/short/trains/${encodeURIComponent(trainId)}/speed-advice`:
        `/api/dashboard/trains/${encodeURIComponent(trainId)}/speed-advice?`+query({
          elapsed_s:this.context.elapsed,incident:this.context.incident,incident_at_s:this.context.incident_at,seed:this.context.seed}));
    const raw=await requestJson(path);
    return normalizeSpeedAdvice({...raw,source_type:raw.source_type??this.state?.source_type});
  }
  async getCascade(trainId) {
    if(this.runtime)return unavailable('No verified 28-train connection graph');
    const path=this.endpoints.cascade??(this.short?'/api/dashboard/short/cascade':null);
    return path?normalizeCascade(await requestJson(path+'?'+query({train_id:trainId}))):
      unavailable('No validated connection graph for the full timetable');
  }
  async getQualityIndex() {if(this.endpoints.quality)return normalizeQualityIndex(await requestJson(this.endpoints.quality));
    if(this.runtime)return normalizeQualityIndex(await requestJson('/api/runtime/health-index'));
    if(this.short)return normalizeQualityIndex(await requestJson('/api/dashboard/short/quality',{timeoutMs:20000}));
    return this.demo?.quality?normalizeQualityIndex({...this.demo.quality,source_type:'DEMO'}):unavailable('Quality data unavailable');}
  async runWhatIf(request) {
    if(this.runtime)return unavailable('Use decision preview for a fork of the current runtime');
    const path=this.endpoints.whatIf??(this.short?'/api/dashboard/short/what-if':null);
    return path?normalizeWhatIf(await requestJson(path,{method:'POST',body:request,timeoutMs:30000})):
      unavailable('Full timetable counterfactual cannot be executed with the current station-capable fork');
  }
  async submitHumanDecision(choice,{elapsed_s=0,incident='none',incident_at_s=0,seed=42}={}) {
    if(this.runtime)return unavailable('Use validated runtime alternatives');
    if(this.short)return unavailable('Human decision not defined for short route');
    return {...await requestJson('/dispatch/decision',{method:'POST',body:{choice,elapsed_s,incident,incident_at_s,seed},timeoutMs:15000}),
      source_type:'DEMO'};}
  async setControl(running,speed){return requestJson('/api/runtime/control',{method:'POST',body:{running,speed}});}
  async resetRuntime(){return normalizeState(await requestJson('/api/runtime/reset',{method:'POST'}));}
  async createIncident(type,resource_id,duration_min){const state=this.state;
    const raw=await requestJson('/api/runtime/incidents',{method:'POST',body:{type,resource_id,duration_min,
      run_id:state.run_id,snapshot_version:state.snapshot_version}});
    this.state=normalizeState(raw.state);return {...raw,state:this.state};}
  async analyzeRuntime(){return requestJson('/api/runtime/analysis',{timeoutMs:30000});}
  async previewRuntime(option_id,horizon_minutes=20){return requestJson('/api/runtime/preview',{method:'POST',timeoutMs:30000,
    body:{option_id,horizon_minutes,run_id:this.state.run_id,snapshot_version:this.state.snapshot_version}});}
  async applyRuntime(option_id){return requestJson('/api/runtime/apply',{method:'POST',timeoutMs:30000,
    body:{option_id,run_id:this.state.run_id,snapshot_version:this.state.snapshot_version}});}
  async historyRuntime(){return requestJson('/api/runtime/history');}
  async replayRuntime(at){return requestJson('/api/runtime/replay?'+query({at}));}
}
