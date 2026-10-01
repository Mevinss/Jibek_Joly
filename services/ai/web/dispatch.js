'use strict';
const $=id=>document.getElementById(id), esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt=(n,d=1)=>Number(n).toLocaleString('ru-RU',{maximumFractionDigits:d});
const clamp=(v,a,b)=>Math.max(a,Math.min(b,v)), fc=features=>({type:'FeatureCollection',features});
const point=(coordinates,properties={})=>({type:'Feature',geometry:{type:'Point',coordinates},properties});
const colors={ink:'#182925',green:'#146b50',late:'#895019',red:'#9b3029',line:'#d5d9ce',paper:'#f3f2ec',lime:'#dbea8b'};
let geo,country,snap,selected,map,mapReady=false,schema=false,following=false,playing=true,replaying=false,tempo=1;
let stream,retryTimer,retries=0,generation=0,receivedAt=0,lastFrame=0,lastForecast=0,forecastSeq=0,forecastController;
let history=[],forecasts=[],scheduleForecasts=[],correction={},drawn={},experiment=null,chatBusy=false,chatHistory=[],stationId='AST';
let incident='none',incidentAt=0,elapsed=0;
const reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;
const train=()=>snap?.state.trains.find(t=>t.train_id===selected);
const display=()=>snap?.display.find(t=>t.train_id===selected);
function error(message=''){$('error').textContent=message;$('error').hidden=!message;}
async function api(path,body,signal){const r=await fetch(path,{method:body?'POST':'GET',headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined,signal});if(!r.ok)throw Error(r.status===429?'Лимит запросов. Повторите через минуту.':`Сервис недоступен (${r.status}). Повторите запрос.`);return r.json();}
function clock(ts){return ts?.slice(11,19)||'—';}
function currentState(){const s=structuredClone(snap.state);if(experiment){const t=s.trains.find(t=>t.train_id===experiment.id);if(t){t.delay_s=experiment.delay*60;t.time_reserve_min=experiment.reserve;}}return s;}
function select(id){if(!snap?.state.trains.some(t=>t.train_id===id))return;selected=id;stationId=display().next_station;$('station-picker').value=stationId;experiment=null;renderInspector();renderDiagram();renderStation();calculate();if(following)focusTrain();}
function applySnapshot(data,record=true){if(record&&snap&&data.elapsed_s<snap.elapsed_s-.1&&!replaying)return;
  correction=Object.fromEntries(data.display.map(d=>[d.train_id,(drawn[d.train_id]??d.corridor_km)-d.corridor_km]));snap=data;elapsed=data.elapsed_s;receivedAt=performance.now();
  if(record){history.push(data);history=history.filter(s=>s.elapsed_s>=elapsed-900).slice(-901);$('replay').max=history.length-1;$('replay').value=history.length-1;}
  $('clock').textContent=clock(data.ts);$('connection').textContent=playing?'SSE · 1 Гц':'Пауза';renderInspector();renderDiagram();renderStation();updateInfrastructure();
  if(performance.now()-lastForecast>3000)calculate();
}
function connect(){clearTimeout(retryTimer);stream?.close();if(!playing||replaying)return;const token=++generation;
  const q=new URLSearchParams({elapsed:String(elapsed),speed:String(tempo),incident,incident_at:String(incidentAt)});stream=new EventSource('/demo/stream?'+q);
  stream.addEventListener('state',e=>{if(token!==generation)return;try{const data=JSON.parse(e.data);retries=0;applySnapshot(data);error();}catch{error('Некорректный кадр. Ожидаем следующие данные.');}});
  stream.onerror=()=>{if(token!==generation)return;stream.close();$('connection').textContent='Переподключение…';error('Поток прерван. Положение заморожено; переподключаемся автоматически.');receivedAt=0;retryTimer=setTimeout(connect,Math.min(15000,1000*2**retries++));};
}
function pause(){playing=false;generation++;stream?.close();clearTimeout(retryTimer);$('play').textContent='Продолжить';$('connection').textContent='Пауза';correction={};}
function resume(){experiment=null;if(replaying)history=history.filter(s=>s.elapsed_s<=elapsed);replaying=false;playing=true;$('play').textContent='Пауза';$('replay-label').textContent='Прямой эфир';connect();}
async function calculate(){if(!snap)return;lastForecast=performance.now();const seq=++forecastSeq;forecastController?.abort();forecastController=new AbortController();
  $('prediction').textContent='…';try{const [data,schedule]=await Promise.all([api('/forecast',currentState(),forecastController.signal),api('/forecast/schedule',currentState(),forecastController.signal).catch(()=>[])]);if(seq!==forecastSeq)return;forecasts=data;scheduleForecasts=schedule;renderForecast();}catch(e){if(e.name!=='AbortError'){$('prediction').textContent='—';$('prediction-note').textContent='Прогноз недоступен. Повторите выбор поезда.';}}
}
function renderInspector(){const t=train(),d=display();if(!t)return;$('selected-title').textContent='Поезд '+d.label.split('-').at(-1);$('train-picker').value=selected;
  $('train-kind').textContent=t.type==='груз'?'Грузовой':'Пассажирский';$('next-station').textContent=geo.stations.find(s=>s.id===d.next_station)?.name;
  $('train-speed').textContent=fmt(t.speed,0)+' км/ч';$('eta').textContent=d.eta_s===null?'Стоянка':fmt(d.eta_s/60,0)+' мин';
  if(!experiment){$('delay').value=t.delay_s/60;$('reserve').value=t.time_reserve_min;}
  $('delay-output').textContent=fmt(experiment?.delay??t.delay_s/60)+' мин';$('reserve-output').textContent=fmt(experiment?.reserve??t.time_reserve_min)+' мин';
  $('selected-key').textContent=d.label;renderForecast();
}
function renderForecast(){const k=scheduleForecasts.find(f=>f.train_id===selected);$('kz-schedule').textContent=k?`Учебная ML KZ: ${fmt(k.scheduled_segment_travel_min)} мин на весь перегон ${k.segment_id}. По синтетическому расписанию, без инцидентов.`:'Учебная модель KZ недоступна.';const f=forecasts.find(f=>f.train_id===selected);if(!f)return;$('prediction').textContent=fmt(f.expected_delay_s/60,2);
  $('model-badge').textContent=f.degraded?'Правило':'ML · перенос';$('prediction-note').textContent=f.degraded?'Правило сохраняет текущую задержку':'Оценка при выходе со следующего блока';
  $('risk').textContent=(f.degraded?'Оценка по правилу: ':'Прокси-риск: ')+fmt(f.p_conflict_15m*100)+'%';
  $('profile-note').textContent=f.degraded?'Грузовые поезда: эвристика, не обученная модель.':'Общий профиль PKP. Для Казахстана качество не измерено.';
}
function coordsAt(km){const f=geo.features.find(f=>km>=f.properties.start_km-1e-7&&km<=f.properties.end_km+1e-7)||geo.features.at(-1),p=f.properties;
  const fraction=clamp((km-p.start_km)/p.length_km,0,1),line=f.geometry.coordinates;
  // Arc-length interpolation supports future multi-vertex block geometry.
  const lengths=line.slice(1).map((b,i)=>{const a=line[i],rad=Math.PI/180;return Math.hypot((b[0]-a[0])*Math.cos((a[1]+b[1])*rad/2),b[1]-a[1]);});
  let distance=fraction*lengths.reduce((a,b)=>a+b,0);for(let i=0;i<lengths.length;i++){if(distance<=lengths[i]||i===lengths.length-1){const q=lengths[i]?distance/lengths[i]:0;return line[i].map((a,j)=>a+(line[i+1][j]-a)*q);}distance-=lengths[i];}return line[0];
}
function visualKm(d,now){const t=snap.state.trains.find(t=>t.train_id===d.train_id);const age=receivedAt?(now-receivedAt)/1000:0;
  const dt=playing&&!replaying&&!reduced?Math.min(1.3,age)*tempo:0;const p=geo.features.find(f=>f.properties.id===t.position.block_id).properties;
  const target=clamp(d.corridor_km+d.direction*t.speed*dt/3600,p.start_km,p.end_km);
  return clamp(target+(correction[d.train_id]||0)*Math.max(0,1-age/.25),0,geo.length_km);
}
function fallbackProjection([lon,lat]){const w=$('map-shell').clientWidth,h=$('map-shell').clientHeight;const extent=following&&display()?(()=>{const [x,y]=coordsAt(display().corridor_km);return[x-1,y-1,x+1,y+1];})():[67.9,42.7,78.2,54];
  const scale=Math.min((w-90)/((extent[2]-extent[0])*.67),(h-70)/(extent[3]-extent[1]));return {x:w/2+(lon-(extent[0]+extent[2])/2)*.67*scale,y:h/2-(lat-(extent[1]+extent[3])/2)*scale};}
