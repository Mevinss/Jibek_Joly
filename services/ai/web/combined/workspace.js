import { tr } from './locales.js';
import { fleet } from './engine.js';
import { approachAdvice } from './approach.mjs';

const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;' }[c]));
const time = iso => new Date(iso).toLocaleTimeString('ru-RU', { timeZone:'Asia/Qyzylorda', hour:'2-digit', minute:'2-digit', second:'2-digit' });
let cleanup = () => {};
export function disposeWorkspace() { cleanup(); cleanup = () => {}; }

export function workspacePage(lang) {
  const T = key => tr(key, lang);
  return `<div class="page-heading"><div><h1>${T('workspaceTitle')}</h1><p>${T('workspaceDesc')}</p></div></div>
  <div id="api-workspace" class="api-workspace">
    <div class="workspace-controls"><label>${T('incident')} <select id="ws-incident"><option value="none">${T('noIncident')}</option><option value="closure">${T('closure')}</option></select></label><button id="ws-play">${T('pause')}</button><button id="ws-reset">${T('reset')}</button><strong id="ws-clock" class="mono">—</strong><span id="ws-connection" role="status">${T('loading')}</span></div>
    <div id="ws-error" class="info bad" role="alert" hidden><p id="ws-error-message"></p><button id="ws-retry">${T('retry')}</button></div>
    <div class="dispatch-layout"><section class="panel"><div class="panel-head"><h2>${T('diagram')}</h2><span id="ws-count" class="meta">—</span></div><div class="diagram-scroll" tabindex="0"><svg id="ws-diagram" viewBox="0 0 980 400" role="img" aria-label="${T('diagram')}"></svg></div><p class="panel-copy">${T('diagramNote')}</p><div class="history-controls"><label for="ws-replay">${T('history')}</label><input id="ws-replay" type="range" min="0" max="0" value="0"><button id="ws-live">${T('toLive')}</button><button id="ws-csv">CSV</button></div><div id="ws-map" class="workspace-map"></div></section>
    <aside class="decision-stack"><section class="panel"><div class="panel-head"><h2>${T('analysisTitle')}</h2></div><div class="panel-body"><p>${T('analysisNote')}</p><button id="ws-analysis" class="primary">${T('calculate')}</button><div id="ws-analysis-result" class="analysis-result" aria-live="polite"></div></div></section><section class="panel"><div class="panel-head"><h2>${T('selected')}</h2></div><div id="ws-selected" class="panel-body"></div></section></aside></div>
    <section class="panel"><div class="panel-head"><h2>${T('trains')}</h2></div><div class="table-scroll"><table><thead><tr><th>${T('train')}</th><th>${T('block')}</th><th>${T('speed')}</th><th>${T('delay')}</th></tr></thead><tbody id="ws-trains"></tbody></table></div></section>
  </div>`;
}

