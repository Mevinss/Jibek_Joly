import {DataProvider} from './data/data-provider.mjs';
import {delayBand,sourceType,unavailable,normalizeState} from './data/adapters.mjs';
import {requestJson} from './data/api-client.mjs';

const $=id=>document.getElementById(id);
const esc=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const provider=new DataProvider({mode:'LIVE',endpoints:window.JibekJolyApiEndpoints||{}});
const ui={mode:'LIVE',lang:localStorage.getItem('turkisib-language')||'ru',theme:localStorage.getItem('turkisib-theme')||'light',
  topology:null,state:null,demo:null,selectedTrain:null,selectedStation:'AST',city:'ASTANA',
  incident:'none',incidentAt:0,elapsed:0,speed:1,playing:true,view:'map',map:null,mapReady:false,mapFailed:false,
  stream:null,poll:null,staleClock:null,lastReceived:0,lastElapsed:-1,generation:0,
  plan:null,compare:null,eco:null,cascade:null,quality:null,whatIf:null,arrivals:null,
  timer:null,timerLeft:20,decisionPending:false,drawerOpener:null,events:[],affectedResources:[],connectionStatus:'CONNECTING',
  analysis:null,preview:null,selectedOption:null,previewMap:false,replayState:null,replayMap:false};
let cityData=null;
const T=(key,vars={})=>window.i18next?.t(key,vars)||key;
const n=(value,digits=0)=>value==null||!Number.isFinite(Number(value))?'—':Number(value).toLocaleString(ui.lang==='kk'?'kk-KZ':'ru-RU',{maximumFractionDigits:digits});
const when=value=>value&&Number.isFinite(Date.parse(value))?new Date(value).toLocaleTimeString(ui.lang==='kk'?'kk-KZ':'ru-RU',{timeZone:'Asia/Qyzylorda',hour:'2-digit',minute:'2-digit',hour12:false}):T('dPending');
const badge=(element,value)=>{element.textContent=value;element.dataset.source=sourceType(value,'UNAVAILABLE');};
const label=(source)=>T('dSource_'+sourceType(source));
const empty=(key='dUnavailable')=>`<p class="empty">${esc(T(key))}</p>`;
const context=()=>({elapsed_s:ui.elapsed,incident:ui.incident,incident_at_s:ui.incidentAt,seed:ui.state?.seed??42});
const stationName=id=>ui.topology?.stations.find(s=>s.station_id===id)?.name||id||'—';
const train=id=>ui.state?.trains.find(row=>row.train_id===id);
const selected=()=>train(ui.selectedTrain);
const block=id=>ui.state?.blocks.find(row=>row.block_id===id);
const sourceBadge=(id,source)=>badge($(id),source);
const error=message=>{$('global-error').textContent=message;$('global-error').hidden=false;};
const clearError=()=>{$('global-error').hidden=true;$('global-error').textContent='';};
const event=(key,source='DEMO')=>{ui.events.unshift({key,at:ui.state?.virtual_time||ui.demo?.ts||null,source});ui.events=ui.events.slice(0,8);renderTimeline();};

async function initializeLanguage(){
  const [ru,kk]=await Promise.all(['/locales/dashboard-ru.json','/locales/dashboard-kk.json']
    .map(path=>requestJson(path)));
  await window.i18next.init({lng:ui.lang,fallbackLng:'ru',resources:{ru:{translation:ru},kk:{translation:kk}},interpolation:{escapeValue:false}});
  $('language').value=ui.lang;applyLanguage();
}
function applyLanguage(){
  document.documentElement.lang=ui.lang;
  document.querySelectorAll('[data-i18n]').forEach(element=>{element.textContent=T(element.dataset.i18n);});
  $('kk-review').hidden=ui.lang!=='kk';
  $('play').textContent=T(ui.playing?'dPause':'dPlay');
  $('connection').textContent=T('dConnection_'+ui.connectionStatus);
  $('synthetic-badge').textContent=T(provider.live.short&&ui.mode==='LIVE'?'dShortSynthetic':'dSynthetic');
  applyScenarioCopy();
  renderCities();renderAll();
}
function applyScenarioCopy(){const runtime=ui.mode==='LIVE'&&provider.live.runtime;
  document.querySelector('[data-i18n="dHumanBoundary"]').textContent=T(runtime?'dRuntimeHumanBoundary':'dHumanBoundary');
  document.querySelector('[data-i18n="dCompareBoundary"]').textContent=T(runtime?'dRuntimeCompareBoundary':'dCompareBoundary');
  document.querySelector('[data-i18n="dWhatIf"]').textContent=T(runtime?'dRuntimeWhatIf':'dWhatIf');
  $('whatif-form').querySelector('button[type=submit]').textContent=T(runtime?'dRuntimeInject':'dRunWhatIf');
  document.querySelector('.human-panel .badge').textContent=T(runtime?'dRuntimeSimulationBadge':'dDemoTimer');
  $('preview-decision').textContent=T('dRuntimePreview');
  $('apply-decision').textContent=T('dRuntimeApply');
  $('preview-map').textContent=T(ui.previewMap?'dRuntimeLiveMap':'dRuntimePreviewMap');
}
function applyTheme(){document.documentElement.dataset.theme=ui.theme;localStorage.setItem('turkisib-theme',ui.theme);
  if(ui.mapReady)ui.map.setPaintProperty('paper','background-color',getComputedStyle(document.documentElement).getPropertyValue('--surface2').trim());}
function setConnection(status){
  ui.connectionStatus=status;
  const el=$('connection');el.textContent=T('dConnection_'+status);el.dataset.source=status==='ONLINE'?'RUNTIME':status==='MOCK'?'MOCK':'UNAVAILABLE';
  if(status==='OFFLINE')error(ui.mode==='LIVE'?T('dLiveUnavailable'):T('dMockUnavailable'));
}
function stopPlayback(){ui.generation++;ui.stream?.close();ui.stream=null;clearInterval(ui.poll);ui.poll=null;clearInterval(ui.staleClock);ui.staleClock=null;}
async function startMode(mode){
  stopPlayback();stopTimer();clearError();ui.mode=mode;provider.setMode(mode);$('data-mode').value=mode;
  const generation=ui.generation;
  if(mode==='MOCK'&&['SCN-SHORT','SCN-RUNTIME'].includes($('scenario').value))$('scenario').value='SCN-ALL';
  if(mode==='LIVE'&&!['SCN-RUNTIME','SCN-ALL','SCN-SHORT'].includes($('scenario').value))$('scenario').value='SCN-RUNTIME';
  provider.live.setScenario($('scenario').value);
  const short=mode==='LIVE'&&provider.live.short;
  const runtime=mode==='LIVE'&&provider.live.runtime;
  ui.playing=mode==='LIVE'&&!short&&!runtime;
  $('play').textContent=T(ui.playing?'dPause':'dPlay');
  for(const id of ['incident','speed','play'])$(id).disabled=short||(runtime&&id==='incident');
  document.querySelectorAll('[data-choice]').forEach(button=>{button.disabled=short||runtime;button.hidden=runtime;});
  $('runtime-decisions').hidden=!runtime;$('legacy-timer').hidden=runtime;
  applyScenarioCopy();
  $('mode-badge').textContent=runtime?'API LIVE · 28 TRAIN SIMULATOR':short?'API LIVE · 3 TRAIN DEMO':mode==='LIVE'?'API LIVE · 28 TRAIN TIMETABLE':'MOCK · KZ SYNTHETIC';
  $('synthetic-badge').textContent=T(short?'dShortSynthetic':'dSynthetic');
  $('mode-badge').dataset.source=mode==='MOCK'?'MOCK':'DEMO';
  ui.topology=null;ui.state=null;ui.demo=null;ui.plan=null;ui.compare=null;ui.eco=null;ui.cascade=null;
  ui.arrivals=null;ui.quality=null;ui.whatIf=null;ui.analysis=null;ui.preview=null;ui.selectedOption=null;ui.previewMap=false;ui.replayState=null;ui.replayMap=false;
  ui.elapsed=0;ui.lastElapsed=-1;ui.incident='none';ui.incidentAt=0;
  ui.lastQualityFetch=0;
  $('human-status').textContent='';$('human-pair').textContent=T('dNoPair');$('timer').textContent='20';
  $('last-update').textContent='—';
  $('incident').value='none';setConnection(mode==='MOCK'?'MOCK':'CONNECTING');renderAll();
  try {
    const [topology,state]=await Promise.all([provider.getTopology(),provider.getState(mode==='LIVE'?{
      elapsed:0,incident:'none',incident_at:0,seed:42}:undefined)]);
    if(generation!==ui.generation||mode!==ui.mode)return;
    ui.topology=topology;ui.state=state;ui.selectedTrain=state.trains.find(t=>t.train_id===ui.selectedTrain)?.train_id||state.trains[0]?.train_id||null;
    if(short){ui.city='BURABAY';ui.selectedStation='BOR';
      const start=state.virtual_time?.slice(0,16);if(start)$('whatif-form').elements.start_time.value=start;
    }
    $('whatif-form').elements.start_time.readOnly=short||runtime;
    $('whatif-form').elements.start_time.required=!runtime;
    $('whatif-form').elements.duration_min.max=short||runtime?'60':'240';
    if(runtime&&state.virtual_time)$('whatif-form').elements.start_time.value=state.virtual_time.slice(0,16);
    updateTrainOptions();updateWhatIfResources();renderCities();renderAll();
    await Promise.allSettled([loadArrivals(),loadComparison(),loadEcoAndCascade(),loadQuality()]);
    if(generation!==ui.generation||mode!==ui.mode)return;
    if(runtime){ui.playing=state.running===true;ui.speed=state.speed||1;$('speed').value=String(ui.speed);
      $('play').textContent=T(ui.playing?'dPause':'dPlay');ui.lastReceived=Date.now();
      setConnection(ui.playing?'ONLINE':'PAUSED');await Promise.allSettled([runPlan(),loadRuntimeAnalysis(),loadRuntimeHistory()]);connect();}
    else if(short){ui.lastReceived=Date.now();setConnection('ONLINE');await runPlan();}
    else if(mode==='LIVE'){
      const demo=await provider.live.getDemoSnapshot({elapsed:0});ui.demo=demo;ui.lastReceived=Date.now();ui.elapsed=demo.elapsed_s;
      if(generation!==ui.generation||mode!==ui.mode)return;
      renderAll();if(ui.playing)connect();else setConnection('PAUSED');
      void runPlan();
    } else {setConnection('MOCK');await runPlan();}
  }catch(cause){if(generation!==ui.generation||mode!==ui.mode)return;
    setConnection('OFFLINE');error(T(mode==='MOCK'?'dMockUnavailable':'dLiveUnavailable')+' · '+cause.message);}
}

