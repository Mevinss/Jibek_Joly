import {nodes,approach,action,nextRelease,incidentFor} from './corridor-engine.js';
import {stationArrivals} from './arrivals.js';
let apiReport=null;
const strings=await Promise.all(['ru','kk'].map(async locale=>{
 const response=await fetch(new URL(`./locales/${locale}.json`,import.meta.url));
 if(!response.ok)throw Error(`Locale ${locale}: ${response.status}`);
 return response.json();
}));
export const ecoText=(key,lang=0)=>strings[lang?1:0][key]||key;
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const clock=m=>{const n=480+Math.floor(m);return `${String(Math.floor(n/60)).padStart(2,'0')}:${String(n%60).padStart(2,'0')}`;};
const decimal=n=>Number(n).toFixed(1);
const panel=(title,body,extra='')=>`<section class="panel eco-panel"><div class="panel-head"><h2>${title}</h2>${extra}</div><div class="panel-body">${body}</div></section>`;
export function arrivalRows(w,station,lang=0){
 const T=key=>ecoText(key,lang),rows=stationArrivals(w,station);
 return `${rows.length?`<div class="arrival-list">${rows.map(r=>`<button class="arrival-row" data-act="train" data-id="${r.id}" style="--train:${r.color}"><span><b>${r.id}</b><small class="${r.severity}">${r.delay_minutes===null?T(r.held?'held':'unknownEta'):`${T('delay')} +${Math.ceil(r.delay_minutes)} ${T('min')}${r.severity==='bad'?' · '+T('attention'):''}`}</small></span><span class="arrival-time ${r.severity}"><b>${r.eta_minutes===null?'—':r.eta_minutes<.05?T('atStation'):`${Math.max(0,Math.ceil(r.eta_minutes-.05))} ${T('min')}`}</b><small>${r.arrival===null?T('unknownEta'):clock(r.arrival)}</small></span></button>`).join('')}</div>`:`<p class="empty">${T('empty')}</p>`}<p class="meta eco-note">${T('boardNote')}</p>`;
}
export function arrivalPanel(w,station=4,lang=0){
 const T=key=>ecoText(key,lang);
 return panel(T('board'),`<label class="eco-station-picker">${T('station')}<select id="eco-station">${nodes.map((n,i)=>`<option value="${i}" ${i===station?'selected':''}>${n.name}</option>`).join('')}</select></label>${arrivalRows(w,station,lang)}`,`<span class="pill">${nodes[station].name}</span>`);
}
function profileChart(a,cap,lang){
 const T=key=>ecoText(key,lang),points=a.recommended_speed_profile,distance=points.at(-1).distance_km;
 const X=x=>55+x/distance*485,Y=v=>170-v/Math.max(cap,1)*135;
 return `<figure class="eco-profile"><figcaption>${T('profile')}</figcaption><svg viewBox="0 0 565 220" role="img" aria-label="${T('profile')}: ${decimal(a.recommended_speed_kmh)} ${T('kmh')}">${[0,.5,1].map(f=>`<line x1="55" x2="540" y1="${Y(cap*f)}" y2="${Y(cap*f)}" stroke="var(--line)"/><text x="44" y="${Y(cap*f)+4}" text-anchor="end">${Math.round(cap*f)}</text><text x="${X(distance*f)}" y="193" text-anchor="middle">${decimal(distance*f)}</text>`).join('')}<path d="M55 ${Y(cap)} H540" stroke="var(--amber)" fill="none" stroke-width="2" stroke-dasharray="5 5"/><polyline points="${points.map(p=>`${X(p.distance_km)},${Y(p.speed_kmh)}`).join(' ')}" stroke="var(--accent)" fill="none" stroke-width="4"/><circle cx="540" cy="${Y(a.recommended_speed_kmh)}" r="5" fill="var(--accent)"/><text x="55" y="18">${T('kmh')}</text><text x="540" y="216" text-anchor="end">${T('km')}</text></svg><div class="eco-legend"><span class="good">━ ${T('recommended')}</span><span class="warn">┄ ${T('limit')}</span></div></figure>`;
}
export function ecoPanel(w,id,lang=0,readOnly=false){
 const T=key=>ecoText(key,lang),t=w.trains.find(x=>x.id===id)||w.trains[0],a=approach(w,t);
 const station=t.segment===null?t.node:t.dir>0?t.segment+1:t.segment;
 const arrival=stationArrivals(w,station).find(r=>r.id===t.id);
 const active=t.type===2&&a.status==='AVAILABLE',known=nextRelease(w,t),inc=t.segment===null?null:incidentFor(w,t.segment),cap=t.lane==='reserve'?t.maxSpeedKmh*.8:inc?.type==='slow'?Math.min(t.maxSpeedKmh,40):t.maxSpeedKmh;
 const kpi=(label,value,unit='')=>`<div><small>${label}</small><strong>${value}<small>${unit}</small></strong></div>`;
 return panel(`${T('title')} · <span style="color:${t.color}">${t.id}</span>`, `<div class="eco-target"><span>${T('to')} <b>${nodes[station].name}</b></span><strong>${t.finished!==null?T('arrived')+' '+clock(t.finished):arrival?.eta_minutes==null?'—':Math.max(0,Math.ceil(arrival.eta_minutes-.05))+' '+T('min')}</strong></div><div class="eco-kpis">${kpi(T('current'),Math.round(t.actualSpeed||0),T('kmh'))}${kpi(T('recommended'),active?Math.round(a.recommended_speed_kmh):'—',active?T('kmh'):'')}${kpi(T('limit'),Math.round(cap),T('kmh'))}</div>${t.type===2?`<p class="meta">${T('mass')}: ${t.massTons} ${T('tons')}</p>`:''}${active?`<div class="eco-window"><span>${T('green')}</span><strong>${clock(known)}</strong></div>${a.full_stop_avoided?`<div class="eco-badge good"><b>${T('predictedAvoid')}</b><small>full stop avoided · ${T('predicted')}</small></div>`:''}${profileChart(a,cap,lang)}<div class="eco-proxy"><span>${T('proxy')}</span><div><b>${decimal(a.baseline_energy_proxy_units)}</b> → <b class="good">${decimal(a.energy_proxy_units)}</b></div><small>${T('baseline')} / ${T('withEco')}</small></div><p class="meta eco-note">${T('proxyNote')}</p><button class="small" data-eco="check" data-id="${t.id}">${T('apiCheck')}</button><p id="eco-api-result" class="meta" role="status">${apiReport?.id===t.id&&Math.abs(apiReport.time-w.time)<.001?esc(apiReport.text):''}</p>`:`<div class="eco-empty">${T(t.type!==2?'passenger':a.status)}</div>`}${t.full_stop_avoided?`<div class="eco-badge good"><b>${T('confirmedAvoid')} · ${t.full_stop_avoided}</b><small>full stop avoided · ${T('confirmed')}</small></div>`:''}<p class="meta eco-note">${T('modelNote')}</p>${readOnly?`<p class="meta">${T('readOnly')}</p>`:''}`, `<button class="small eco-toggle ${w.eco?'good':''}" data-eco="toggle" aria-label="${T('toggle')}" aria-pressed="${!!w.eco}" ${readOnly?'disabled':''}>${T(w.eco?'on':'off')}</button>`);
}
export function dataPanel(w,lang=0,readOnly=false){
 const T=key=>ecoText(key,lang);
 return `<div class="page-heading"><div><h1>${T('dataTitle')}</h1><p>${T('dataLead')}</p></div></div>`+panel(T('package'),`<p><code>kz-eco-synthetic-v1</code> · seed 20261002</p><p class="meta eco-note">${T('packageNote')}</p><p class="eco-note">${T('signalNote')}</p><a href="/eco/package" target="_blank" rel="noopener">${T('export')} ↗</a>`)+panel(T('apiTitle'),`<div class="api-rows"><div><b>POST</b><code>/eco/advice</code></div><div><b>GET</b><code>/eco/package</code></div></div><p class="meta eco-note">${T('apiNote')}</p><pre class="eco-code">energy_proxy_units\nfull_stop_avoided\nrecommended_speed_profile\ntarget_arrival_time</pre><a href="/docs" target="_blank" rel="noopener">${T('docs')} ↗</a>`)+panel('I = Σ(wᵢ × fᵢ) / Σwᵢ',`<p>${T('indexNote')}</p><p class="meta eco-note">${T('comparisonNote')}</p>`)+ecoPanel(w,w.trains[4].id,lang,readOnly);
}
export function ecoComparison(before,after,lang=0){
 const T=key=>ecoText(key,lang),sum=(w,key)=>w.trains.reduce((s,t)=>s+(t[key]||0),0);
 return panel(T('title'),`<div class="table-wrap"><table><thead><tr><th></th><th>${T('comparisonBefore')}</th><th>${T('comparisonAfter')}</th><th>${T('delta')}</th></tr></thead><tbody>${[['energy', 'energy'],['stops','fullStops'],['avoidCount','full_stop_avoided']].map(([label,key])=>{const a=sum(before,key),b=sum(after,key),d=b-a;return `<tr><td>${T(label)}</td><td>${decimal(a)}</td><td>${decimal(b)}</td><td class="${key==='full_stop_avoided'?(d>0?'good':''):(d<0?'good':d>0?'warn':'')}">${d>0?'+':''}${decimal(d)}</td></tr>`;}).join('')}</tbody></table></div><p class="meta eco-note">${T('comparisonNote')}</p>`);
}
export function attachEco(B){
 document.addEventListener('click',async event=>{
  const button=event.target.closest('[data-eco]');if(!button)return;
  const w=B.world(),lang=B.lang(),T=key=>ecoText(key,lang);
  if(button.dataset.eco==='toggle'){if(!B.canEdit())return;action(w,'eco');B.paint();return;}
  const t=w.trains.find(t=>t.id===button.dataset.id),a=approach(w,t);
  if(!t||a.status!=='AVAILABLE')return;
  const field=document.getElementById('eco-api-result');if(!field)return;
  const cap=t.lane==='reserve'?t.maxSpeedKmh*.8:incidentFor(w,t.segment)?.type==='slow'?Math.min(t.maxSpeedKmh,40):t.maxSpeedKmh;
  const body={train_id:t.id,distance_km:a.recommended_speed_profile.at(-1).distance_km,current_speed_kmh:cap,speed_limit_kmh:cap,now_min:w.time,signal_open_min:nextRelease(w,t),mass_tons:t.massTons};
  B.pause();button.disabled=true;apiReport={id:t.id,time:w.time,text:T('apiWait')};field.textContent=apiReport.text;
  try{
   const response=await fetch('/eco/advice',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
   if(!response.ok)throw Error(`HTTP ${response.status}`);
   const data=await response.json();
   apiReport.text=`${T('apiOk')} · ${clock(body.now_min)} · ${data.recommended_speed_kmh==null?T(data.status):decimal(data.recommended_speed_kmh)+' '+T('kmh')}`;if(field.isConnected)field.textContent=apiReport.text;
  }catch{apiReport.text=T('apiError');if(field.isConnected)field.textContent=apiReport.text;}
  finally{if(button.isConnected)button.disabled=false;}
 });
}