export async function mountWorkspace({ lang, dark }) {
  const T = key => tr(key, lang), host = document.getElementById('api-workspace');
  const controller = new AbortController();
  let stream, retryTimer, map, markers = new Map(), snapshot, snapshotContext, geo, selected, history = [], paused = false, replay = false, incident = 'none', incidentAt = 0, active = true, epoch = 0;
  const $ = id => host.querySelector(`#${id}`);
  const request = async (url, body) => {
    const response = await fetch(url, { signal: AbortSignal.any([controller.signal, AbortSignal.timeout(25000)]), ...(body ? { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body) } : {}) });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  };
  const error = () => { if (active) { $('ws-error').hidden = false; $('ws-error-message').textContent = T('networkError'); } };
  const enableControls = enabled => ['ws-play','ws-reset','ws-incident','ws-replay','ws-live','ws-csv','ws-analysis'].forEach(id => { $(id).disabled = !enabled; });
  enableControls(false);
  cleanup = () => { active = false; epoch++;clearTimeout(retryTimer); controller.abort(); stream?.close(); map?.remove(); };
  function drawDiagram() {
    const current = Date.parse(snapshot.ts), start = current - 5*60000, end = current + 25*60000;
    const x = ts => 130 + (ts-start)/(end-start)*825, y = km => 32 + km/geo.length_km*322;
    let svg = `<rect width="980" height="400" fill="var(--panel)"/>`;
    for (let i=0; i<=6; i++) { const at=start+i*5*60000, px=x(at); svg += `<path d="M${px} 22V365" stroke="var(--line)"/><text x="${px}" y="388" text-anchor="middle">${time(at).slice(0,5)}</text>`; }
    for (const station of geo.stations) svg += `<path d="M130 ${y(station.km)}H955" stroke="var(--line)"/><text x="120" y="${y(station.km)+4}" text-anchor="end">${esc(station.name)}</text>`;
    const stationsById = Object.fromEntries(geo.stations.map(s=>[s.id,s]));
    for (const train of snapshot.state.trains) {
      const display = snapshot.display.find(d=>d.train_id===train.train_id), color = train.train_id===selected ? 'var(--accent)' : 'var(--muted)';
      const points = geo.timetable.filter(r=>r.train_id===train.train_id).map(r=>({ ts:Date.parse(r.scheduled_arrival||r.scheduled_departure), km:stationsById[r.station_id]?.km })).filter(p=>Number.isFinite(p.ts)&&Number.isFinite(p.km));
      if (points.length) svg += `<polyline points="${points.map(p=>`${x(p.ts)},${y(p.km)}`).join(' ')}" fill="none" stroke="${color}" stroke-dasharray="5 5" stroke-width="${train.train_id===selected?2.5:1}" opacity=".65"/>`;
      if (display) svg += `<circle data-train="${esc(train.train_id)}" cx="${x(current)}" cy="${y(display.corridor_km)}" r="${train.train_id===selected?6:3}" fill="${color}"><title>${esc(train.train_id)}</title></circle>`;
    }
    svg += `<path d="M${x(current)} 20V365" stroke="var(--accent)" stroke-width="2"/>`;
    $('ws-diagram').innerHTML = `<defs><clipPath id="ws-plot"><rect x="130" y="20" width="825" height="345"/></clipPath></defs>` + svg.replace(/(<polyline[^>]+\/>)|(<circle[^>]+>.*?<\/circle>)/g,'<g clip-path="url(#ws-plot)">$&</g>');
  }
  function drawMap() {
    if (!map) return;
    for (const train of snapshot.state.trains) {
      const block=geo.features.find(f=>f.properties.id===train.position.block_id), display=snapshot.display.find(d=>d.train_id===train.train_id);
      if (!block||!display) continue;
      const coords=block.geometry.coordinates, first=coords[0], last=coords.at(-1);
      let fraction=Math.min(1,Math.max(0,train.position.km/block.properties.length_km));
      const position=[first[1]+fraction*(last[1]-first[1]),first[0]+fraction*(last[0]-first[0])];
      let marker=markers.get(train.train_id);
      if (!marker) { marker=L.circleMarker(position,{radius:5,weight:1,fillOpacity:.9}).addTo(map).bindTooltip(train.train_id).on('click',()=>choose(train.train_id));markers.set(train.train_id,marker); }
      marker.setLatLng(position).setStyle({ color:train.train_id===selected?'#1d5fa8':'#6b4fbb',radius:train.train_id===selected?8:4 });
    }
  }
  function drawSelected() {
    const train=snapshot.state.trains.find(t=>t.train_id===selected);
    if (!train) return;
    $('ws-selected').innerHTML=`<strong class="mono">${esc(train.train_id)}</strong><dl class="fact-list"><dt>${T('speed')}</dt><dd>${train.speed.toFixed(1)}</dd><dt>${T('delay')}</dt><dd>${(train.delay_s/60).toFixed(1)}</dd></dl><p>${T('forecastBoundary')}</p><button id="ws-forecast">${T('forecast')}</button><p id="ws-forecast-result" role="status"></p>`;
    $('ws-forecast').onclick=async()=>{
      const capture=structuredClone(snapshot.state.trains.find(t=>t.train_id===selected)), infrastructure=structuredClone(snapshot.state.infra), version=snapshot.ts, selection=selected, button=$('ws-forecast');button.disabled=true;
      try { const result=await request('/forecast/advisory',{ trains:[capture], infra:infrastructure });
        if (!active||selected!==selection) return;
        const row=Array.isArray(result)?result[0]:result.forecasts?.[0]||result.advisories?.[0]||result;
        $('ws-forecast-result').textContent=`${T('captured')}: ${time(version)}. ${T('knownWait')}: ${row.known_wait_min == null ? '—' : Number(row.known_wait_min).toFixed(1)} · ${T('forecastBoundary')} ${T('heuristic')}`;
      } catch(e) { if(active&&selected===selection&&e.name!=='AbortError') $('ws-forecast-result').textContent=T('networkError'); } finally { if(button.isConnected)button.disabled=false; }
    };
  }
  function choose(id) { selected=id;drawDiagram();drawMap();drawSelected();host.querySelectorAll('[data-train]').forEach(el=>el.classList.toggle('selected-row',el.dataset.train===id)); }
  function draw(data, record=false, context={incident,incidentAt}) {
    snapshot=data;snapshotContext=context;selected ||= data.state.trains[0]?.train_id;
    if (record) { history.push({data,context});if(history.length>900)history.shift();$('ws-replay').max=history.length-1;$('ws-replay').value=history.length-1; }
    $('ws-clock').textContent=time(data.ts)+' · UTC+5';document.getElementById('global-clock').textContent=time(data.ts).slice(0,5);$('ws-count').textContent=data.state.trains.length+' SIM';
    if (!$('ws-trains').children.length) {
      $('ws-trains').innerHTML=data.state.trains.map(t=>`<tr data-id="${esc(t.train_id)}"><td><button class="train-select" data-train="${esc(t.train_id)}">${esc(t.train_id)}</button></td><td></td><td></td><td></td></tr>`).join('');
    }
    for (const row of $('ws-trains').children) {
      const train=data.state.trains.find(t=>t.train_id===row.dataset.id);
      if(!train)continue;row.classList.toggle('selected-row',train.train_id===selected);
      row.cells[1].textContent=train.position.block_id;row.cells[2].textContent=train.speed.toFixed(1);row.cells[3].textContent=(train.delay_s/60).toFixed(1);
    }
    drawDiagram();drawMap();
    // Preserve a pending forecast until selection changes; facts still update each second.
    if (!$('ws-selected').querySelector('strong') || $('ws-selected').querySelector('strong').textContent!==selected) drawSelected();
    else { const t=data.state.trains.find(t=>t.train_id===selected);const values=$('ws-selected').querySelectorAll('dd');if(t){values[0].textContent=t.speed.toFixed(1);values[1].textContent=(t.delay_s/60).toFixed(1);} }
  }
  function connect() {
    clearTimeout(retryTimer);stream?.close();if(paused||replay||!active)return;
    if (!snapshot) return;
    const query=new URLSearchParams({ elapsed:String(snapshot.elapsed_s), speed:'1', incident, incident_at:String(incidentAt) });
    stream=new EventSource('/demo/stream?'+query);
    stream.addEventListener('state',event=>{if(!active||paused||replay)return;try{draw(JSON.parse(event.data),true);$('ws-connection').textContent=T('running');$('ws-error').hidden=true;}catch{error();}});
    stream.onerror=()=>{stream.close();if(active){$('ws-connection').textContent=T('frozen');error();retryTimer=setTimeout(connect,1500);}};
  }
  async function refresh(elapsed=0) {
    const ticket=++epoch;stream?.close();$('ws-analysis-result').replaceChildren();
    try {const data=await request('/demo/snapshot?'+new URLSearchParams({ elapsed, incident, incident_at:incidentAt }));if(!active||ticket!==epoch)return;draw(data,true);$('ws-error').hidden=true;connect();}
    catch(e){if(e.name!=='AbortError')error();}
  }
  host.addEventListener('click',event=>{const element=event.target.closest('[data-train]');if(element)choose(element.dataset.train);}, {signal:controller.signal});
  $('ws-play').onclick=()=>{if(replay){const latest=history.at(-1);if(latest)draw(latest.data,false,latest.context);}paused=!paused;replay=false;$('ws-play').textContent=T(paused?'play':'pause');$('ws-connection').textContent=T(paused?'paused':'running');if(paused)stream?.close();else connect();};
  $('ws-reset').onclick=()=>{paused=false;replay=false;history=[];incidentAt=0;$('ws-play').textContent=T('pause');refresh(0);};
  $('ws-incident').onchange=()=>{incident=$('ws-incident').value;incidentAt=snapshot?.elapsed_s||0;replay=false;refresh(incidentAt);};
  $('ws-replay').oninput=()=>{const entry=history[Number($('ws-replay').value)];if(!entry)return;paused=true;replay=true;stream?.close();$('ws-play').textContent=T('play');$('ws-connection').textContent=T('paused');draw(entry.data,false,entry.context);};
  $('ws-live').onclick=()=>{const latest=history.at(-1);if(latest)draw(latest.data,false,latest.context);replay=false;paused=false;$('ws-play').textContent=T('pause');connect();};
  $('ws-csv').onclick=()=>{const lines=['timestamp,train_id,block_id,speed_kmh,delay_min'];for(const {data:s} of history)for(const t of s.state.trains)lines.push([s.ts,t.train_id,t.position.block_id,t.speed,t.delay_s/60].join(','));const url=URL.createObjectURL(new Blob(['\ufeff'+lines.join('\r\n')],{type:'text/csv;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download='jibek-joly-sim-history.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
  $('ws-analysis').onclick=async()=>{
    if(!snapshot)return;const captured={elapsed_s:snapshot.elapsed_s,incident:snapshotContext.incident,incident_at_s:snapshotContext.incidentAt,seed:42};const ticket=epoch, button=$('ws-analysis');button.disabled=true;$('ws-analysis-result').textContent=T('calculating');
    try {const result=await request('/dispatch/analysis',captured);if(!active||ticket!==epoch)return;
      $('ws-analysis-result').innerHTML=`<dl class="fact-list"><dt>${T('captured')}</dt><dd>${time(result.snapshot_time)}</dd><dt>${T('pair')}</dt><dd class="mono">${esc(result.pair_train_ids.join(' / '))}</dd><dt>CP-SAT</dt><dd>${esc(result.cp_sat.status)}</dd><dt>${T('fullPlan')}</dt><dd>${esc(result.full_cp_sat.status)}</dd></dl><p class="${result.cp_sat.valid?'good':'warn'}">${T(result.cp_sat.valid?'checked':'notChecked')}</p><p>${T('fifo')}: <span class="mono">${esc(result.fifo.ordered_train_ids.join(' → '))}</span></p><details><summary>${T('technical')}</summary><pre>${esc(JSON.stringify(result,null,2))}</pre></details>`;
    }catch(e){if(e.name!=='AbortError'){$('ws-analysis-result').textContent=T('networkError');}}finally{if(button.isConnected)button.disabled=false;}
  };
  async function initialize() { enableControls(false);$('ws-retry').disabled=true;
  try {
    [geo,snapshot]=await Promise.all([request('/infra/geometry'),request('/demo/snapshot')]);if(!active)return;
    map=L.map('ws-map',{scrollWheelZoom:false}).setView([48,73],5);L.geoJSON(geo,{style:{color:'#1d5fa8',weight:3}}).addTo(map);
    for(const s of geo.stations)L.circleMarker([s.coordinates[1],s.coordinates[0]],{radius:4,color:'#7a5c3e'}).addTo(map).bindTooltip(s.name);
    map.fitBounds(geo.stations.map(s=>[s.coordinates[1],s.coordinates[0]]),{padding:[25,25]});
    request('/kazakhstan.geojson').then(g=>{if(active)L.geoJSON(g,{style:{color:'#8a9ca6',weight:1,fillColor:dark?'#1d2835':'#e8dcc2',fillOpacity:.3}}).addTo(map).bringToBack();}).catch(()=>{});
    $('ws-error').hidden=true;draw(snapshot,true);enableControls(true);connect();
  }catch(e){if(e.name!=='AbortError')error();}finally{if(active)$('ws-retry').disabled=false;}
  }
  $('ws-retry').onclick=()=>{if(geo&&snapshot){$('ws-error').hidden=true;refresh(snapshot.elapsed_s);}else initialize();};
  initialize();
}

export function modelsPage(lang) {
  const T=key=>tr(key,lang);
  return `<div class="page-heading"><div><h1>${T('modelsTitle')}</h1><p>${T('modelsDesc')}</p></div></div><div class="model-grid">${[['pkp','forecastBoundary'],['schedule','scheduleBoundary']].map(([name,note])=>`<section class="panel"><div class="panel-head"><h2>${T(name)}</h2></div><div class="panel-body"><p>${T(note)}</p><div id="model-${name}" aria-live="polite">${T('loading')}</div><button data-model-retry="${name}">${T('retry')}</button></div></section>`).join('')}</div><p class="info">${T('legacy')}</p>`;
}
export function mountModels(lang) {
  const T=key=>tr(key,lang),controller=new AbortController();let active=true;
  cleanup=()=>{active=false;controller.abort();};
  async function load(name) {
    const target=document.getElementById('model-'+name);target.textContent=T('loading');
    try {const r=await fetch(name==='pkp'?'/forecast/model-info':'/forecast/schedule-info',{signal:AbortSignal.any([controller.signal,AbortSignal.timeout(25000)])});if(!r.ok)throw Error();const data=await r.json();if(!active)return;
      target.innerHTML=`<dl class="fact-list"><dt>${T('modelVersion')}</dt><dd class="mono">${esc(data.model_version)}</dd></dl><details><summary>${T('technical')}</summary><pre>${esc(JSON.stringify(data,null,2))}</pre></details>`;
    }catch(e){if(active&&e.name!=='AbortError')target.textContent=T('networkError');}
  }
  document.querySelectorAll('[data-model-retry]').forEach(button=>button.onclick=()=>load(button.dataset.modelRetry));load('pkp');load('schedule');
}

export function approachPanel(lang) {
  const T=key=>tr(key,lang);
  return `<section class="panel approach-panel"><div class="panel-head"><h2>${T('approachTitle')}</h2></div><div class="panel-body"><p>${T('approachNote')}</p><div class="approach-controls"><label>${T('train')} <select id="approach-train">${fleet.map((t,i)=>`<option value="${i}">${esc(t.id)}</option>`).join('')}</select></label><label>${T('distance')} <input id="approach-distance" type="number" min="0.1" max="50" step="0.1" value="4"></label><div><span>${T('window')}</span><strong id="approach-window" class="mono">—</strong></div><div><span>${T('cap')}</span><strong id="approach-cap" class="mono">—</strong></div></div><div class="approach-result"><div><span>${T('averageSpeed')}</span><strong id="approach-speed" class="mono">—</strong><p id="approach-status" role="status"></p></div><svg id="approach-plot" viewBox="0 0 400 110" role="img" aria-label="${T('averageSpeed')}"></svg></div><p class="caption">${T('syntheticPassengers')}</p></div></section>`;
}
export function mountApproach(lang,scenarioId,result,nowMin) {
  const root=document.querySelector('.approach-panel');if(!root)return;
  const T=key=>tr(key,lang), $=id=>root.querySelector('#'+id);
  const draw=()=>{
    const row=result.rows.find(r=>r.i===Number($('approach-train').value)),distanceKm=Number($('approach-distance').value),capKmh=scenarioId===2?40:80;
    const advice=distanceKm<.1||distanceKm>50?{status:'INVALID',speedKmh:null}:approachAdvice({distanceKm,nowMin,slotMin:row.start,capKmh});
    const minutes=8*60+Math.floor(row.start);
    $('approach-window').textContent=`${String(Math.floor(minutes/60)).padStart(2,'0')}:${String(minutes%60).padStart(2,'0')}`;
    $('approach-cap').textContent=capKmh;$('approach-speed').textContent=advice.speedKmh===null?'—':advice.speedKmh.toFixed(1);
    $('approach-status').textContent=T(advice.status);
    const y=85-(advice.speedKmh||0)/capKmh*65;
    $('approach-plot').innerHTML=`<path d="M30 10V85H380" fill="none" stroke="var(--muted)"/><path d="M30 20H380" stroke="var(--amber)" stroke-dasharray="4 4"/><text x="36" y="15">${capKmh} ${T('kmh')}</text>${advice.speedKmh!==null?`<path d="M30 ${y}H380" stroke="var(--accent)" stroke-width="3"/><text x="36" y="${Math.max(30,y-7)}">${advice.speedKmh.toFixed(1)} ${T('kmh')}</text>`:''}`;
  };
  $('approach-train').onchange=draw;$('approach-distance').oninput=draw;draw();
}