function connect(){
  stopPlayback();if(ui.mode!=='LIVE'||provider.live.short)return;
  const generation=ui.generation;
  if(provider.live.runtime){
    const stream=new EventSource('/api/runtime/stream');ui.stream=stream;
    stream.addEventListener('state',message=>{
      try{acceptRuntimeFrame(JSON.parse(message.data),generation);}catch(cause){error(cause.message);}
    });
    stream.onerror=()=>{if(generation===ui.generation)setConnection('OFFLINE');};
    return;
  }
  if(!ui.playing)return;
  if(ui.speed===60){
    ui.poll=setInterval(async()=>{
      if(generation!==ui.generation)return;
      try {const frame=await provider.live.getDemoSnapshot({elapsed:Math.min(86400,ui.elapsed+60),incident:ui.incident,incident_at:ui.incidentAt});
        await acceptDemoFrame(frame,generation);}catch{setConnection('OFFLINE');}
    },1000);
  }else{
    const query=new URLSearchParams({elapsed:ui.elapsed,speed:String(ui.speed),incident:ui.incident,incident_at:ui.incidentAt});
    const stream=new EventSource('/demo/stream?'+query);
    ui.stream=stream;
    stream.addEventListener('state',async message=>{
      try{await acceptDemoFrame(JSON.parse(message.data),generation);}catch(cause){error(cause.message);}
    });
    stream.onerror=()=>{if(generation===ui.generation)setConnection('OFFLINE');};
  }
  ui.staleClock=setInterval(()=>{
    if(generation!==ui.generation||!ui.playing)return;
    const age=Date.now()-ui.lastReceived;
    if(age>8000)setConnection('OFFLINE');else if(age>3500)setConnection('STALE');
  },1000);
}
function acceptRuntimeFrame(frame,generation){
  if(generation!==ui.generation||!frame?.state)return;
  const state=normalizeState(frame.state),current=ui.state;
  if(current?.run_id===state.run_id&&state.snapshot_version<current.snapshot_version)return;
  ui.lastReceived=Date.now();ui.playing=state.running===true;
  $('play').textContent=T(ui.playing?'dPause':'dPlay');$('last-update').textContent=when(frame.sent_at);
  setConnection(ui.playing?'ONLINE':'PAUSED');
  if(current?.snapshot_id===state.snapshot_id)return;
  provider.live.state=state;ui.state=state;
  if(current?.run_id!==state.run_id||current?.snapshot_version!==state.snapshot_version){
    ui.analysis=null;ui.preview=null;ui.selectedOption=null;ui.previewMap=false;ui.replayMap=false;ui.plan=null;ui.compare=null;
    ui.quality=null;ui.arrivals=null;renderRuntimeDecisions();
    void loadArrivals();void loadQuality();
  }
  renderAll();
}
async function acceptDemoFrame(frame,generation){
  if(generation!==ui.generation||!frame||!Number.isFinite(frame.elapsed_s)||frame.elapsed_s<=ui.lastElapsed)return;
  ui.demo=frame;ui.elapsed=frame.elapsed_s;ui.lastElapsed=frame.elapsed_s;ui.lastReceived=Date.now();
  provider.live.demo=frame;setConnection('ONLINE');clearError();
  $('virtual-time').textContent=when(frame.ts);$('last-update').textContent=when(frame.sent_at||new Date().toISOString());
  const snapshot=await provider.getState({elapsed:frame.elapsed_s,incident:ui.incident,incident_at:ui.incidentAt,seed:ui.state?.seed??42});
  if(generation!==ui.generation||snapshot.snapshot_version<(ui.state?.snapshot_version??-1))return;
  ui.state=snapshot;renderAll();
  if(ui.selectedStation)void loadArrivals();
  void loadQuality();
}

const geometryFor=id=>ui.topology?.blocks.find(row=>row.block_id===id)?.geometry;
const mapState=()=>ui.replayMap&&ui.replayState?.run_id===ui.state?.run_id?ui.replayState:
  ui.previewMap&&ui.preview?.snapshot_id===ui.state?.snapshot_id?ui.preview.projected:ui.state;
function trainCoordinates(row){
  if(Array.isArray(row.position_coordinates))return row.position_coordinates;
  const line=geometryFor(row.current_block_id||row.position_block_id)?.coordinates;
  if(!line?.length){const station=ui.topology?.stations.find(item=>item.station_id===
      (row.status==='completed'?row.destination_station_id:row.origin_station_id));
    if(!Array.isArray(station?.coordinates))return null;
    // Stable visual separation for scheduled trains at one station; not track position.
    const hash=[...(row.train_id||'')].reduce((value,char)=>(value*31+char.charCodeAt(0))>>>0,0);
    const angle=(hash%360)*Math.PI/180,radius=.035+(hash%4)*.012;
    return [station.coordinates[0]+Math.cos(angle)*radius,station.coordinates[1]+Math.sin(angle)*radius];}
  const start=line[0],end=line.at(-1),fraction=Math.max(0,Math.min(1,Number(row.block_progress_0_1)||0));
  const ratio=row.direction==='reverse'?1-fraction:fraction;
  return [start[0]+(end[0]-start[0])*ratio,start[1]+(end[1]-start[1])*ratio];
}
function incidentCoordinate(incident){
  if(incident.block_id){const line=geometryFor(incident.block_id)?.coordinates;if(line?.length)return line[Math.floor(line.length/2)];}
  if(incident.signal_id){const signal=ui.topology?.signals.find(row=>row.signal_id===incident.signal_id);const line=geometryFor(signal?.block_id)?.coordinates;if(line?.length)return line[0];}
  if(incident.switch_id){const switchState=ui.topology?.switches.find(row=>row.switch_id===incident.switch_id);return ui.topology?.stations.find(row=>row.station_id===switchState?.station_id)?.coordinates;}
  if(incident.train_id)return trainCoordinates(train(incident.train_id)||{});
  return null;
}
const feature=(coordinates,properties,kind='Point')=>({type:'Feature',geometry:{type:kind,coordinates},properties});
const collection=features=>({type:'FeatureCollection',features});
function mapData(){
  if(!ui.topology)return null;
  const display=mapState(),byBlock=new Map((display?.blocks||[]).map(row=>[row.block_id,row]));
  const recommended=new Set((ui.plan?.reservations||[]).filter(row=>row.train_id===ui.selectedTrain&&row.resource_type==='block').map(row=>row.resource_id));
  const blocks=ui.topology.blocks.filter(row=>row.geometry?.coordinates).map(row=>feature(row.geometry.coordinates,{
    id:row.block_id,conflict:!!byBlock.get(row.block_id)?.state_conflict,
    closed:!!byBlock.get(row.block_id)?.closed,
    selected:!!selected()?.route?.includes(row.block_id),
    recommended:recommended.has(row.block_id),
    affected:ui.affectedResources.includes(row.block_id)},'LineString'));
  const stations=ui.topology.stations.filter(row=>Array.isArray(row.coordinates)).map(row=>feature(row.coordinates,{id:row.station_id,name:row.name}));
  const trains=(display?.trains||[]).map(row=>({row,coordinates:trainCoordinates(row)}))
    .filter(item=>item.coordinates).map(item=>feature(item.coordinates,{id:item.row.train_id,selected:item.row.train_id===ui.selectedTrain,
      category:item.row.category,delay:item.row.delay_min}));
  const signals=ui.topology.signals.map(row=>({row,coordinates:geometryFor(row.block_id)?.coordinates?.[0]}))
    .filter(item=>item.coordinates).map(item=>feature(item.coordinates,{id:item.row.signal_id,
      failed:display?.signals.find(s=>s.signal_id===item.row.signal_id)?.failed===true,
      aspect:display?.signals.find(s=>s.signal_id===item.row.signal_id)?.aspect||'UNKNOWN'}));
  const switches=ui.topology.switches.map(row=>({row,coordinates:ui.topology.stations.find(s=>s.station_id===row.station_id)?.coordinates}))
    .filter(item=>item.coordinates).map(item=>feature(item.coordinates,{id:item.row.switch_id,
      failed:display?.switches.find(s=>s.switch_id===item.row.switch_id)?.failed===true,
      locked:display?.switches.find(s=>s.switch_id===item.row.switch_id)?.locked===true,
      position:display?.switches.find(s=>s.switch_id===item.row.switch_id)?.position||'UNKNOWN'}));
  const incidents=(display?.active_incidents||[]).map(row=>({row,coordinates:incidentCoordinate(row)}))
    .filter(item=>item.coordinates).map(item=>feature(item.coordinates,{id:item.row.incident_id,type:item.row.type}));
  return {blocks,stations,trains,signals,switches,incidents};
}
function addMapSource(name,data){ui.map.addSource(name,{type:'geojson',data:collection(data)});}
function initializeMap(){
  if(ui.map)return true;
  if(ui.mapFailed||!window.maplibregl||!window.maplibregl.supported?.())return false;
  try{
    ui.map=new window.maplibregl.Map({container:'map',style:{version:8,sources:{},layers:[{id:'paper',type:'background',
      paint:{'background-color':getComputedStyle(document.documentElement).getPropertyValue('--surface2').trim()}}]},
      center:[73.5,48.8],zoom:5,attributionControl:false});
    ui.map.on('load',()=>{
      ui.mapReady=true;const data=mapData();if(!data)return;
      for(const [name,features] of Object.entries(data))addMapSource('dash-'+name,features);
      ui.map.addLayer({id:'dash-blocks-line',type:'line',source:'dash-blocks',paint:{'line-color':['case',['get','conflict'],'#c0392b',['get','closed'],'#566070',['get','affected'],'#965900',['get','recommended'],'#176c47',['get','selected'],'#1d5fa8','#b9c3ce'],
        'line-width':['case',['get','conflict'],7,['get','selected'],5,3]}});
      ui.map.addLayer({id:'dash-station-points',type:'circle',source:'dash-stations',paint:{'circle-radius':6,'circle-color':'#fff','circle-stroke-color':'#1d5fa8','circle-stroke-width':2}});
      ui.map.addLayer({id:'dash-switch-points',type:'circle',source:'dash-switches',paint:{'circle-radius':4,'circle-color':['case',['get','failed'],'#c0392b',['get','locked'],'#965900',['==',['get','position'],'UNKNOWN'],'#566070','#176c47']}});
      ui.map.addLayer({id:'dash-signal-points',type:'circle',source:'dash-signals',paint:{'circle-radius':3,'circle-color':['case',['get','failed'],'#c0392b',['==',['get','aspect'],'STOP'],'#c0392b',['==',['get','aspect'],'CLEAR'],'#176c47',['==',['get','aspect'],'CAUTION'],'#965900','#566070']}});
      ui.map.addLayer({id:'dash-train-points',type:'circle',source:'dash-trains',paint:{'circle-radius':['case',['get','selected'],8,5],
        'circle-color':['case',['get','selected'],'#c0392b','#1d5fa8'],'circle-stroke-color':'#fff','circle-stroke-width':2}});
      ui.map.addLayer({id:'dash-incident-points',type:'circle',source:'dash-incidents',paint:{'circle-radius':8,'circle-color':'#c0392b','circle-stroke-color':'#fff','circle-stroke-width':2}});
      ui.map.on('click','dash-station-points',e=>chooseStation(e.features[0].properties.id,true));
      ui.map.on('click','dash-train-points',e=>chooseTrain(e.features[0].properties.id,true));
      ui.map.on('click','dash-incident-points',e=>openIncident(e.features[0].properties.id));
      ui.map.on('click','dash-blocks-line',e=>{const id=e.features[0].properties.id;if(block(id)?.state_conflict)openConflict(id);});
      updateMap();
    });
    ui.map.on('error',()=>{if(!ui.mapReady){ui.mapFailed=true;ui.map?.remove();ui.map=null;renderMap();}});
    return true;
  }catch{ui.mapFailed=true;ui.map=null;return false;}
}
function updateMap(){if(!ui.mapReady||ui.view!=='map')return;const data=mapData();if(!data)return;
  for(const [name,features] of Object.entries(data))ui.map.getSource('dash-'+name)?.setData(collection(features));}
