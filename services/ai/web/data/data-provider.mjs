import {LiveProvider} from './live-provider.mjs';
import {MockProvider} from './mock-provider.mjs';

export class DataProvider {
  constructor({mode='LIVE',endpoints={}}={}) {this.live=new LiveProvider(endpoints);this.mock=new MockProvider();this.setMode(mode);}
  setMode(mode){if(!['LIVE','MOCK'].includes(mode))throw Error('Unknown data mode');this.mode=mode;this.active=mode==='LIVE'?this.live:this.mock;}
  getState(context){return this.active.getState(context);}
  getTopology(){return this.active.getTopology();}
  getTrainDetails(trainId){return this.active.getTrainDetails(trainId);}
  getStationArrivals(stationId){return this.active.getStationArrivals(stationId);}
  getDispatchPlan(context){return this.active.getDispatchPlan(context);}
  getCompareResult(){return this.active.getCompareResult();}
  getSpeedAdvice(trainId){return this.active.getSpeedAdvice(trainId);}
  getCascade(trainId){return this.active.getCascade(trainId);}
  getQualityIndex(){return this.active.getQualityIndex();}
  runWhatIf(request){return this.active.runWhatIf(request);}
  submitHumanDecision(choice,context){return this.active.submitHumanDecision(choice,context);}
}