const project=coord=>mapReady&&!schema?map.project(coord):fallbackProjection(coord);
function fit(){following=false;$('follow').setAttribute('aria-pressed','false');if(mapReady)map.fitBounds([[68.8,43.05],[77.5,53.55]],{padding:{top:35,bottom:45,left:50,right:90},duration:reduced?0:450});}
function focusTrain(){if(!display())return;if(mapReady&&!schema)map.easeTo({center:coordsAt(display().corridor_km),zoom:Math.max(7,map.getZoom()),duration:reduced?0:350});}
function updateInfrastructure(){if(!mapReady||!snap)return;const features=geo.features.map(f=>{const b=snap.state.infra.blocks.find(b=>b.id===f.properties.id);return {...f,properties:{...f.properties,closed:b.closed,occupied:b.occupied,limited:b.speed_limit<geo.features.find(x=>x.properties.id===b.id).properties.speed_limit}};});map.getSource('infra').setData(fc(features));}
function initializeMap(){try{if(!window.maplibregl)throw Error('MapLibre unavailable');map=new maplibregl.Map({container:'map',style:{version:8,sources:{},layers:[{id:'paper',type:'background',paint:{'background-color':colors.paper}}]},center:[72,49],zoom:4,attributionControl:true});
  map.addControl(new maplibregl.NavigationControl({showCompass:false}),'bottom-right');
  map.on('load',()=>{map.addSource('country',{type:'geojson',data:country});map.addLayer({id:'country-fill',type:'fill',source:'country',paint:{'fill-color':'#eaf0e5'}});map.addLayer({id:'country-edge',type:'line',source:'country',paint:{'line-color':'#b1bdad','line-width':1.5}});
    map.addSource('infra',{type:'geojson',data:geo});map.addLayer({id:'rail',type:'line',source:'infra',paint:{'line-color':colors.ink,'line-width':2}});
    map.addLayer({id:'occupied',type:'line',source:'infra',filter:['==',['get','occupied'],true],paint:{'line-color':colors.green,'line-width':4}});
    map.addLayer({id:'closed',type:'line',source:'infra',filter:['==',['get','closed'],true],paint:{'line-color':colors.red,'line-width':7,'line-dasharray':[1,1]}});
    map.addSource('trains',{type:'geojson',data:fc([])});map.addLayer({id:'train-points',type:'circle',source:'trains',paint:{'circle-radius':['case',['get','selected'],7,4],'circle-color':['get','color'],'circle-stroke-width':2,'circle-stroke-color':colors.paper}});
    mapReady=true;fit();updateInfrastructure();$('map-caption').textContent='Казахстан · локальная геометрия · подложка отключена';
  });map.on('error',()=>{if($('basemap').checked){$('basemap').checked=false;if(map.getLayer('osm-layer'))map.setLayoutProperty('osm-layer','visibility','none');$('map-caption').textContent='Подложка недоступна · локальный маршрут работает';}});
  map.getCanvas().addEventListener('webglcontextlost',e=>{e.preventDefault();setSchema(true);error('WebGL недоступен. Включена локальная схема.');});
  }catch{setSchema(true);$('map-caption').textContent='Локальная схема · WebGL недоступен';}}