function pointSvg(coordinates,mode,stationIndex){
  if(mode==='scheme')return [55+stationIndex*890/Math.max(1,ui.topology.stations.length-1),210];
  return [65+(coordinates[0]-68)*99,30+(54-coordinates[1])*32];
}
function renderSvgMap(){const svg=$('map-svg');if(!ui.topology){svg.innerHTML='';return;}
  const mode=ui.view==='scheme'?'scheme':'map',stations=ui.topology.stations,display=mapState();
  const points=new Map(stations.map((row,index)=>[row.station_id,pointSvg(row.coordinates||[72,48],mode,index)]));
  const bySegment=new Map(ui.topology.segments.map(row=>[row.segment_id,row]));
  const byBlock=new Map((display?.blocks||[]).map(row=>[row.block_id,row]));
  const blocks=ui.topology.blocks.map(row=>{
    let a,b;if(mode==='map'){const line=row.geometry?.coordinates;if(!line?.length)return '';a=pointSvg(line[0],mode,0);b=pointSvg(line.at(-1),mode,0);}
    else {const segment=bySegment.get(row.segment_id),ids=ui.topology.blocks.filter(item=>item.segment_id===row.segment_id);
      const start=points.get(segment?.from_station_id),end=points.get(segment?.to_station_id);if(!start||!end)return '';
      const index=ids.findIndex(item=>item.block_id===row.block_id);a=[start[0]+(end[0]-start[0])*index/ids.length,210];b=[start[0]+(end[0]-start[0])*(index+1)/ids.length,210];}
    const state=byBlock.get(row.block_id),recommended=(ui.plan?.reservations||[]).some(item=>item.train_id===ui.selectedTrain&&item.resource_id===row.block_id),
      kind=state?.state_conflict?'conflict':state?.closed?'closed':recommended?'recommended':'';
    return `<line class="route ${kind}" x1="${a[0]}" y1="${a[1]}" x2="${b[0]}" y2="${b[1]}" data-block="${esc(row.block_id)}"/>`;}).join('');
  const stationMarks=stations.map(row=>{const p=points.get(row.station_id);return `<g role="button" tabindex="0" data-station="${esc(row.station_id)}" aria-label="${esc(row.name)}"><circle class="station" cx="${p[0]}" cy="${p[1]}" r="8"/><text x="${p[0]+10}" y="${p[1]-11}">${esc(row.name)}</text></g>`;}).join('');
  const trainMarks=(display?.trains||[]).map(row=>{const coords=trainCoordinates(row);if(!coords)return '';
    let p;if(mode==='map')p=pointSvg(coords,mode,0);else{const seg=bySegment.get(row.current_segment_id),start=points.get(seg?.from_station_id),end=points.get(seg?.to_station_id);
      if(!start||!end){const station=points.get(row.status==='completed'?row.destination_station_id:row.origin_station_id);
        if(!station)return '';const hash=[...row.train_id].reduce((value,char)=>(value*31+char.charCodeAt(0))>>>0,0);
        p=[station[0]+(hash%7-3)*6,station[1]+(Math.floor(hash/7)%5-2)*6];}
      else {const ids=ui.topology.blocks.filter(item=>item.segment_id===row.current_segment_id),index=ids.findIndex(item=>item.block_id===(row.current_block_id||row.position_block_id));
        const local=Number(row.block_progress_0_1||0),fraction=(index+(row.direction==='reverse'?1-local:local))/Math.max(1,ids.length);
        p=[start[0]+(end[0]-start[0])*fraction,210];}}
    return `<g role="button" tabindex="0" data-train="${esc(row.train_id)}" aria-label="${esc(row.train_id)}"><circle class="train" cx="${p[0]}" cy="${p[1]}" r="${row.train_id===ui.selectedTrain?8:5}"/><title>${esc(row.train_id)}</title></g>`;}).join('');
  const incidents=(display?.active_incidents||[]).map(row=>{const coords=incidentCoordinate(row);if(!coords)return '';
    const p=mode==='map'?pointSvg(coords,mode,0):points.get(ui.selectedStation)||[500,210];
    return `<g role="button" tabindex="0" data-incident="${esc(row.incident_id)}"><circle class="incident" cx="${p[0]}" cy="${p[1]-18}" r="7"/><title>${esc(row.type)}</title></g>`;}).join('');
  const signals=ui.topology.signals.filter(row=>display?.signals.find(item=>item.signal_id===row.signal_id)?.failed||
    selected()?.current_block_id===row.block_id).map(row=>{const coords=geometryFor(row.block_id)?.coordinates?.[0];if(!coords)return '';
      const signal=display?.signals.find(item=>item.signal_id===row.signal_id),p=mode==='map'?pointSvg(coords,mode,0):[500,195];
      const aspect=signal?.failed?'failed':signal?.aspect==='CLEAR'?'clear':signal?.aspect==='STOP'?'stop':signal?.aspect==='CAUTION'?'caution':'unknown';
      return `<circle class="signal ${aspect}" cx="${p[0]}" cy="${p[1]}" r="4"><title>${esc(row.signal_id)} · ${esc(signal?.aspect||T('dUnknown'))}</title></circle>`;}).join('');
  const switches=ui.topology.switches.map(row=>{const p=points.get(row.station_id);if(!p)return '';return `<rect class="switch" x="${p[0]-3}" y="${p[1]+12}" width="6" height="6"><title>${esc(row.switch_id)}</title></rect>`;}).join('');
  svg.innerHTML=blocks+stationMarks+switches+signals+trainMarks+incidents;
}
function renderMap(){if(!ui.topology)return;
  const mapMode=ui.view==='map'&&initializeMap();
  $('map').hidden=!mapMode;$('map-svg').toggleAttribute('hidden',mapMode);
  $('map-mode').setAttribute('aria-pressed',String(ui.view==='map'));
  $('scheme-mode').setAttribute('aria-pressed',String(ui.view==='scheme'));
  $('map-overlay-note').textContent=ui.replayMap?T('dRuntimeReplayMapNote'):ui.previewMap?T('dRuntimePreviewMapNote'):ui.view==='scheme'?T('dSchemeNote'):mapMode?T('dGeneralized'):T('dOfflineFallback');
  if(mapMode){ui.map.resize();updateMap();}else renderSvgMap();
}

