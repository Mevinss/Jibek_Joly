'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const config = window.Stage1MapConfig;
  let lang = localStorage.getItem('turkisib-language') || 'ru';
  let source, map, offline = true, styleFallback = false, playing = true, speed = 1;
  let scenarioId = 'SCN-ALL', simMs = Date.parse('2026-10-01T09:00:00+05:00');
  let lastTick = performance.now(), staleSince = null, drawer = null, drawerMinute = null, drawerOpener = null;
  const T = (key, vars={}) => i18next.t(key, vars);
  const stamp = value => value ? new Date(value).toLocaleTimeString(lang === 'kk' ? 'kk-KZ' : 'ru-RU', {timeZone:'Asia/Qyzylorda', hour:'2-digit', minute:'2-digit', hour12:false}) : '—';
  const num = (value, digits=0) => Number(value).toLocaleString(lang === 'kk' ? 'kk-KZ' : 'ru-RU', {maximumFractionDigits:digits});
  const station = id => source?.dataset.stations.find(row => row.station_id === id);
  const coord = id => {const row = source?.stations.find(row => row.station_id === id); return row ? [row.lon, row.lat] : null;};
  const route = (a,b) => source?.routes.find(row => row.from_station_id === a && row.to_station_id === b || row.from_station_id === b && row.to_station_id === a);
  const profile = () => source.dataset.profiles[scenarioId];
  const activeIncidents = () => {
    const scenario = source.dataset.scenarios.find(row => row.scenario_id === scenarioId);
    return source.dataset.incidents.filter(row => scenario.incident_ids.includes(row.incident_id) && simMs >= Date.parse(row.at) && simMs < Date.parse(row.at) + Number(row.duration_min)*60000);
  };
  const km = (a,b) => {const lat1=a[1]*Math.PI/180,lat2=b[1]*Math.PI/180,dlat=lat2-lat1,dlon=(b[0]-a[0])*Math.PI/180;const q=Math.sin(dlat/2)**2+Math.cos(lat1)*Math.cos(lat2)*Math.sin(dlon/2)**2;return 6371.0088*2*Math.asin(Math.min(1,Math.sqrt(q)));};
  function along(line, fraction) {
    const lengths = line.slice(1).map((point,index) => km(line[index],point));
    let remaining = lengths.reduce((sum,value)=>sum+value,0)*Math.max(0,Math.min(1,fraction));
    for(let i=0;i<lengths.length;i++){if(remaining<=lengths[i]||i===lengths.length-1){const ratio=lengths[i]?remaining/lengths[i]:0;return line[i].map((value,axis)=>value+(line[i+1][axis]-value)*ratio);}remaining-=lengths[i];}
    return line[0];
  }
  function trainState(train) {
    const stops = train.stops;
    let current = stops[0], next = stops[1] || null, fraction = 0, moving = false;
    if(simMs >= Date.parse(stops.at(-1).expected_arrival || stops.at(-1).expected_departure)) {current=stops.at(-1);next=null;}
    else for(let i=0;i<stops.length-1;i++) {
      const left=stops[i],right=stops[i+1], depart=Date.parse(left.expected_departure || left.expected_arrival),arrive=Date.parse(right.expected_arrival || right.expected_departure);
      if(simMs < depart) {current=left;next=right;break;}
      if(simMs <= arrive) {current=left;next=right;fraction=(simMs-depart)/Math.max(1,arrive-depart);moving=true;break;}
      current=right;next=stops[i+2]||null;
    }
    const segment=next?route(current.station_id,next.station_id):null;
    const line=segment?.polyline;
    const direction=segment?.from_station_id===current.station_id;
    const position=moving&&line?along(direction?line:[...line].reverse(),fraction):coord(current.station_id);
    const distance=moving&&segment?Number(segment.demo_distance_km)*(1-fraction):next&&segment?Number(segment.demo_distance_km):0;
    const nextArrival=next?.expected_arrival||next?.scheduled_arrival;
    const speedKmh=moving&&segment&&nextArrival?Number(segment.demo_distance_km)*3600000/Math.max(1,Date.parse(nextArrival)-Date.parse(current.expected_departure||current.scheduled_departure)):0;
    const delayMin=(next||current).delay_min;
    return {position,current,next,fraction,moving,distance,speedKmh,delayMin};
  }
  function delayClass(value) {return value<=config.delayThresholdsMin.ok?'ok':value<=config.delayThresholdsMin.warning?'warning':value<=config.delayThresholdsMin.orange?'orange':'critical';}
  const delayChip = value => `<span class="stage1-status ${delayClass(value)}">${value>5?'!':'✓'} +${num(value,1)} ${T('min')}</span>`;
  const category = key => T('stage1Category_'+key);
  function incidentPoint(incident) {
    if(incident.incident_id==='INC-01')return coord('KOK');
    if(incident.incident_id==='INC-03')return coord('AST');
    const blockId=incident.block_id||incident.signal_id?.replace(/^SIG-/,'').replace(/-(BOR|AKK|KOK|AST|KAR|AKD|SAR|SHU|ALM)$/,'');
    for(const segment of source.routes)for(const block of segment.blocks)if(block.block_id===blockId)return along(segment.polyline,(block.start_fraction+block.end_fraction)/2);
    return null;
  }
  function paint() {
    if(!source)return;
    $('stage1-clock').textContent=stamp(simMs)+':'+String(new Date(simMs).getUTCSeconds()).padStart(2,'0')+' +05:00';
    $('stage1-range').value=Math.max(0,Math.min(900,Math.floor((simMs-Date.parse('2026-10-01T09:00:00+05:00'))/60000)));
    const trainFeatures=profile().map(train=>{const state=trainState(train);return {type:'Feature',geometry:{type:'Point',coordinates:state.position},properties:{train_id:train.train_id,category:train.category,delay:state.delayMin}};}).filter(feature=>feature.geometry.coordinates);
    const incidentFeatures=activeIncidents().map(row=>({type:'Feature',geometry:{type:'Point',coordinates:incidentPoint(row)},properties:{incident_id:row.incident_id}})).filter(feature=>feature.geometry.coordinates);
    if(map?.getSource('stage-trains'))map.getSource('stage-trains').setData({type:'FeatureCollection',features:trainFeatures});
    if(map?.getSource('stage-incidents'))map.getSource('stage-incidents').setData({type:'FeatureCollection',features:incidentFeatures});
    $('stage1-connection').textContent=staleSince ? T('stage1Stale',{seconds:Math.floor((Date.now()-staleSince)/1000)}) : T('stage1Connected');
    $('stage1-map').classList.toggle('stage1-stale',Boolean(staleSince));
    if(drawer&&drawerMinute!==Math.floor(simMs/60000)){drawerMinute=Math.floor(simMs/60000);renderDrawer();}
  }
  function localStyle(){return {version:8,sources:{},layers:[{id:'local-paper',type:'background',paint:{'background-color':getComputedStyle(document.documentElement).getPropertyValue('--bg').trim()}}]};}
  async function initializeMap(forceOnline=false) {
    if(map){map.remove();map=null;}
    styleFallback=false;
    let style=localStyle();offline=true;
    if(navigator.onLine||forceOnline){
      const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),6000);
      try {const response=await fetch(config.styleUrl,{signal:controller.signal});if(!response.ok)throw Error(String(response.status));style=config.styleUrl;offline=false;}
      catch {offline=true;}
      finally {clearTimeout(timer);}
    }
    $('stage1-map-state').textContent=T(offline?'stage1Offline':'stage1Online');
    $('stage1-attribution').textContent=offline?T('stage1LocalCredit'):config.attribution;
    try {
      map=new maplibregl.Map({container:'stage1-map',style,center:config.center,zoom:config.zoom,attributionControl:false});
      map.addControl(new maplibregl.NavigationControl({showCompass:false}),'bottom-right');
      map.on('load',setupLayers);
      map.on('error',()=>{if(!offline&&!styleFallback){styleFallback=true;offline=true;$('stage1-map-state').textContent=T('stage1Offline');map.setStyle(localStyle());}});
    } catch(error) {$('stage1-error').hidden=false;$('stage1-error').textContent=T('stage1MapError')+' '+error.message;}
  }
  function setupLayers() {
    if(!map||!source)return;
    if(offline){map.addSource('stage-country',{type:'geojson',data:source.country});map.addLayer({id:'stage-country',type:'fill',source:'stage-country',paint:{'fill-color':getComputedStyle(document.documentElement).getPropertyValue('--surface2').trim(),'fill-outline-color':'#99a9b8'}});}
    map.addSource('stage-route',{type:'geojson',data:{type:'FeatureCollection',features:source.routes.map(row=>({type:'Feature',geometry:{type:'LineString',coordinates:row.polyline},properties:{segment_id:row.segment_id}}))}});
    map.addLayer({id:'stage-route-halo',type:'line',source:'stage-route',paint:{'line-color':'#ffffff','line-width':6}});
    map.addLayer({id:'stage-route',type:'line',source:'stage-route',paint:{'line-color':'#1d5fa8','line-width':3}});
    map.addSource('stage-stations',{type:'geojson',data:{type:'FeatureCollection',features:source.stations.map(row=>({type:'Feature',geometry:{type:'Point',coordinates:[row.lon,row.lat]},properties:{station_id:row.station_id}}))}});
    map.addLayer({id:'stage-stations-halo',type:'circle',source:'stage-stations',paint:{'circle-radius':10,'circle-color':'#fff','circle-stroke-width':2,'circle-stroke-color':'#1d5fa8'}});
    map.addLayer({id:'stage-stations',type:'circle',source:'stage-stations',paint:{'circle-radius':5,'circle-color':'#1d5fa8'}});
    map.addSource('stage-trains',{type:'geojson',data:{type:'FeatureCollection',features:[]}});
    map.addLayer({id:'stage-train-halo',type:'circle',source:'stage-trains',paint:{'circle-radius':11,'circle-color':['step',['get','delay'],'#176c47',5.0001,'#965900',15.0001,'#a3420c',30.0001,'#c0392b'],'circle-opacity':.75}});
    map.addLayer({id:'stage-trains',type:'circle',source:'stage-trains',paint:{'circle-radius':6,'circle-color':['match',['get','category'],'intercity','#1d5fa8','regional','#6b4fbb','freight','#7a5c3e','#566070'],'circle-stroke-width':1.5,'circle-stroke-color':'#fff'}});
    map.addSource('stage-incidents',{type:'geojson',data:{type:'FeatureCollection',features:[]}});
    map.addLayer({id:'stage-incidents',type:'circle',source:'stage-incidents',paint:{'circle-radius':12,'circle-color':'#c0392b','circle-stroke-width':3,'circle-stroke-color':'#fff'}});
    if(!map._stageListeners){
      map.on('click','stage-stations',event=>{const id=event.features?.[0]?.properties?.station_id;if(id)openDrawer('station',id);});
      map.on('click','stage-trains',event=>{const id=event.features?.[0]?.properties?.train_id;if(id)openDrawer('train',id);});
      map.on('click','stage-incidents',event=>{const id=event.features?.[0]?.properties?.incident_id;if(id)openDrawer('incident',id);});
      for(const layer of ['stage-stations','stage-trains','stage-incidents'])map.on('mouseenter',layer,()=>map.getCanvas().style.cursor='pointer');
      for(const layer of ['stage-stations','stage-trains','stage-incidents'])map.on('mouseleave',layer,()=>map.getCanvas().style.cursor='');
      map._stageListeners=true;
    }
    map.fitBounds([[68.8,43.05],[77.5,53.55]],{padding:50,duration:0});
    paint();
  }
  function openDrawer(type,id,stationId=null) {
    drawer={type,id,stationId};drawerMinute=null;drawerOpener=document.activeElement;
    $('stage1-drawer').hidden=false;renderDrawer();$('stage1-close').focus({preventScroll:true});
    if(type==='station'&&map){const point=coord(id),approximate=source.stations.find(row=>row.station_id===id)?.approximate;if(point)map.flyTo({center:point,zoom:offline||approximate?9:14.5,speed:1.2,duration:offline?0:undefined});}
  }
  function closeDrawer(){$('stage1-drawer').hidden=true;drawer=null;drawerOpener?.focus?.({preventScroll:true});}
  function board(id) {
    const entries=profile().flatMap(train=>train.stops.filter(stop=>stop.station_id===id).map(stop=>({train,stop,at:stop.expected_arrival||stop.expected_departure})));
    entries.sort((a,b)=>Date.parse(a.at)-Date.parse(b.at));
    const future=entries.filter(row=>Date.parse(row.at)>=simMs).slice(0,12);
    return future.length?future:entries.slice(-12);
  }
  function renderStation(id) {
    const row=station(id),tracks=source.dataset.station_tracks.filter(track=>track.station_id===id).length;
    const attention=$('stage1-attention')?.checked||false,tab=$('stage1-tab-scheme')?.getAttribute('aria-selected')==='true'?'scheme':'board';
    const header=`<div class="stage1-facts"><div><dt>${T('stage1Tracks')}</dt><dd>${num(tracks)}</dd></div><div><dt>${T('stage1LocationQuality')}</dt><dd>${T(source.stations.find(s=>s.station_id===id)?.approximate?'stage1Approximate':'stage1OsmVerified')}</dd></div></div><p class="caption">${T('stage1Simulation')} · ${T('stage1Mock')}</p><div class="stage1-tabs" role="tablist"><button id="stage1-tab-board" type="button" role="tab" aria-selected="${tab==='board'}" data-stage-tab="board">${T('stage1Board')}</button><button id="stage1-tab-scheme" type="button" role="tab" aria-selected="${tab==='scheme'}" data-stage-tab="scheme">${T('stage1Scheme')}</button></div>`;
    if(tab==='scheme')return header+renderScheme(id,tracks);
    const rows=board(id).filter(item=>!attention||item.stop.delay_min>15||incidentReason(item.train,item.stop));
    return header+`<label class="stage1-filter"><input id="stage1-attention" type="checkbox" ${attention?'checked':''}><span>${T('stage1Attention')}</span></label><div class="table-wrap"><table><thead><tr><th>${T('train')}</th><th>${T('direction')}</th><th>${T('scheduled')}</th><th>${T('stage1Expected')}</th><th>${T('stage1In')}</th><th>${T('delay')}</th><th>${T('stage1Track')}</th><th>${T('stage1Status')}</th></tr></thead><tbody>${rows.map(({train,stop,at})=>`<tr><td><button data-train="${esc(train.train_id)}" data-station-context="${id}">${esc(train.train_id)}</button><small>${category(train.category)}</small></td><td>${esc(stationName(train.origin_station_id))} → ${esc(stationName(train.destination_station_id))}</td><td>${stamp(stop.scheduled_arrival||stop.scheduled_departure)}</td><td>${stamp(at)}</td><td>${Math.max(0,Math.ceil((Date.parse(at)-simMs)/60000))} ${T('min')}</td><td>${delayChip(stop.delay_min)}</td><td>${T('stage1NoData')}</td><td>${incidentReason(train,stop)||T('stage1ScheduledStatus')}</td></tr>`).join('')}</tbody></table></div>${rows.length?'':`<p>${T('stage1NoData')}</p>`}<p class="caption">${T('stage1BoardNote')}</p>`;
  }
  function stationName(id){return station(id)?.name_kk||id;}
  function incidentReason(train,stop){const cause=source.dataset.incidents.find(incident=>stop.cause_ids?.includes(incident.incident_id));return cause?esc(T('stage1Incident_'+cause.incident_id)):'';}
  function renderScheme(id,tracks) {
    const switchRow=source.dataset.switches.find(row=>row.station_id===id);
    const incident=activeIncidents().some(row=>row.incident_id==='INC-03'&&id==='AST');
    const index=source.dataset.stations.findIndex(row=>row.station_id===id),previous=source.dataset.stations[index-1],next=source.dataset.stations[index+1];
    const height=100+tracks*34;
    const lines=Array.from({length:tracks},(_,i)=>{const y=55+i*34;return `<path d="M28 ${height/2} L85 ${y} H350 L414 ${height/2}" fill="none" stroke="${i===0?'#1d5fa8':'#8a93a1'}" stroke-width="${i===0?3:2}"/><text x="90" y="${y-8}">T${i+1}${i===0?' · '+T('stage1MainTrack'):''}</text>`;}).join('');
    const adjacentBlocks=source.routes.filter(segment=>segment.from_station_id===id||segment.to_station_id===id).map(segment=>segment.from_station_id===id?segment.blocks[0].block_id:segment.blocks.at(-1).block_id);
    const signals=source.dataset.signals.filter(row=>adjacentBlocks.includes(row.block_id)&&row.entry_direction_from===id);
    const signalStop=incident||signals.some(row=>row.initial_aspect==='STOP');
    return `<svg class="stage1-scheme" viewBox="0 0 440 ${height}" role="img" aria-label="${esc(T('stage1Scheme'))}"><text x="10" y="20">${esc(previous?.name_kk||'—')}</text><text x="300" y="20">${esc(next?.name_kk||'—')}</text>${lines}${switchRow?`<circle cx="60" cy="${height/2}" r="6" fill="${incident?'#c0392b':'#1d5fa8'}"/><text x="12" y="${height-8}">${esc(switchRow.switch_id)}${incident?' · '+esc(T('stage1OnlyT1')):''}</text>`:''}<circle cx="402" cy="${height/2}" r="6" fill="${signalStop?'#c0392b':'#176c47'}"/>${signalStop?`<text x="360" y="${height-9}">${esc(T('stage1SignalStop'))}</text>`:''}</svg><p class="caption">${T('stage1SchemeNote')}</p><p>${T('stage1Signals')}: ${num(signals.length)} · ${T('stage1TrackUnassigned')}</p>`;
  }
  function renderTrain(id) {
    const train=profile().find(row=>row.train_id===id);if(!train)return `<p>${T('stage1NoData')}</p>`;
    const state=trainState(train),next=state.next;
    const details=[[T('train'),train.train_id],[T('stage1Type'),category(train.category)],[T('direction'),stationName(train.origin_station_id)+' → '+stationName(train.destination_station_id)],[T('speed'),state.moving?num(state.speedKmh,1)+' '+T('kmh'):T('stopped')],[T('nextStation'),next?stationName(next.station_id):T('stage1NoData')],[T('distance'),next?num(state.distance,1)+' '+T('km'):T('stage1NoData')],[T('eta'),next?num(Math.max(0,(Date.parse(next.expected_arrival)-simMs)/60000),0)+' '+T('min'):T('stage1NoData')],[T('delay'),`+${num(state.delayMin,1)} ${T('min')}`],[T('stage1RecommendedTrack'),T('stage1NoData')]];
    const upcoming=train.stops.filter(stop=>Date.parse(stop.expected_departure||stop.expected_arrival)>=simMs);
    const target=drawer?.stationId?train.stops.find(stop=>stop.station_id===drawer.stationId):null;
    const until=target?.expected_arrival?Math.max(0,(Date.parse(target.expected_arrival)-simMs)/60000):null;
    return `<p class="caption">${T('stage1Simulation')} · ${T('stage1Mock')}</p><dl class="stage1-facts">${details.map(([label,value])=>`<div><dt>${label}</dt><dd>${esc(value)}</dd></div>`).join('')}</dl>${until===null?'':`<p>${T('stage1UntilStation',{name:stationName(drawer.stationId),minutes:num(until,0)})}</p>`}<h3>${T('stage1NextStops')}</h3><div class="table-wrap"><table><thead><tr><th>${T('station')}</th><th>${T('scheduled')}</th><th>${T('stage1Expected')}</th><th>${T('stage1In')}</th><th>${T('delay')}</th></tr></thead><tbody>${upcoming.map(stop=>{const expected=stop.expected_arrival||stop.expected_departure,planned=stop.scheduled_arrival||stop.scheduled_departure;return `<tr><td>${esc(stationName(stop.station_id))}${stop.station_id===drawer?.stationId?' · '+T('stage1SelectedStation'):''}</td><td>${stamp(planned)}</td><td>${expected?stamp(expected):T('stage1ExpectedUnavailable')}</td><td>${expected?num(Math.max(0,(Date.parse(expected)-simMs)/60000),0)+' '+T('min'):'—'}</td><td>${delayChip(stop.delay_min)}</td></tr>`;}).join('')}</tbody></table></div>${upcoming.length?'':`<p>${T('stage1NoData')}</p>`}`;
  }
  function renderDrawer() {
    if(!drawer)return;
    const title=drawer.type==='station'?stationName(drawer.id):drawer.type==='train'?drawer.id:drawer.id;
    $('stage1-drawer-title').textContent=title;
    if(drawer.type==='station')$('stage1-drawer-content').innerHTML=renderStation(drawer.id);
    else if(drawer.type==='train')$('stage1-drawer-content').innerHTML=renderTrain(drawer.id);
    else {const incident=source.dataset.incidents.find(row=>row.incident_id===drawer.id);$('stage1-drawer-content').innerHTML=`<p>${incident?esc(T('stage1Incident_'+incident.incident_id)):T('stage1NoData')}</p><p class="caption">${T('stage1Mock')} · ${stamp(incident?.at)} · ${incident?.duration_min||0} ${T('min')}</p>`;}
  }
  function renderStations(){$('stage1-station-list').innerHTML=source.dataset.stations.map(row=>`<button type="button" data-station="${row.station_id}"><span>${esc(row.name_kk)}</span><small>${T(source.stations.find(point=>point.station_id===row.station_id)?.approximate?'stage1Approximate':'stage1OsmVerified')}</small></button>`).join('');}
  function localize(){document.documentElement.lang=lang;document.querySelectorAll('[data-i18n]').forEach(node=>node.textContent=T(node.dataset.i18n));$('stage1-language').value=lang;$('stage1-theme').textContent=T(document.documentElement.dataset.theme==='dark'?'light':'dark');$('stage1-review').hidden=lang!=='kk';$('stage1-map-state').textContent=T(offline?'stage1Offline':'stage1Online');if(source){renderScenarios();renderStations();renderDrawer();paint();}}
  function renderScenarios(){$('stage1-scenario').innerHTML=source.dataset.scenarios.map(row=>`<option value="${row.scenario_id}">${row.scenario_id} · ${esc(T('stage1Scenario_'+row.scenario_id))}</option>`).join('');$('stage1-scenario').value=scenarioId;}
  function tick(now){const delta=Math.min(2,(now-lastTick)/1000);lastTick=now;if(playing&&!staleSince){simMs=Math.min(Date.parse('2026-10-02T00:00:00+05:00'),simMs+delta*speed*1000);}if(source)paint();setTimeout(()=>requestAnimationFrame(tick),1000);}
  document.addEventListener('click',event=>{const stationButton=event.target.closest('[data-station]');if(stationButton)openDrawer('station',stationButton.dataset.station);const trainButton=event.target.closest('[data-train]');if(trainButton)openDrawer('train',trainButton.dataset.train,trainButton.dataset.stationContext||null);const tab=event.target.closest('[data-stage-tab]');if(tab&&drawer){const old=tab.dataset.stageTab;renderDrawer();$('stage1-tab-board')?.setAttribute('aria-selected',String(old==='board'));$('stage1-tab-scheme')?.setAttribute('aria-selected',String(old==='scheme'));$('stage1-drawer-content').innerHTML=renderStation(drawer.id);$(old==='board'?'stage1-tab-board':'stage1-tab-scheme')?.focus({preventScroll:true});}});
  document.addEventListener('change',event=>{if(event.target.id==='stage1-attention')renderDrawer();});
  document.addEventListener('keydown',event=>{if(event.key==='Escape'&&drawer)closeDrawer();});
  $('stage1-close').onclick=closeDrawer;
  $('stage1-play').onclick=()=>{playing=!playing;$('stage1-play').textContent=T(playing?'pause':'resume');};
  $('stage1-speed').onchange=event=>speed=Number(event.target.value);
  $('stage1-scenario').onchange=event=>{scenarioId=event.target.value;drawerMinute=null;renderDrawer();paint();};
  $('stage1-range').oninput=event=>{simMs=Date.parse('2026-10-01T09:00:00+05:00')+Number(event.target.value)*60000;drawerMinute=null;renderDrawer();paint();};
  $('stage1-disconnect').onclick=()=>{staleSince=staleSince?null:Date.now();$('stage1-disconnect').textContent=T(staleSince?'stage1Reconnect':'stage1Disconnect');paint();};
  $('stage1-fit').onclick=()=>map?.fitBounds([[68.8,43.05],[77.5,53.55]],{padding:50});
  $('stage1-online').onclick=()=>initializeMap(true);
  $('stage1-language').onchange=async event=>{lang=event.target.value;localStorage.setItem('turkisib-language',lang);await i18next.changeLanguage(lang);localize();};
  $('stage1-theme').onclick=()=>{const theme=document.documentElement.dataset.theme==='dark'?'light':'dark';document.documentElement.dataset.theme=theme;localStorage.setItem('turkisib-theme',theme);localize();if(offline&&map)map.setPaintProperty('local-paper','background-color',getComputedStyle(document.documentElement).getPropertyValue('--bg').trim());};
  async function start(){try{const [ru,kk]=await Promise.all(['/locales/ru.json','/locales/kk.json'].map(url=>fetch(url).then(response=>response.json())));await i18next.init({lng:lang,fallbackLng:'ru',resources:{ru:{translation:ru},kk:{translation:kk}},interpolation:{escapeValue:false}});document.documentElement.dataset.theme=localStorage.getItem('turkisib-theme')||'light';localize();source=await Stage1DataSource.load();const params=new URLSearchParams(location.search),scenario=params.get('scenario'),minute=Number(params.get('minute'));if(source.dataset.scenarios.some(row=>row.scenario_id===scenario))scenarioId=scenario;if(params.has('minute')&&Number.isFinite(minute))simMs=Date.parse('2026-10-01T09:00:00+05:00')+Math.max(0,Math.min(900,minute))*60000;renderScenarios();renderStations();await initializeMap();if(source.dataset.stations.some(row=>row.station_id===params.get('station'))){openDrawer('station',params.get('station'));if(params.get('tab')==='scheme')$('stage1-tab-scheme')?.click();}paint();requestAnimationFrame(tick);}catch(error){$('stage1-error').hidden=false;$('stage1-error').textContent=T('stage1LoadError')+' '+error.message;}}
  start();
})();