function setSchema(value){schema=value;$('map').hidden=value;$('schema-mode').setAttribute('aria-pressed',String(value));$('map-mode').setAttribute('aria-pressed',String(!value));$('basemap').disabled=value;map?.resize();$('map-caption').textContent=value?'Казахстан · схема по координатам · без интернета':'Казахстан · географическая карта';}
function renderMap(now){if(!snap||!geo)return;const w=$('map-shell').clientWidth,h=$('map-shell').clientHeight;$('map-overlay').setAttribute('viewBox',`0 0 ${w} ${h}`);let html='';const path=cs=>cs.map((c,i)=>{const p=project(c);return`${i?'L':'M'}${p.x},${p.y}`;}).join(' ');
  if(schema||!mapReady){for(const f of country.features){const polys=f.geometry.type==='MultiPolygon'?f.geometry.coordinates:[f.geometry.coordinates];for(const poly of polys)html+=`<path d="${path(poly[0])}Z" fill="#eaf0e5" stroke="#b1bdad"/>`;}
    for(const f of geo.features){const b=snap.state.infra.blocks.find(b=>b.id===f.properties.id),closed=b.closed&&$('layer-restrictions').checked;html+=`<path d="${path(f.geometry.coordinates)}" fill="none" stroke="${closed?colors.red:b.occupied&&$('layer-occupancy').checked?colors.green:colors.ink}" stroke-width="${closed?6:2}" ${closed?'stroke-dasharray="3 3"':''}/>`;}}
  const selectedDisplay=display();if($('layer-forecast').checked&&selectedDisplay){const trail=history.filter(s=>s.elapsed_s<=snap.elapsed_s&&s.elapsed_s>=snap.elapsed_s-600).map(s=>s.display.find(d=>d.train_id===selected)).filter(Boolean).map(d=>coordsAt(d.corridor_km));if(trail.length>1)html+=`<path d="${path(trail)}" stroke="${colors.green}" stroke-width="2" fill="none"/>`;
    const t=train(),end=clamp(selectedDisplay.corridor_km+selectedDisplay.direction*t.speed/4,0,geo.length_km);const future=Array.from({length:25},(_,i)=>coordsAt(selectedDisplay.corridor_km+(end-selectedDisplay.corridor_km)*i/24));html+=`<path d="${path(future)}" stroke="${colors.green}" stroke-width="2" stroke-dasharray="5 5" fill="none"/>`;
    const g=project(coordsAt(selectedDisplay.scheduled_km));html+=`<circle cx="${g.x}" cy="${g.y}" r="9" fill="none" stroke="${colors.ink}" stroke-dasharray="3 3"/><text x="${g.x+13}" y="${g.y-10}">по графику</text>`;}
  for(const s of geo.stations){const p=project(s.coordinates),v=snap.stations.find(v=>v.id===s.id);const left=s.id==='KOK'||s.id==='AKK'||s.id==='KAR'||s.id==='SAR';const dx=left?-14:14;
    html+=`<g data-station="${s.id}" role="button" tabindex="0" aria-label="Станция ${esc(s.name)}"><circle cx="${p.x}" cy="${p.y}" r="10" fill="${colors.paper}" stroke="${colors.line}" stroke-width="3"/><circle cx="${p.x}" cy="${p.y}" r="10" fill="none" stroke="${v.problem?colors.red:colors.green}" stroke-width="3" stroke-dasharray="${v.occupied/v.capacity*62.83} 63" class="${v.problem?'problem-ring':''}"/><text class="station-name" x="${p.x+dx}" y="${p.y-6}" text-anchor="${left?'end':'start'}">${esc(s.name)}</text><text x="${p.x+dx}" y="${p.y+9}" text-anchor="${left?'end':'start'}">${v.occupied}/${v.capacity} путей</text></g>`;}
  const points=[];if($('layer-trains').checked){for(const d of [...snap.display].sort((a,b)=>(a.train_id===selected)-(b.train_id===selected))){const t=snap.state.trains.find(t=>t.train_id===d.train_id),km=visualKm(d,now);drawn[d.train_id]=km;const c=coordsAt(km),p=project(c),next=project(coordsAt(clamp(km+d.direction*.2,0,geo.length_km)));const angle=Math.atan2(next.y-p.y,next.x-p.x)*180/Math.PI;
      const color=d.train_id===selected?colors.lime:t.delay_s>=300?colors.late:colors.green;points.push(point(c,{selected:d.train_id===selected,color}));
      const offset=d.direction*9;p.x+=offset; // Directional visual separation; not a claim of parallel physical tracks.
      const shape=t.type==='груз'?'<rect x="-9" y="-4" width="18" height="8"/>':'<path d="M-10-4H5L11 0 5 4H-10Z"/>';
      html+=`<g data-train="${esc(d.train_id)}" role="button" tabindex="${d.train_id===selected?0:-1}" aria-label="Выбрать ${esc(d.train_id)}"><g transform="translate(${p.x},${p.y}) rotate(${angle})" fill="${color}" stroke="${colors.ink}" stroke-width="1">${shape}</g><circle cx="${p.x}" cy="${p.y}" r="14" fill="transparent"/>${d.train_id===selected?`<text x="${p.x+15}" y="${p.y+25}" font-weight="600">${esc(d.label)}</text>`:''}<title>${esc(d.train_id)} · ${fmt(t.speed,0)} км/ч · задержка ${fmt(t.delay_s/60)} мин</title></g>`;
    }}
  if(mapReady&&!schema)map.getSource('trains').setData(fc(points));
  const focus=document.activeElement?.closest('#map-overlay [data-train],#map-overlay [data-station]');const key=focus?.dataset.train||focus?.dataset.station;
  $('map-overlay').innerHTML=html;if(key)$('map-overlay').querySelector(`[data-train="${CSS.escape(key)}"],[data-station="${CSS.escape(key)}"]`)?.focus({preventScroll:true});
  if(following&&mapReady&&!schema&&selectedDisplay&&now-lastFrame>0)map.setCenter(coordsAt(drawn[selected]??selectedDisplay.corridor_km));
}
function renderDiagram(){if(!snap)return;const x=m=>190+(m+10)/25*660,y=km=>{let i=geo.stations.findIndex((s,j)=>j<geo.stations.length-1&&km>=s.km&&km<=geo.stations[j+1].km);if(i<0)i=geo.stations.length-2;const a=geo.stations[i],b=geo.stations[i+1];return 22+(i+clamp((km-a.km)/(b.km-a.km),0,1))*23;};let svg='';
  for(const s of geo.stations)svg+=`<line x1="190" x2="850" y1="${y(s.km)}" y2="${y(s.km)}" stroke="${colors.line}"/><text x="180" y="${y(s.km)+4}" text-anchor="end">${esc(s.name)}</text>`;
  for(let m=-10;m<=15;m+=5)svg+=`<line x1="${x(m)}" x2="${x(m)}" y1="18" y2="207" stroke="${m===0?colors.ink:colors.line}"/><text x="${x(m)}" y="232" text-anchor="middle">${m===0?'Сейчас':`${m>0?'+':''}${m} мин`}</text>`;
  for(const d of [...snap.display].sort((a,b)=>(a.train_id===selected)-(b.train_id===selected))){const t=snap.state.trains.find(t=>t.train_id===d.train_id),chosen=d.train_id===selected,color=chosen?colors.green:colors.muted||'#849187';
    const past=history.filter(s=>s.elapsed_s<=snap.elapsed_s&&s.elapsed_s>=snap.elapsed_s-600).map(s=>({m:(s.elapsed_s-snap.elapsed_s)/60,d:s.display.find(t=>t.train_id===d.train_id)})).filter(v=>v.d);
    const pts=past.map(v=>`${x(v.m)},${y(v.d.corridor_km)}`).join(' ');const end=clamp(d.corridor_km+d.direction*t.speed/4,0,geo.length_km);
    svg+=`<g data-train="${esc(d.train_id)}" role="button" tabindex="0" aria-label="Выбрать ${esc(d.train_id)}" opacity="${chosen?1:.55}"><polyline points="${pts}" fill="none" stroke="${color}" stroke-width="${chosen?3:1.5}"/><line x1="${x(0)}" y1="${y(d.corridor_km)}" x2="${x(15)}" y2="${y(end)}" stroke="${color}" stroke-width="${chosen?3:1.5}" stroke-dasharray="5 4"/><line x1="${x(0)}" y1="${y(d.corridor_km)}" x2="${x(15)}" y2="${y(end)}" stroke="transparent" stroke-width="9"/><circle cx="${x(0)}" cy="${y(d.corridor_km)}" r="${chosen?5:2}" fill="${color}"/><title>${esc(d.train_id)}</title></g>`;}
  const focused=document.activeElement?.closest('#diagram [data-train]')?.dataset.train;$('diagram').innerHTML=svg;if(focused)$('diagram').querySelector(`[data-train="${CSS.escape(focused)}"]`)?.focus({preventScroll:true});
}
function renderStation(){if(!snap)return;const s=geo.stations.find(s=>s.id===stationId),v=snap.stations.find(s=>s.id===stationId);let svg='';for(let i=0;i<s.tracks;i++){const y=42+i*38;svg+=`<path d="M15 100L70 ${y}H330L385 100" fill="none" stroke="${colors.line}" stroke-width="2"/><text x="74" y="${y-10}">Путь ${i+1}</text>`;if(v.trains[i])svg+=`<g data-train="${esc(v.trains[i])}" role="button" tabindex="0" aria-label="Выбрать ${esc(v.trains[i])}"><rect x="125" y="${y-7}" width="160" height="14" rx="3" fill="${v.trains[i]===selected?colors.lime:colors.green}"/><text x="205" y="${y+22}" text-anchor="middle">${esc(v.trains[i].replace('SIM-',''))}</text></g>`;}svg+=`<text x="16" y="200">Занято ${v.occupied} из ${v.capacity}${v.trains.length>v.capacity?' · очередь '+(v.trains.length-v.capacity):''}</text>`;const focused=document.activeElement?.closest('#station [data-train]')?.dataset.train;$('station').innerHTML=svg;if(focused)$('station').querySelector(`[data-train="${CSS.escape(focused)}"]`)?.focus({preventScroll:true});}
function frame(now){requestAnimationFrame(frame);if(document.hidden||now-lastFrame<(!playing||reduced?250:tempo===10?66:16))return;renderMap(now);lastFrame=now;}
async function ask(question){if(chatBusy||!snap)return;chatBusy=true;$('send').disabled=true;const snapshot=currentState(),time=clock(snap.ts);const add=(text,cls='')=>{const p=document.createElement('p');p.className='message '+cls;p.textContent=text;$('messages').append(p);return p;};add(question,'user');const reply=add('Запрашиваю инструменты…');const abort=new AbortController(),timeout=setTimeout(()=>abort.abort(),95000);let answer='',done=false;
  $('chat-context').textContent=`Снимок ${time} · ${selected} · Казахстан, перенос ML с PKP`;
  try{const messages=[...chatHistory.slice(-10),{role:'user',content:question+`\nКонтекст интерфейса: выбран ${selected}. Снимок Казахстана; перенос модели задержек PKP не валидирован.`}];const r=await fetch('/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({messages,state:snapshot,session_id:'kz-map-demo'}),signal:abort.signal});if(!r.ok)throw Error(`Ошибка ${r.status}. Повторите позже.`);
    const reader=r.body.getReader(),decoder=new TextDecoder();let buffer='';while(true){const chunk=await reader.read();buffer+=decoder.decode(chunk.value||new Uint8Array(),{stream:!chunk.done});let index;
      while((index=buffer.indexOf('\n\n'))>=0){const event=buffer.slice(0,index);buffer=buffer.slice(index+2);const kind=event.split('\n').find(l=>l.startsWith('event:'))?.slice(6).trim(),line=event.split('\n').find(l=>l.startsWith('data:'));if(!line)continue;const data=JSON.parse(line.slice(5));if(kind==='token'){answer+=data.text;reply.textContent=answer;}if(kind==='done'){done=true;$('chat-context').textContent+=` · ${data.mode==='llm'?'Ответ LLM':'Проверенная сводка'}`;}if(kind==='tool_call')reply.textContent='Проверяю данные: '+data.name;}$('messages').scrollTop=$('messages').scrollHeight;if(chunk.done)break;}
    if(!done||!answer)throw Error('Ответ прервался. Повторите вопрос.');reply.textContent=answer;chatHistory=[...messages,{role:'assistant',content:answer}];
  }catch(e){reply.textContent=e.name==='AbortError'?'Время ожидания истекло. Повторите вопрос.':e.message;}finally{clearTimeout(timeout);chatBusy=false;$('send').disabled=false;}
}
document.addEventListener('click',e=>{const t=e.target.closest('[data-train]');if(t)select(t.dataset.train);const s=e.target.closest('[data-station]');if(s){stationId=s.dataset.station;$('station-picker').value=stationId;renderStation();}});
document.addEventListener('keydown',e=>{if(['Enter',' '].includes(e.key)&&e.target.matches('svg [role=button]')){e.preventDefault();e.target.dispatchEvent(new MouseEvent('click',{bubbles:true}));}});
$('map-overlay').addEventListener('pointermove',e=>{const t=e.target.closest('[data-train]');$('hover').hidden=!t;if(t){const row=snap.state.trains.find(x=>x.train_id===t.dataset.train),d=snap.display.find(x=>x.train_id===row.train_id);$('hover').textContent=`${row.train_id} · ${fmt(row.speed,0)} км/ч · ETA ${d.eta_s===null?'стоянка':fmt(d.eta_s/60,0)+' мин'}`;}});
$('map-overlay').addEventListener('pointerleave',()=>$('hover').hidden=true);
$('train-picker').onchange=e=>select(e.target.value);$('station-picker').onchange=e=>{stationId=e.target.value;renderStation();};
$('play').onclick=()=>playing?pause():resume();$('tempo').onchange=e=>{tempo=Number(e.target.value);if(playing)connect();};
$('reset').onclick=async()=>{pause();elapsed=0;incident='none';incidentAt=0;$('incident').value='none';history=[];snap=null;experiment=null;try{applySnapshot(await api('/demo/snapshot'));resume();}catch(e){error(e.message);}};
$('incident').onchange=async e=>{incident=e.target.value;incidentAt=elapsed;pause();experiment=null;try{applySnapshot(await api('/demo/snapshot?'+new URLSearchParams({elapsed,incident,incident_at:incidentAt})));calculate();resume();if(incident!=='none')$('focus-incident').click();}catch(err){error(err.message);}};
$('focus-incident').onclick=()=>{following=false;$('follow').setAttribute('aria-pressed','false');if(mapReady&&!schema)map.fitBounds([[70,51.7],[71.3,53]],{padding:45,duration:reduced?0:400});else{stationId='AKK';$('station-picker').value=stationId;renderStation();}};
$('follow').onclick=()=>{following=!following;$('follow').setAttribute('aria-pressed',String(following));if(following)focusTrain();};$('fit').onclick=fit;
$('schema-mode').onclick=()=>setSchema(true);$('map-mode').onclick=()=>{if(mapReady)setSchema(false);else error('WebGL не загрузился. Схема доступна; обновите страницу для повторной попытки.');};
$('basemap').onchange=()=>{if(!mapReady)return;if(!map.getSource('osm')){map.addSource('osm',{type:'raster',tiles:['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],tileSize:256,maxzoom:19,attribution:'© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>'});map.addLayer({id:'osm-layer',type:'raster',source:'osm',paint:{'raster-opacity':.45,'raster-saturation':-.9}},'rail');}map.setLayoutProperty('osm-layer','visibility',$('basemap').checked?'visible':'none');$('map-caption').textContent=$('basemap').checked?'Казахстан · подложка OSM онлайн':'Казахстан · локальная геометрия';};
['trains','occupancy','forecast','restrictions'].forEach(key=>$('layer-'+key).onchange=()=>{if(!mapReady)return;const layer={trains:'train-points',occupancy:'occupied',restrictions:'closed'}[key];if(layer)map.setLayoutProperty(layer,'visibility',$('layer-'+key).checked?'visible':'none');});
['delay','reserve'].forEach(id=>$(id).oninput=()=>{pause();experiment={id:selected,delay:Number($('delay').value),reserve:Number($('reserve').value)};renderInspector();calculate();});$('clear-experiment').onclick=()=>{experiment=null;renderInspector();calculate();};
$('replay').oninput=()=>{pause();replaying=true;experiment=null;const index=Number($('replay').value);applySnapshot(history[index],false);$('replay-label').textContent=clock(snap.ts);calculate();};
$('live').onclick=()=>{if(history.length)applySnapshot(history.at(-1),false);resume();};
$('csv').onclick=()=>{const rows=['timestamp,train_id,block_id,km,speed_kmh,delay_s'];for(const s of history)for(const t of s.state.trains)rows.push([s.ts,t.train_id,t.position.block_id,t.position.km,t.speed,t.delay_s].join(','));const url=URL.createObjectURL(new Blob(['\ufeff'+rows.join('\r\n')],{type:'text/csv;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download='turkisib-kz-demo.csv';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
$('explain').onclick=()=>{$('assistant').scrollIntoView({behavior:reduced?'auto':'smooth'});ask(`Объясни прогноз для поезда ${selected}`);};
$('chat-form').onsubmit=e=>{e.preventDefault();const q=$('question').value.trim();if(q)ask(q);};
async function start(){try{const [g,c,s,h,info]=await Promise.all([api('/infra/geometry'),api('/kazakhstan.geojson'),api('/demo/snapshot'),api('/health'),api('/forecast/model-info')]);geo=g;country=c;selected=s.state.trains[0].train_id;
  $('train-picker').innerHTML=s.display.map(d=>`<option value="${esc(d.train_id)}">${esc(d.label)}</option>`).join('');$('train-picker').disabled=false;
  $('station-picker').innerHTML=geo.stations.map(s=>`<option value="${s.id}">${esc(s.name)}</option>`).join('');$('station-picker').value=stationId;
  $('chat-provider').textContent=h.llm_configured?'OpenAI настроен':'Резервная сводка · без ключа';$('quality').textContent=info.regression?`На тесте PKP: средняя ошибка ${fmt(info.regression.mae,2)} мин; ROC-AUC ${fmt(info.classification.roc_auc,3)}; точность предупреждений ${fmt(info.classification.precision*100)}%, полнота ${fmt(info.classification.recall*100)}%.`:'Модель недоступна: используются правила.';
  api('/forecast/schedule-info').then(k=>{$('kz-quality').textContent=`Учебная модель на вашем архиве KZ: ${k.rows.total} перегонов, ${k.rows.test} строк теста. Ошибка ${fmt(k.metrics.mae_min,2)} мин на SIM-рейсах; на незнакомом перегоне — ${fmt(k.metrics.unseen_shu_almaty_mae_min)} мин. Это воспроизведение расписания, не прогноз фактических задержек.`;}).catch(()=>{$('kz-quality').textContent='Учебная модель KZ недоступна.';});applySnapshot(s);calculate();initializeMap();$('play').disabled=false;connect();requestAnimationFrame(frame);
}catch(e){$('connection').textContent='Нет подключения';error(e.message+' Проверьте запуск сервиса и обновите страницу.');}}
const chartResize=new ResizeObserver(()=>{for(const [id,units] of [['diagram',880],['station',400]]){const svg=$(id);if(svg.clientWidth)svg.style.setProperty('--label-size',`${Math.max(12,12*units/svg.clientWidth)}px`);}});chartResize.observe($('diagram'));chartResize.observe($('station'));
start();