const detail=(name,value)=>`<div class="detail"><small>${esc(name)}</small><strong>${esc(value??'—')}</strong></div>`;
const delay=(value)=>`<span class="delay ${delayBand(value)}">${value==null?'—':`+${n(value,1)} ${esc(T('dMin'))}`}</span>`;
function updateTrainOptions(){const select=$('train-select'),previous=ui.selectedTrain;
  select.replaceChildren(...(ui.state?.trains||[]).map(row=>new Option(`${row.train_id} · ${row.category||'—'}`,row.train_id)));
  if(previous)select.value=previous;
}
function updateWhatIfResources(){
  const type=document.querySelector('#whatif-form [name="incident_type"]').value;
  const rows=type==='TRAIN_DELAY'?ui.state?.trains:type==='SIGNAL_FAILURE'?ui.topology?.signals:
    type==='SWITCH_FAILURE'?ui.topology?.switches:ui.topology?.blocks;
  const key=type==='TRAIN_DELAY'?'train_id':type==='SIGNAL_FAILURE'?'signal_id':
    type==='SWITCH_FAILURE'?'switch_id':'block_id';
  const select=$('whatif-resource'),previous=select.value;
  select.replaceChildren(...(rows||[]).map(row=>new Option(row[key],row[key])));
  if([...select.options].some(option=>option.value===previous))select.value=previous;
}
function renderCities(){if(!ui.topology||!cityData)return;
  const city=$('city'),station=$('station');city.replaceChildren(...cityData.cities.map(row=>new Option(ui.lang==='kk'?row.name_kk:row.name_ru,row.city_id)));
  if(!cityData.cities.some(row=>row.city_id===ui.city))ui.city=cityData.cities[0]?.city_id;
  city.value=ui.city;const selectedCity=cityData.cities.find(row=>row.city_id===ui.city);
  const stationIds=selectedCity?.station_ids||[];
  station.replaceChildren(...stationIds.map(id=>new Option(stationName(id),id)));
  if(!stationIds.includes(ui.selectedStation))ui.selectedStation=stationIds[0]||null;
  station.value=ui.selectedStation;
}
function renderConflict(){const target=$('conflict-content');if(!ui.state){target.innerHTML=empty('dLoading');return;}
  sourceBadge('conflict-source',ui.mode==='MOCK'?'MOCK':'DEMO');
  const conflicts=ui.state.blocks.filter(row=>row.state_conflict);
  if(!conflicts.length){const incident=provider.live.runtime?ui.state.active_incidents.at(-1):null;
    target.innerHTML=incident?`<p><strong>${esc(incident.type)}</strong> · ${esc(incident.train_id||incident.block_id||incident.signal_id||incident.switch_id||'')}</p><p class="caption">${esc(T('dNoConflict'))}</p>`:empty('dNoConflict');return;}
  const current=conflicts[0],ids=current.occupied_train_ids.slice(0,2);
  target.innerHTML=`<p class="conflict-flag">⚠ ${esc(T('dConflict'))} · ${conflicts.length}</p>
    <div class="conflict-trains">${ids.map(id=>{const row=train(id);return `<button type="button" data-train="${esc(id)}"><strong>${esc(id)}</strong><span>${esc(row?.category||'—')} · ${esc(row?.direction||'—')}</span>${delay(row?.delay_min)}</button>`;}).join('')}</div>
    <p class="conflict-resource">${esc(T('dResource'))}: <button type="button" data-block="${esc(current.block_id)}">${esc(current.block_id)}</button></p>
    <p class="caption">${esc(T('dConflictBoundary'))}</p>`;
}
function renderPlan(){const target=$('plan-content');if(!ui.plan){target.innerHTML=empty('dRunToSeePlan');return;}
  if(ui.plan.status==='UNAVAILABLE'){target.innerHTML=empty('dPlanUnavailable');return;}
  const plan=ui.plan;const validation=plan.validation_status;
  const key={VALIDATED:'dValidated',PARTIALLY_VALIDATED:'dPartiallyValidated',INVALID:'dInvalid',UNAVAILABLE:'dUnavailable'}[validation];
  target.innerHTML=`<p><span class="validation ${validation==='VALIDATED'?'valid':validation==='INVALID'?'invalid':'partial'}">${esc(T(key))}</span>
    <span class="badge" data-source="${esc(plan.source_type)}">${esc(label(plan.source_type))}</span></p>
    <div class="plan-facts">${detail(T('dPolicy'),plan.policy)}${detail(T('dSolverStatus'),plan.solver_status)}
    ${detail(T('dCompute'),plan.solver_wall_time_ms==null?'—':n(plan.solver_wall_time_ms,1)+' ms')}
    ${detail(T('dHolding'),plan.holding_minutes==null?'—':n(plan.holding_minutes,1)+' '+T('dMin'))}</div>
    <details><summary>${esc(T('dTechnical'))}</summary><p class="mono">${esc(T('dPlanId'))}: ${esc(plan.plan_id||'—')}</p>
    <p>${esc(T('dValidationScope'))}: ${esc(plan.validation_scope||'—')}</p>
    <p>${esc(T('dUnverifiedScope'))}: ${esc(plan.unverified_scope.join(', ')||T('dUnknown'))}</p>
    <p>${esc(T('dFallback'))}: ${plan.fallback_used?esc(plan.fallback_reason||T('dYes')):esc(T('dNo'))}</p>
    <p>${esc(T('dRecommendedTrack'))}: ${esc(plan.selected_station_track||T('dNotAssigned'))}</p>
    <p>${esc(T('dReservations'))}: ${n(plan.reservations.length)}</p></details>
    ${plan.fully_validated===true?'':`<p class="caption">${esc(T('dStationUnverified'))}</p>`}`;
}
function renderStationScheme(){const target=$('station-scheme');if(!ui.state||!ui.selectedStation){target.innerHTML=empty();return;}
  const tracks=ui.state.station_tracks.filter(row=>row.station_id===ui.selectedStation);
  target.innerHTML=`<strong>${esc(stationName(ui.selectedStation))}</strong><div>${tracks.length?tracks.map(row=>{
    const status=row.occupancy_source==='UNAVAILABLE'||row.available==null?'UNKNOWN':row.occupied_train_ids?.length?'OCCUPIED':row.available?'FREE':'UNAVAILABLE';
    return `<span class="track-chip ${status.toLowerCase()}">${esc(row.track_id)} · ${esc(T('dTrack_'+status))}</span>`;
  }).join(''):esc(T('dNoTrackData'))}</div>`;
}
function renderArrivals(){sourceBadge('arrival-source',ui.arrivals?.source_type||'UNAVAILABLE');renderStationScheme();
  const body=$('arrivals-body');if(!ui.arrivals){body.innerHTML=`<tr><td colspan="4">${esc(T('dLoading'))}</td></tr>`;return;}
  if(ui.arrivals.status==='UNAVAILABLE'){body.innerHTML=`<tr><td colspan="4">${esc(T('dArrivalsUnavailable'))}</td></tr>`;return;}
  if(!ui.arrivals.arrivals.length){body.innerHTML=`<tr><td colspan="4">${esc(T('dNoArrivals'))}</td></tr>`;return;}
  body.innerHTML=ui.arrivals.arrivals.map(row=>`<tr><td><button type="button" data-train="${esc(row.train_id)}">${esc(row.train_number||row.train_id)}</button><br><small>${esc(row.category||'—')}</small></td>
    <td>${esc(when(row.eta))}<br><small>${esc(T('dScheduled'))}: ${esc(when(row.scheduled_arrival))}</small></td>
    <td>${delay(row.delay_min)}</td><td>${esc(row.track_id||T('dNotAssigned'))}<br><small>${esc(T('dTrack_'+(row.track_status||'UNKNOWN')))}</small></td></tr>`).join('');
}
function trainSignal(row){const signalId=row?.entry_signals?.[Math.max(0,Number(row.block_index||0)+1)];
  return ui.state?.signals.find(signal=>signal.signal_id===signalId)||null;}
function renderTrain(){sourceBadge('train-source',ui.mode==='MOCK'?'MOCK':'DEMO');const target=$('train-details'),row=selected();
  if(!row){target.innerHTML=empty('dSelectTrain');return;}
  const signal=trainSignal(row),speed=row.speed_kmh==null?'—':n(row.speed_kmh,1)+' km/h';
  target.innerHTML=`<div class="details-grid">${detail(T('dCategory'),row.category||'—')}${detail(T('dDirection'),row.direction||'—')}
    ${detail(T('dSpeed'),speed)}${detail(T('dDelay'),row.delay_min==null?'—':'+'+n(row.delay_min,1)+' '+T('dMin'))}
    ${detail(T('dBlock'),row.current_block_id||T('dUnknown'))}${detail(T('dNextStation'),stationName(row.next_station_id))}
    ${detail('ETA',when(row.estimated_arrival))}${detail(T('dScheduled'),when(row.scheduled_arrival))}</div>
    <p class="caption">${esc(T('dRouteProgress'))}: ${n(row.route_progress_0_1==null?null:row.route_progress_0_1*100,1)}% · ${esc(T('dBlockProgress'))}: ${n(row.block_progress_0_1==null?null:row.block_progress_0_1*100,1)}%</p>
    <p class="caption">${esc(T('dSignal'))}: ${esc(signal?.failed?T('dSignalFailed'):signal?.aspect||T('dUnknown'))} · ${esc(T('dDataSource'))}: ${esc(row.source_type||'—')}</p>`;
}
function renderCompare(){sourceBadge('compare-source',ui.compare?.source_type||'UNAVAILABLE');const body=$('compare-body');
  $('compare-scope').textContent=ui.mode==='LIVE'?(provider.live.runtime?T('dRuntimeScope'):provider.live.short?T('dShortScope'):T('dFullNotComparable')):'';
  if(!ui.compare||ui.compare.status==='UNAVAILABLE'){body.innerHTML=`<tr><td colspan="7">${esc(T('dCompareWaiting'))}</td></tr>`;return;}
  body.innerHTML=ui.compare.rows.map(row=>`<tr><td><strong>${esc(row.policy)}</strong></td><td>${n(row.total_delay_min,1)}</td>
    <td>${n(row.incident_delay_min,1)}</td><td>${n(row.conflicts)}</td><td>${row.compute_ms==null?'—':n(row.compute_ms,1)+' ms'}</td>
    <td>${n(row.energy_proxy_units,2)} <small>proxy</small></td><td>${esc(row.validation)}</td></tr>`).join('');
}
function renderSpeedChart(advice){const target=$('speed-chart'),points=advice?.profile_points||[];
  const valid=points.filter(row=>row.distance_km!=null&&row.recommended_speed_kmh!=null);
  if(valid.length<2){target.innerHTML='';return;}
  const maxX=Math.max(1,...valid.map(row=>row.distance_km)),maxY=Math.max(1,...valid.map(row=>row.recommended_speed_kmh),...valid.map(row=>row.speed_limit_kmh||0));
  const xy=row=>[38+row.distance_km/maxX*410,137-row.recommended_speed_kmh/maxY*112];
  const path=valid.map((row,index)=>`${index?'L':'M'}${xy(row).map(value=>value.toFixed(1)).join(' ')}`).join(' ');
  const limits=valid.every(row=>row.speed_limit_kmh!=null)?valid.map((row,index)=>`${index?'L':'M'}${(38+row.distance_km/maxX*410).toFixed(1)} ${(137-row.speed_limit_kmh/maxY*112).toFixed(1)}`).join(' '):null;
  target.innerHTML=`<svg viewBox="0 0 470 170" aria-label="${esc(T('dSpeedChart'))}"><path class="axis" d="M38 20 V137 H450"/>
    <path class="profile" d="${path}"/>${limits?`<path class="limit" d="${limits}"/>`:''}
    <text x="40" y="158">0 km</text><text x="394" y="158">${n(maxX,1)} km</text><text x="40" y="17">km/h</text></svg>
    <p class="caption">● ${esc(T('dRecommended'))} · ┄ ${esc(T('dLimit'))} · ${esc(T('dCurrentSpeed'))}: ${advice.current_speed_kmh==null?'—':n(advice.current_speed_kmh,1)+' km/h'}</p>`;
}
function renderEco(){sourceBadge('eco-source',ui.eco?.source_type||'UNAVAILABLE');const target=$('eco-content');
  if(!ui.eco||ui.eco.status==='UNAVAILABLE'){target.innerHTML=empty('dEcoUnavailable');$('speed-chart').innerHTML='';return;}
  const advice=ui.eco;
  if(advice.status==='LIMIT_ONLY_ILLUSTRATION'){
    target.innerHTML=`<p class="caption">${esc(T('dRuntimeSpeedBoundary'))}</p><div class="table-scroll"><table><thead><tr><th>${esc(T('dSegment'))}</th><th>${esc(T('dLimit'))}</th><th>km</th></tr></thead><tbody>`+
      advice.segments.map(row=>`<tr><td>${esc(row.from_station_id)} → ${esc(row.to_station_id)}</td><td>${n(row.recommended_speed_kmh)} km/h</td><td>${n(row.distance_from_km,1)}–${n(row.distance_to_km,1)}</td></tr>`).join('')+
      '</tbody></table></div>';
    $('speed-chart').innerHTML='';return;
  }
  target.innerHTML=`<div class="eco-stats">${detail(T('dCurrentSpeed'),advice.current_speed_kmh==null?'—':n(advice.current_speed_kmh,1)+' km/h')}
    ${detail(T('dRecommended'),advice.recommended_speed_kmh==null?'—':n(advice.recommended_speed_kmh,1)+' km/h')}
    ${detail(T('dFullStop'),advice.full_stop_avoided==null?T('dUncertain'):T(advice.full_stop_avoided?'dYes':'dNo'))}</div>
    <p>${esc(T('dTargetArrival'))}: ${esc(when(advice.target_arrival))} · ${esc(T('dResourceOpens'))}: ${esc(when(advice.resource_opens))}</p>
    <p>${esc(T('dEnergyProxy'))}: ${n(advice.energy_proxy_before,2)} → ${n(advice.energy_proxy_after,2)} (Δ ${n(advice.energy_proxy_delta,2)} proxy)</p>
    <p class="caption">${esc(advice.reason_code||advice.reason||T('dEcoBoundary'))} · ${esc(T('dEcoBoundary'))}</p>`;
  renderSpeedChart(advice);
}
function renderCascade(){sourceBadge('cascade-source',ui.cascade?.source_type||'UNAVAILABLE');const target=$('cascade-content');
  if(!ui.cascade||ui.cascade.status==='UNAVAILABLE'){target.innerHTML=empty('dCascadeWaiting');$('connections-content').innerHTML='';return;}
  target.innerHTML=`<p>${esc(T('dNetworkEffect'))}: <strong>+${n(ui.cascade.total_added_delay_min,1)} ${esc(T('dMin'))}</strong></p>`+
    ui.cascade.nodes.map((node,index)=>`${index?'<div class="cascade-arrow">↓</div>':''}<div class="cascade-node"><button type="button" data-train="${esc(node.train_id)}">${esc(node.train_id)}</button>
      <strong>+${n(node.added_delay_min,1)} ${esc(T('dMin'))}</strong><small>${esc(node.cause||'—')}</small></div>`).join('');
  $('connections-content').innerHTML=ui.cascade.connections.length?`<h3>${esc(T('dConnections'))}</h3>`+
    ui.cascade.connections.map(row=>`<p>${esc(row.from_train_id)} → ${esc(row.to_train_id)} · ${esc(stationName(row.station_id))} · ${n(row.minimum_transfer_min,1)} ${esc(T('dMin'))}</p>`).join(''):'';
}
function renderQuality(){sourceBadge('quality-source',ui.quality?.source_type||'UNAVAILABLE');const target=$('quality-content');
  if(!ui.quality||ui.quality.status==='UNAVAILABLE'){target.innerHTML=empty('dQualityWaiting');return;}
  target.innerHTML=`<div class="quality-score">${n(ui.quality.score,1)} / 100</div><p class="caption">${esc(T(provider.live.runtime&&ui.mode==='LIVE'?'dRuntimeQualityBoundary':'dQualityBoundary'))}</p>
    <ul class="quality-factors">${ui.quality.factors.map(row=>`<li>${esc(row.key)} · ${n(row.points,1)}</li>`).join('')}</ul>`;
}
function renderWhatIf(){sourceBadge('whatif-source',ui.whatIf?.source_type||'UNAVAILABLE');const target=$('whatif-content');
  if(ui.mode==='LIVE'&&provider.live.runtime){const incident=ui.state?.active_incidents.at(-1);
    sourceBadge('whatif-source',incident?'DEMO':'UNAVAILABLE');
    target.innerHTML=incident?`${detail(T('dIncident'),incident.type)}${detail(T('dResource'),incident.train_id||incident.block_id||incident.signal_id||incident.switch_id||T('dUnknown'))}<p class="caption">${esc(when(incident.at))} · ${esc(ui.state.snapshot_id)}</p>`:empty('dRuntimeWhatIfHint');return;}
  if(!ui.whatIf){target.innerHTML=empty('dWhatIfHint');return;}
  if(ui.whatIf.status==='UNAVAILABLE'){target.innerHTML=empty('dWhatIfWaiting');return;}
  const fields=[['delay_min','dTotalDelay'],['conflicts','dConflicts'],['stops','dStops'],['energy_proxy_units','dEnergyProxy'],['affected_trains','dAffectedTrains']];
  target.innerHTML=`<div class="whatif-result">${[['current','dCurrent'],['what_if','dWhatIf'],['delta','dDelta']].map(([key,title])=>`<div><strong>${esc(T(title))}</strong>
    ${fields.map(([field,name])=>`<small>${esc(T(name))}: ${n(ui.whatIf[key]?.[field],1)}${field==='energy_proxy_units'?' proxy':''}</small>`).join('')}</div>`).join('')}</div>
    <p class="caption">${esc(ui.whatIf.note||T('dWhatIfBoundary'))}</p>`;
}
function renderTimeline(){$('timeline-content').innerHTML=ui.events.length?ui.events.map(row=>`<li><span class="mono">${esc(when(row.at))}</span> · ${esc(T(row.key))} <span class="badge" data-source="${esc(row.source)}">${esc(label(row.source))}</span>${row.replayAt?` <button type="button" data-replay="${esc(row.replayAt)}">${esc(T('dRuntimeReplay'))}</button>`:''}</li>`).join(''):`<li>${esc(T('dNoEvents'))}</li>`;
  $('replay-map').hidden=!ui.replayState;$('replay-map').textContent=T(ui.replayMap?'dRuntimeLiveMap':'dRuntimeReplayMap');
  $('replay-detail').innerHTML=ui.replayState?`<p class="caption">${esc(T('dRuntimeReplayReadOnly'))}</p><div class="details-grid">${detail('snapshot',ui.replayState.snapshot_id)}${detail(T('dTrain'),ui.replayState.trains.length)}${detail(T('dConflicts'),ui.replayState.blocks.filter(row=>row.state_conflict).length)}${detail(T('dIncident'),ui.replayState.active_incidents.length)}</div>`:'';}
function renderTrainGraph(){const target=$('train-graph');sourceBadge('graph-source',ui.mode==='MOCK'?'MOCK':'DEMO');
  if(!ui.state){target.innerHTML=empty('dLoading');return;}
  $('graph-title').textContent=`${T('dRuntimeTrainGraph')} · ${ui.state.trains.length}`;
  const forecast=ui.preview?.snapshot_id===ui.state.snapshot_id?new Map(ui.preview.projected.trains.map(row=>[row.train_id,row])):null;
  const affected=new Set(ui.analysis?.snapshot_id===ui.state.snapshot_id?ui.analysis.optimization_scope_train_ids:[]);
  target.innerHTML=ui.state.trains.map(row=>{const current=Math.max(0,Math.min(100,Number(row.route_progress_0_1||0)*100));
    const future=forecast?.get(row.train_id),next=future?Math.max(0,Math.min(100,Number(future.route_progress_0_1||0)*100)):null;
    return `<div class="graph-row" role="listitem" data-affected="${affected.has(row.train_id)}"><button type="button" data-train="${esc(row.train_id)}">${esc(row.train_id)}</button>
      <div class="graph-track" aria-label="${esc(row.train_id)} ${n(current,1)}%">
        <div class="graph-fill" style="width:${current}%"></div>${next===null?'':`<span class="graph-future" style="left:${next}%" title="${n(ui.preview.horizon_seconds/60)} ${esc(T('dMin'))}: ${n(next,1)}%"></span>`}</div>
      <span class="mono">${n(current,0)}%${next===null?'':` → ${n(next,0)}%`}</span>${delay(row.delay_min)}</div>`;}).join('');
}
function renderRuntimeDecisions(){if(!provider.live.runtime||ui.mode!=='LIVE')return;
  const analysis=ui.analysis,options=$('runtime-options');
  $('preview-map').hidden=!ui.preview||ui.preview.snapshot_id!==ui.state?.snapshot_id;
  $('preview-map').textContent=T(ui.previewMap?'dRuntimeLiveMap':'dRuntimePreviewMap');
  $('runtime-identity').textContent=ui.state?`${ui.state.run_id} · snapshot ${ui.state.snapshot_version} · ${ui.state.trains.length} поездов`:'';
  if(!analysis||analysis.snapshot_id!==ui.state?.snapshot_id){options.innerHTML=empty('dRunToSeePlan');
    $('preview-decision').disabled=true;$('apply-decision').disabled=true;return;}
  $('human-pair').textContent=analysis.optimization_scope_train_ids.length?
    `${analysis.optimization_scope_train_ids.length} ${T('dRuntimeAffected')}: ${analysis.optimization_scope_train_ids.slice(0,5).join(', ')}`:T('dRuntimeNoIncident');
  options.innerHTML=`<p class="caption">${esc(T('dRuntimeRecommendationBasis'))} · ${esc(T('dRuntimePlanWarning'))}</p>`+
    analysis.options.map(row=>`<label class="runtime-option ${row.id===analysis.recommended_option_id?'recommended':''}">
      <input type="radio" name="runtime-option" value="${esc(row.id)}" ${row.id===ui.selectedOption?'checked':''} ${row.validation.valid?'':'disabled'}>
      <strong>${esc(row.id)} · ${esc(row.action?`${T('dRuntimeHold')} ${row.action.train_id} ${row.action.hold_minutes} ${T('dMin')}`:T('dRuntimeNoAction'))}</strong>
      ${row.id===analysis.recommended_option_id?`<span class="badge" data-source="DERIVED">${esc(T('dRecommended'))}</span>`:''}
      <small>${esc(T('dRuntimeDelay'))} ${n(row.metrics.total_delay_min,1)} ${esc(T('dMin'))} · ${esc(T('dRuntimeWeighted'))} ${n(row.metrics.weighted_delay_units,1)} · ${esc(T('dConflicts'))} ${n(row.metrics.conflicts)}</small>
    </label>`).join('');
  $('preview-decision').disabled=!ui.selectedOption;$('apply-decision').disabled=!ui.selectedOption||ui.selectedOption==='A';
  if(ui.preview?.snapshot_id!==analysis.snapshot_id)$('runtime-preview').innerHTML='';
  else $('runtime-preview').innerHTML=`<p><strong>${esc(T('dRuntimePreview'))} ${esc(ui.preview.option_id)}</strong> · ${esc(T('dRuntimeUnchanged'))}</p>
    <div class="preview-comparison">${[[T('dCurrent'),ui.preview.current],[`${n(ui.preview.horizon_seconds/60)} ${T('dMin')} ${T('dRuntimeLater')}`,ui.preview.projected]].map(([title,state])=>
      `<div><strong>${esc(title)}</strong><small>${esc(when(state.virtual_time))}</small><small>${state.trains.length} поездов</small><small>${state.blocks.filter(block=>block.state_conflict).length} конфликтов</small></div>`).join('')}</div>
    <div class="preview-comparison"><div><strong>A · ${esc(T('dRuntimeWithoutAction'))}</strong><small>${n(ui.preview.baseline_metrics.total_delay_min,1)} ${esc(T('dMin'))}</small><small>${n(ui.preview.baseline_metrics.conflicts)} ${esc(T('dConflicts'))}</small></div>
    <div><strong>${esc(ui.preview.option_id)} · ${esc(T('dRuntimeWithAction'))}</strong><small>${n(ui.preview.metrics.total_delay_min,1)} ${esc(T('dMin'))}</small><small>${n(ui.preview.metrics.conflicts)} ${esc(T('dConflicts'))}</small></div></div>
    <p>${esc(T('dDelta'))}: ${n(ui.preview.delta_total_delay_min,1)} ${esc(T('dMin'))} · ${esc(T('dQuality'))}: ${n(ui.preview.baseline_metrics.quality.score,1)} → ${n(ui.preview.metrics.quality.score,1)} / 100</p>
    <div class="train-impact-chart">${ui.preview.train_impacts.map(row=>`<div><strong>${esc(row.train_id)}</strong><span>${n(row.without_action_delay_min,1)} → ${n(row.with_action_delay_min,1)} ${esc(T('dMin'))}<br><small>ETA ${esc(when(row.without_action_eta))} → ${esc(when(row.with_action_eta))}</small></span></div>`).join('')}</div>`;
}
function renderAll(){
  $('virtual-time').textContent=when(ui.state?.virtual_time||ui.demo?.ts);
  if(!ui.topology||!ui.state){for(const id of ['conflict-content','plan-content','train-details','cascade-content','eco-content','quality-content','whatif-content'])$(id).innerHTML=empty('dLoading');
    for(const id of ['conflict-source','arrival-source','train-source','compare-source','eco-source','cascade-source','quality-source','whatif-source'])sourceBadge(id,'UNAVAILABLE');
    $('arrivals-body').innerHTML=`<tr><td colspan="4">${esc(T('dLoading'))}</td></tr>`;
    $('compare-body').innerHTML=`<tr><td colspan="7">${esc(T('dLoading'))}</td></tr>`;
    $('speed-chart').innerHTML='';$('map').hidden=true;$('map-svg').removeAttribute('hidden');$('map-svg').innerHTML='';renderTrainGraph();return;}
  sourceBadge('source-badge',ui.topology.geometry_source==='EXTERNAL_REFERENCE_APPROXIMATE'?'DERIVED':'UNAVAILABLE');
  $('source-badge').textContent=T('dGeneralized');
  renderMap();renderConflict();renderPlan();renderArrivals();renderTrain();renderCompare();renderEco();renderCascade();renderQuality();renderWhatIf();renderTimeline();
  renderRuntimeDecisions();renderTrainGraph();
}
async function loadRuntimeAnalysis(){if(!provider.live.runtime||!ui.state)return;
  const identity=ui.state.snapshot_id;$('runtime-options').innerHTML=empty('dLoading');
  try{const analysis=await provider.live.analyzeRuntime();if(identity!==ui.state?.snapshot_id)return;
    ui.analysis=analysis;ui.selectedOption=analysis.recommended_option_id;ui.preview=null;
    ui.compare={status:'READY',source_type:'DEMO',snapshot_id:analysis.snapshot_id,
      rows:['fifo','cp_sat'].map(policy=>({policy:policy.toUpperCase(),total_delay_min:null,incident_delay_min:null,
        conflicts:null,compute_ms:analysis.planner[policy].solver_wall_time_ms??null,energy_proxy_units:null,
        validation:`${analysis.planner[policy].status} · ${T(analysis.planner[policy].fully_validated?'dValidated':'dStationUnverified')}`}))};
    renderRuntimeDecisions();renderCompare();}
  catch(cause){if(identity===ui.state?.snapshot_id){ui.analysis=null;$('runtime-options').textContent=cause.message;}}}
async function loadRuntimeHistory(){if(!provider.live.runtime)return;
  try{const result=await provider.live.historyRuntime();if(result.run_id!==ui.state?.run_id)return;
    ui.events=result.events.slice(-8).reverse().map(row=>({key:row.type,at:row.virtual_time||row.at,replayAt:row.virtual_time,source:'DEMO'}));renderTimeline();}
  catch{ui.events=[];renderTimeline();}}
async function loadReplay(at){if(!provider.live.runtime)return;
  try{const result=await provider.live.replayRuntime(at);if(result.state.run_id!==ui.state?.run_id)return;
    ui.replayState=normalizeState(result.state);ui.replayMap=false;renderTimeline();}
  catch(cause){error(cause.message);}}
async function previewRuntime(){if(!ui.selectedOption||!ui.analysis)return;
  $('preview-decision').disabled=true;$('runtime-preview').textContent=T('dLoading');
  try{ui.preview=await provider.live.previewRuntime(ui.selectedOption,Number($('preview-horizon').value));ui.previewMap=false;renderRuntimeDecisions();renderMap();renderTrainGraph();}
  catch(cause){$('runtime-preview').textContent=cause.message;}
  finally{$('preview-decision').disabled=false;}}
async function applyRuntime(){if(!ui.selectedOption||ui.selectedOption==='A'||!ui.analysis)return;
  $('apply-decision').disabled=true;
  try{const result=await provider.live.applyRuntime(ui.selectedOption);
    ui.state=provider.live.state=normalizeState(result.after);ui.analysis=null;ui.preview=null;ui.selectedOption=null;ui.previewMap=false;
    $('human-status').textContent=`Применено: ${result.option_id} · snapshot ${ui.state.snapshot_version}`;
    renderAll();await Promise.allSettled([loadRuntimeAnalysis(),loadRuntimeHistory(),loadArrivals(),loadQuality()]);}
  catch(cause){$('human-status').textContent=`Решение не применено: ${cause.message}`;}
  finally{$('apply-decision').disabled=false;}}

async function loadArrivals(){if(!ui.selectedStation)return;const id=ui.selectedStation;
  const identity=ui.state?.snapshot_id;
  try{const result=await provider.getStationArrivals(id);if(id!==ui.selectedStation||identity!==ui.state?.snapshot_id)return;ui.arrivals=result;renderArrivals();}
  catch{ui.arrivals=unavailable('Station arrivals request failed');renderArrivals();}}
async function loadComparison(){try{ui.compare=await provider.getCompareResult();}catch{ui.compare=unavailable('Compare request failed');}renderCompare();}
async function loadEcoAndCascade(){const id=ui.selectedTrain;if(!id)return;
  const identity=ui.state?.snapshot_id;
  ui.eco=null;ui.cascade=null;renderEco();renderCascade();
  const [eco,cascade]=await Promise.allSettled([provider.getSpeedAdvice(id),provider.getCascade(id)]);
  if(id!==ui.selectedTrain||identity!==ui.state?.snapshot_id)return;
  ui.eco=eco.status==='fulfilled'?eco.value:unavailable('Speed advice request failed');
  ui.cascade=cascade.status==='fulfilled'?cascade.value:unavailable('Cascade request failed');
  renderEco();renderCascade();}
async function loadQuality(){if(provider.live.endpoints.quality&&Date.now()-(ui.lastQualityFetch||0)<10000)return;
  const identity=ui.state?.snapshot_id;
  ui.lastQualityFetch=Date.now();try{const quality=await provider.getQualityIndex();if(identity!==ui.state?.snapshot_id)return;ui.quality=quality;}
  catch{ui.quality=unavailable('Quality request failed');}renderQuality();}
async function runPlan(){if(!ui.state)return;
  $('run-plan').disabled=true;$('plan-content').textContent=T('dLoading');
  const identity=ui.state.snapshot_id;
  try{const plan=await provider.getDispatchPlan(context());if(identity!==ui.state?.snapshot_id)return;
    ui.plan=plan;renderPlan();
    const pair=ui.plan.pair_train_ids.length?ui.plan.pair_train_ids:
      ui.state.blocks.find(row=>row.state_conflict)?.occupied_train_ids.slice(0,2)||[];
    $('human-pair').textContent=pair.length?pair.join(' / '):T('dNoPair');
     if(ui.incident!=='none'&&!provider.live.short&&!provider.live.runtime)startTimer();
  }catch(cause){ui.plan=unavailable(cause.message);renderPlan();$('human-pair').textContent=T('dNoPair');}
   finally{$('run-plan').disabled=false;if(ui.mode==='LIVE'&&!provider.live.runtime)void loadComparison();}}
function chooseTrain(id,drawer=false){if(!train(id))return;ui.selectedTrain=id;$('train-select').value=id;
  renderTrain();renderMap();void loadEcoAndCascade();if(drawer)openDrawer('train',id);}
function chooseStation(id,drawer=false){if(!ui.topology?.stations.some(row=>row.station_id===id))return;
  ui.selectedStation=id;const city=cityData?.cities.find(row=>row.station_ids.includes(id));if(city)ui.city=city.city_id;
  renderCities();renderStationScheme();void loadArrivals();if(drawer)openDrawer('station',id);}
function openConflict(blockId){const row=block(blockId);if(!row)return;openDrawer('conflict',blockId);}
function openIncident(id){if(!ui.state?.active_incidents.some(row=>row.incident_id===id))return;openDrawer('incident',id);}
function openDrawer(kind,id){ui.drawerOpener=document.activeElement;const drawer=$('detail-drawer'),target=$('drawer-content');
  drawer.hidden=false;$('drawer-title').textContent=kind==='train'?id:kind==='station'?stationName(id):kind==='conflict'?T('dConflict'):T('dIncident');
  if(kind==='train'){const row=train(id),signal=trainSignal(row);
    target.innerHTML=`<div class="details-grid">${detail(T('dTrain'),row.train_id)}${detail(T('dCategory'),row.category)}
      ${detail(T('dDirection'),row.direction)}${detail(T('dSegment'),row.current_segment_id||T('dUnknown'))}
      ${detail(T('dBlock'),row.current_block_id||T('dUnknown'))}${detail(T('dNextStation'),stationName(row.next_station_id))}
      ${detail('ETA',when(row.estimated_arrival))}${detail(T('dScheduled'),when(row.scheduled_arrival))}
      ${detail(T('dDelay'),row.delay_min==null?'—':'+'+n(row.delay_min,1)+' '+T('dMin'))}
      ${detail(T('dSpeed'),row.speed_kmh==null?'—':n(row.speed_kmh,1)+' km/h')}
      ${detail(T('dRecommendedTrack'),ui.plan?.selected_station_track||T('dNotAssigned'))}
      ${detail(T('dAppliedTrack'),T('dNotAssigned'))}
      ${detail(T('dSignal'),signal?.failed?T('dSignalFailed'):signal?.aspect||T('dUnknown'))}
      ${detail(T('dValidation'),ui.plan?.validation_status||T('dUnavailable'))}
      ${detail(T('dPolicy'),ui.plan?.policy||T('dUnavailable'))}
      ${detail(T('dDataSource'),row.source_type||T('dUnavailable'))}</div>`;
  }else if(kind==='station'){
    const row=ui.topology.stations.find(item=>item.station_id===id);
    target.innerHTML=`${detail(T('dStation'),row.name)}${detail(T('dDataSource'),ui.topology.geometry_source)}
      <p>${esc(T('dStationArrivals'))}: <a href="#station-panel" id="drawer-arrivals-link">${esc(T('dOpenPanel'))}</a></p>`;
  }else if(kind==='conflict'){
    const row=block(id);target.innerHTML=`${detail(T('dResource'),id)}${detail(T('dCapacity'),row.capacity)}
      <p>${esc(T('dConflict'))}: ${row.occupied_train_ids.map(esc).join(', ')}</p><p class="caption">${esc(T('dConflictBoundary'))}</p>`;
  }else{
    const row=ui.state.active_incidents.find(item=>item.incident_id===id);
    target.innerHTML=`${detail(T('dIncident'),row.type)}${detail(T('dResource'),row.block_id||row.signal_id||row.switch_id||row.train_id||T('dUnknown'))}
      ${detail(T('dStartTime'),when(row.at))}${detail(T('dDataSource'),row.source_type||'SIMULATED_DEMO')}`;
  }
  $('close-drawer').focus();
}
function closeDrawer(){if($('detail-drawer').hidden)return;$('detail-drawer').hidden=true;ui.drawerOpener?.focus?.();ui.drawerOpener=null;}
function stopTimer(){clearInterval(ui.timer);ui.timer=null;}
function startTimer(){stopTimer();ui.timerLeft=20;$('timer').textContent='20';
  ui.timer=setInterval(()=>{ui.timerLeft--; $('timer').textContent=String(Math.max(0,ui.timerLeft));
    if(ui.timerLeft<=0){stopTimer();$('human-status').textContent=T('dAutoFifoSimulation');event('dAutoFifoSimulation','DEMO');}},1000);}
async function submitChoice(choice){if(ui.decisionPending)return;ui.decisionPending=true;stopTimer();
  const buttons=[...document.querySelectorAll('[data-choice]')];buttons.forEach(button=>button.disabled=true);
  $('human-status').textContent=T('dPendingDecision');
  try{const result=await provider.submitHumanDecision(choice,context());
    if(result.accepted===true)$('human-status').textContent=T('dAcceptedAdvisory')+(result.applied?'':` · ${T('dNotApplied')}`);
    else if(result.accepted===false)$('human-status').textContent=T('dRejected')+': '+(result.reason||result.actions?.flatMap(row=>row.issue_codes||[]).join(', ')||T('dUnknown'));
    else $('human-status').textContent=T('dHumanDemoOnly');
    event(result.accepted===true?'dAcceptedAdvisory':result.accepted===false?'dRejected':'dHumanDemoOnly',result.source_type||'DEMO');
  }catch(cause){$('human-status').textContent=T('dDecisionError')+': '+cause.message;}
  finally{ui.decisionPending=false;buttons.forEach(button=>button.disabled=false);}}
async function changeIncident(value){ui.incident=value;ui.incidentAt=ui.elapsed;ui.plan=null;ui.affectedResources=[];
  if(ui.mode==='LIVE'&&provider.live.short)return;
  $('human-status').textContent='';stopTimer();event('dIncidentChanged','DEMO');
  if(ui.mode==='MOCK'){renderAll();await runPlan();return;}
  stopPlayback();try{const frame=await provider.live.getDemoSnapshot({elapsed:ui.elapsed,incident:value,incident_at:ui.incidentAt});
    ui.demo=frame;provider.live.demo=frame;ui.state=await provider.getState({elapsed:ui.elapsed,incident:value,incident_at:ui.incidentAt,seed:ui.state?.seed??42});
    ui.lastElapsed=ui.elapsed-.001;renderAll();await runPlan();if(ui.playing)connect();}
  catch(cause){setConnection('OFFLINE');error(T('dLiveUnavailable')+': '+cause.message);}}
async function submitWhatIf(form){const values=new FormData(form),request={incident_type:values.get('incident_type'),
  resource_id:values.get('resource_id'),start_time:values.get('start_time'),duration_min:Number(values.get('duration_min')),
   scenario_id:ui.state?.scenario_id,seed:ui.state?.seed,snapshot_version:ui.state?.snapshot_version};
  if(ui.mode==='LIVE'&&provider.live.runtime){
    $('whatif-content').textContent=T('dLoading');
    try{await provider.live.setControl(false,ui.speed);ui.playing=false;$('play').textContent=T('dPlay');
      const created=await provider.live.createIncident(request.incident_type,request.resource_id,request.duration_min);
      ui.state=created.state;ui.analysis=null;ui.preview=null;ui.selectedOption=null;
      ui.affectedResources=[request.resource_id];ui.whatIf=null;
      $('whatif-content').textContent=`${created.incident.type} · ${created.incident[Object.keys(created.incident).find(key=>key.endsWith('_id')&&key!=='incident_id')]} · snapshot ${ui.state.snapshot_version}`;
      renderAll();setConnection('PAUSED');await Promise.allSettled([loadRuntimeAnalysis(),loadRuntimeHistory(),loadArrivals(),loadQuality(),runPlan()]);
    }catch(cause){$('whatif-content').textContent=`Инцидент не внесён: ${cause.message}`;}
    return;
  }
  $('whatif-content').textContent=T('dLoading');
  try{ui.whatIf=await provider.runWhatIf(request);ui.affectedResources=Array.isArray(ui.whatIf.affected_resource_ids)?ui.whatIf.affected_resource_ids:[];
    renderWhatIf();renderMap();event('dWhatIf',ui.whatIf.source_type||'UNAVAILABLE');}
  catch(cause){ui.whatIf=unavailable(cause.message);renderWhatIf();}}

async function start(){
  applyTheme();await initializeLanguage();
  try{cityData=await requestJson('/mocks/cities.json');if(cityData.source_type!=='MOCK')throw Error('City reference source invalid');}
  catch{cityData={cities:[]};}
  $('theme').onclick=()=>{ui.theme=ui.theme==='dark'?'light':'dark';applyTheme();renderMap();};
  $('language').onchange=async e=>{ui.lang=e.target.value;localStorage.setItem('turkisib-language',ui.lang);
    await window.i18next.changeLanguage(ui.lang);applyLanguage();};
  $('data-mode').onchange=e=>void startMode(e.target.value);
  $('scenario').onchange=async e=>{if(ui.mode==='LIVE'&&!['SCN-RUNTIME','SCN-ALL','SCN-SHORT'].includes(e.target.value)){
      error(T('dScenarioUnavailable'));e.target.value='SCN-RUNTIME';return;}
    if(ui.mode==='MOCK'){
      if(['SCN-SHORT','SCN-RUNTIME'].includes(e.target.value)){e.target.value='SCN-ALL';error(T('dScenarioUnavailable'));return;}
      provider.mock.setScenario(e.target.value);
    }
    await startMode(ui.mode);};
  $('incident').onchange=e=>void changeIncident(e.target.value);
  document.querySelector('#whatif-form [name="incident_type"]').onchange=updateWhatIfResources;
  $('speed').onchange=e=>{ui.speed=Number(e.target.value);
    if(ui.mode==='LIVE'&&provider.live.runtime){void provider.live.setControl(ui.playing,ui.speed).catch(cause=>error(cause.message));return;}
    if(ui.mode==='LIVE'&&ui.playing)connect();};
  $('play').onclick=async()=>{if(provider.live.short&&ui.mode==='LIVE')return;
    ui.playing=!ui.playing;$('play').textContent=T(ui.playing?'dPause':'dPlay');
    if(ui.mode==='LIVE'&&provider.live.runtime){try{await provider.live.setControl(ui.playing,ui.speed);setConnection(ui.playing?'ONLINE':'PAUSED');
      if(!ui.playing)await Promise.allSettled([loadRuntimeAnalysis(),loadRuntimeHistory()]);}
      catch(cause){ui.playing=!ui.playing;$('play').textContent=T(ui.playing?'dPause':'dPlay');error(cause.message);}return;}
    if(ui.mode==='LIVE'){if(ui.playing)connect();else{stopPlayback();setConnection('PAUSED');}}else setConnection('MOCK');};
  $('reset').onclick=async()=>{if(ui.mode==='LIVE'&&provider.live.runtime){
      try{await provider.live.resetRuntime();await startMode('LIVE');}catch(cause){error(cause.message);}return;}
    ui.playing=true;$('play').textContent=T('dPause');void startMode(ui.mode);};
  $('map-mode').onclick=()=>{ui.view='map';renderMap();};$('scheme-mode').onclick=()=>{ui.view='scheme';renderMap();};
  $('preview-map').onclick=()=>{ui.previewMap=!ui.previewMap;renderRuntimeDecisions();renderMap();};
  $('replay-map').onclick=()=>{ui.replayMap=!ui.replayMap;if(ui.replayMap)ui.previewMap=false;renderTimeline();renderRuntimeDecisions();renderMap();};
  $('fit').onclick=()=>{if(ui.mapReady&&ui.view==='map')ui.map.fitBounds([[68,42.5],[78,54]],{padding:40,duration:0});};
  $('city').onchange=e=>{ui.city=e.target.value;renderCities();void loadArrivals();};
  $('station').onchange=e=>chooseStation(e.target.value);
  $('train-select').onchange=e=>chooseTrain(e.target.value);
  $('open-train-drawer').onclick=()=>{if(ui.selectedTrain)openDrawer('train',ui.selectedTrain);};
  $('close-drawer').onclick=closeDrawer;
  $('run-plan').onclick=()=>{void runPlan();if(provider.live.runtime)void loadRuntimeAnalysis();};
  $('runtime-options').onchange=e=>{if(e.target.name==='runtime-option'){ui.selectedOption=e.target.value;ui.preview=null;renderRuntimeDecisions();}};
  $('preview-decision').onclick=()=>void previewRuntime();
  $('preview-horizon').onchange=()=>{ui.preview=null;ui.previewMap=false;renderRuntimeDecisions();renderMap();renderTrainGraph();};
  $('apply-decision').onclick=()=>void applyRuntime();
  document.querySelectorAll('[data-choice]').forEach(button=>button.onclick=()=>void submitChoice(button.dataset.choice));
  $('whatif-form').onsubmit=e=>{e.preventDefault();void submitWhatIf(e.currentTarget);};
  document.addEventListener('click',e=>{const trainButton=e.target.closest('[data-train]');if(trainButton)chooseTrain(trainButton.dataset.train,true);
    const stationButton=e.target.closest('[data-station]');if(stationButton)chooseStation(stationButton.dataset.station,true);
    const blockButton=e.target.closest('[data-block]');if(blockButton)openConflict(blockButton.dataset.block);
    const incidentButton=e.target.closest('[data-incident]');if(incidentButton)openIncident(incidentButton.dataset.incident);
    const replayButton=e.target.closest('[data-replay]');if(replayButton)void loadReplay(replayButton.dataset.replay);});
  $('map-svg').addEventListener('keydown',e=>{if(['Enter',' '].includes(e.key)&&e.target.matches('[role=button]')){e.preventDefault();e.target.dispatchEvent(new MouseEvent('click',{bubbles:true}));}});
  document.addEventListener('keydown',e=>{if(e.key==='Escape')closeDrawer();});
  await startMode(new URLSearchParams(location.search).get('mode')?.toUpperCase()==='MOCK'?'MOCK':'LIVE');
}
start().catch(cause=>error(cause.message));
