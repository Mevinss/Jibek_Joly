'use strict';
const $ = id => document.getElementById(id);
const esc = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const number = (value, digits = 1) => Number(value).toLocaleString('ru-RU', {maximumFractionDigits:digits, minimumFractionDigits:digits});
const trainType = type => ({'пасс':'Пассажирский','скоростной':'Скоростной','груз':'Грузовой'}[type] || type);
let state, initial, selected, forecasts = [], revision = 1, pending = 0, timer, controller, threshold = .1036324786;
let chatBusy = false, history = [], scenarioReady = false;
const selectedTrain = () => state.trains.find(t => t.train_id === selected);
const selectedBlock = () => state.infra.blocks.find(b => b.id === selectedTrain().position.block_id);
const controls = ['preset','reset','train-type','delay','reserve','technical','restriction','closure','ask-train'];
function enableControls(enabled) { controls.forEach(id => $(id).disabled = !enabled); }
async function api(path, body, signal) {
  const response = await fetch(path, {method:body ? 'POST' : 'GET', headers:body ? {'Content-Type':'application/json'} : {}, body:body ? JSON.stringify(body) : undefined, signal});
  if (!response.ok) throw new Error(response.status === 429 ? 'Лимит запросов. Повторите через минуту.' : `Сервис вернул ошибку ${response.status}. Повторите расчёт или обновите страницу.`);
  return response.json();
}
function showError(message) { $('error').textContent = message; $('error').hidden = !message; }
function parameters() {
  const t = selectedTrain(), b = selectedBlock();
  $('selected-title').textContent = `Поезд ${t.train_id}`;
  $('train-type').value = t.type;
  $('delay').value = t.delay_s / 60;
  $('reserve').value = t.time_reserve_min;
  $('technical').value = t.min_technical_time_min;
  $('restriction').checked = b.speed_limit < 100;
  $('closure').checked = b.closed;
  labels();
}
function labels() {
  $('delay-value').textContent = `${number($('delay').value)} мин`;
  $('reserve-value').textContent = `${number($('reserve').value)} мин`;
}
function selectTrain(id) {
  if (!state.trains.some(t => t.train_id === id)) return;
  selected = id;
  parameters(); renderTrains(); renderResult(); calculate();
}
function renderTrains() {
  const focused = document.activeElement;
  const focusTarget = focused?.matches('[data-train]') ? {id:focused.dataset.train, container:focused.closest('#tracks') ? 'tracks' : 'trains'} : null;
  const query = $('search').value.trim();
  const filtered = state.trains.filter(t => t.train_id.includes(query));
  $('train-count').textContent = state.trains.length;
  $('empty').hidden = filtered.length > 0;
  $('trains').innerHTML = filtered.map(t => {
    const f = forecasts.find(r => r.train_id === t.train_id);
    return `<tr class="${selected === t.train_id ? 'selected' : ''}"><td><button class="train-select" data-train="${esc(t.train_id)}" aria-pressed="${selected === t.train_id}">${esc(t.train_id)}<small>${esc(trainType(t.type))}</small></button></td><td>${esc(t.position.block_id)}</td><td>${number(t.delay_s/60)}</td><td>${f ? number(f.expected_delay_s/60) : '—'}</td><td class="risk-cell ${f?.alert ? 'alert' : ''}">${f ? `${number(f.p_conflict_15m*100)}%` : '—'}${f?.degraded ? '<span class="heuristic">правило</span>' : ''}</td></tr>`;
  }).join('');
  $('tracks').innerHTML = state.infra.blocks.map(b => `<div class="segment" aria-label="Перегон ${esc(b.id)}">${state.trains.filter(t => t.position.block_id === b.id).map(t => `<button class="train-marker ${forecasts.find(f => f.train_id === t.train_id)?.alert ? 'alert' : ''}" data-train="${esc(t.train_id)}" aria-label="Выбрать поезд ${esc(t.train_id)}" aria-pressed="${selected === t.train_id}">${esc(t.train_id)}</button>`).join('')}</div>`).join('');
  if (focusTarget) $(focusTarget.container).querySelector(`[data-train="${CSS.escape(focusTarget.id)}"]`)?.focus({preventScroll:true});
}
function renderResult() {
  const f = forecasts.find(row => row.train_id === selected), t = selectedTrain();
  if (!f) return;
  $('expected').textContent = number(f.expected_delay_s / 60);
  const delta = (f.expected_delay_s-t.delay_s)/60;
  $('delta').textContent = f.degraded ? 'Правило сохраняет текущее опоздание' : Math.abs(delta) < .05 ? `Изменение менее ${number(.05)} мин` : `${delta > 0 ? '+' : ''}${number(delta)} мин к текущему опозданию`;
  $('risk').textContent = `${number(f.p_conflict_15m*100)}%`;
  $('risk-fill').style.transform = `scaleX(${f.p_conflict_15m})`;
  $('risk-fill').style.background = f.alert ? 'var(--amber)' : 'var(--green)';
  $('threshold-mark').style.left = `${threshold*100}%`;
  $('risk-label').textContent = f.degraded ? 'Эвристическая оценка риска' : 'Вероятность прокси-события';
  $('risk-note').textContent = `${f.alert ? 'Выше' : 'Ниже'} порога ${number(threshold*100)}%. Не вероятность столкновения.`;
  $('model-badge').textContent = f.degraded ? 'Правило · не ML' : 'LightGBM';
  $('fallback-note').hidden = !f.degraded;
  $('fallback-note').textContent = 'Для этого типа поезда или состояния модель недоступна. Оценка по правилам не калибрована.';
  $('factor-method').textContent = f.degraded ? 'Эвристика' : 'SHAP';
  const max = Math.max(.01,...f.top_features.map(x => Math.abs(x.impact)));
  $('factors').innerHTML = f.top_features.map(x => `<div><div class="factor-head"><span>${esc(x.name)}</span><strong>${x.impact > 0 ? '+' : ''}${number(x.impact,3)}</strong></div><div class="factor-bar"><i class="${x.impact > 0 ? 'positive' : ''}" style="width:${Math.abs(x.impact)/max*100}%"></i></div></div>`).join('');
  $('factor-note').textContent = f.degraded ? 'Показан вклад в правило. Это не SHAP и не результат обученной модели.' : 'Вклад в логарифм шансов до калибровки: плюс повышает оценку, минус снижает. Это не доказательство причины задержки.';
}
function renderCurve(results, levels) {
  const left=42, right=603, top=18, bottom=151;
  const ceiling = Math.max(.2, Math.ceil(Math.max(...results.map(r=>r.p_conflict_15m))*10)/10);
  const x = v => left + v/30*(right-left), y = v => bottom - v/ceiling*(bottom-top);
  let svg = [0,ceiling/2,ceiling].map(v => `<line x1="${left}" x2="${right}" y1="${y(v)}" y2="${y(v)}" stroke="#d5d9ce"/><text x="32" y="${y(v)+4}" text-anchor="end">${Math.round(v*100)}%</text>`).join('');
  svg += `<line x1="${left}" x2="${right}" y1="${y(threshold)}" y2="${y(threshold)}" stroke="#895019" stroke-dasharray="4 4"/>`;
  svg += `<polyline points="${results.map((r,i)=>`${x(levels[i])},${y(r.p_conflict_15m)}`).join(' ')}" fill="none" stroke="#146b50" stroke-width="2.5"/>`;
  svg += results.map((r,i) => `<circle cx="${x(levels[i])}" cy="${y(r.p_conflict_15m)}" r="3.5" fill="#146b50"><title>${levels[i]} мин: ${number(r.p_conflict_15m*100)}%</title></circle><text x="${x(levels[i])}" y="174" text-anchor="middle">${levels[i]}</text>`).join('');
  const f = forecasts.find(r=>r.train_id===selected);
  svg += `<circle cx="${x(selectedTrain().delay_s/60)}" cy="${y(f.p_conflict_15m)}" r="6" fill="#dbea8b" stroke="#182925" stroke-width="2"><title>Текущий сценарий: ${number(f.p_conflict_15m*100)}%</title></circle>`;
  $('curve').innerHTML = svg;
  $('curve').setAttribute('aria-label', `Оценка риска при опоздании: ${results.map((r,i)=>`${levels[i]} минут — ${number(r.p_conflict_15m*100)} процентов`).join('; ')}`);
  $('curve-current').textContent = `Выбранная точка: ${number(selectedTrain().delay_s/60)} мин · ${number(f.p_conflict_15m*100)}%`;
}
async function calculate() {
  clearTimeout(timer);
  controller?.abort(); controller = new AbortController();
  const signal = controller.signal, sequence = ++pending;
  scenarioReady = false;
  $('calculation').textContent = 'Расчёт…';
  $('forecast-result').setAttribute('aria-busy','true');
  const snapshot = structuredClone(state), train = structuredClone(selectedTrain());
  const levels = [0,5,10,15,20,25,30];
  const sweep = {infra:snapshot.infra, trains:levels.map((delay,i)=>({...train,train_id:`curve-${i}`,delay_s:delay*60}))};
  try {
    const [result, curve] = await Promise.all([api('/forecast',snapshot,signal),api('/forecast',sweep,signal)]);
    if(sequence !== pending) return;
    forecasts = result; scenarioReady = true;
    renderTrains(); renderResult(); renderCurve(curve,levels);
    $('calculation').textContent = 'Рассчитано';
    $('connection').textContent = 'Сервис доступен';
    showError('');
  } catch(error) {
    if(error.name === 'AbortError') return;
    if(sequence !== pending) return;
    forecasts=[]; renderTrains();
    $('expected').textContent='—'; $('risk').textContent='—'; $('risk-fill').style.transform='scaleX(0)'; $('factors').textContent='Расчёт недоступен'; $('curve').innerHTML='';
    $('delta').textContent='Прогноз не рассчитан'; $('curve-current').textContent='';
    $('calculation').textContent='Ошибка'; $('connection').textContent='Ошибка расчёта';
    showError(`${error.message} Для повторной попытки измените параметр или сбросьте сценарий.`);
  } finally { if(sequence === pending) $('forecast-result').setAttribute('aria-busy','false'); }
}
function edited() {
  clearTimeout(timer);
  revision++; $('revision').textContent=`Сценарий ${revision}`;
  // Invalidate immediately: a slow response for the prior slider value must not render.
  pending++; controller?.abort(); scenarioReady=false;
  $('calculation').textContent='Пересчёт…';
  $('chat-context').textContent='Новый вопрос будет отправлен с изменённым сценарием';
  timer=setTimeout(calculate,180);
}
function changeParameters() {
  if (!$('technical').checkValidity()) { $('technical').reportValidity(); return; }
  const t=selectedTrain(), b=selectedBlock();
  t.type=$('train-type').value; t.delay_s=Number($('delay').value)*60; t.time_reserve_min=Number($('reserve').value); t.min_technical_time_min=Number($('technical').value);
  b.speed_limit=$('restriction').checked ? 60 : 100; b.closed=$('closure').checked;
  labels(); edited();
}
function addMessage(role, text) {
  const article=document.createElement('article'); article.className=`message ${role}-message`;
  const speaker=document.createElement('span'); speaker.className='speaker'; speaker.textContent=role==='user'?'Вы':'Ассистент';
  const p=document.createElement('p'); p.textContent=text;
  article.append(speaker,p); $('messages').append(article); $('messages').scrollTop=$('messages').scrollHeight;
  return {article,p,speaker};
}
async function ask(question) {
  if(chatBusy || !state) return;
  chatBusy=true; $('send').disabled=true; $('clear-chat').disabled=true;
  const sentRevision=revision, snapshot=structuredClone(state);
  addMessage('user',question); $('question').value='';
  const reply=addMessage('assistant','Проверяю данные сценария…');
  reply.speaker.textContent=`Ассистент · сценарий ${sentRevision}`;
  const trace=document.createElement('div'); trace.className='tool-trace'; reply.article.append(trace);
  let answer='', done=false, sourceNames=[];
  const timeoutController=new AbortController(); const timeout=setTimeout(()=>timeoutController.abort(),100000);
  try {
    const messages=[...history.slice(-18),{role:'user',content:question}];
    const response=await fetch('/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({messages,state:snapshot,session_id:'interactive-demo'}),signal:timeoutController.signal});
    if(!response.ok) throw new Error(response.status===429?'Достигнут лимит запросов. Подождите минуту.':`Ассистент недоступен (${response.status}). Повторите вопрос.`);
    const reader=response.body.getReader(), decoder=new TextDecoder(); let buffer='';
    while(true) {
      const chunk=await reader.read(); buffer+=decoder.decode(chunk.value || new Uint8Array(),{stream:!chunk.done});
      let boundary;
      while((boundary=buffer.indexOf('\n\n'))!==-1) {
        const frame=buffer.slice(0,boundary); buffer=buffer.slice(boundary+2);
        const event=frame.split('\n').find(x=>x.startsWith('event:'))?.slice(6).trim();
        const dataLine=frame.split('\n').find(x=>x.startsWith('data:'));
        if(!dataLine) continue;
        const data=JSON.parse(dataLine.slice(5));
        if(event==='token'){answer+=data.text;reply.p.textContent=answer;}
        if(event==='tool_call'){sourceNames.push(data.name);trace.textContent=`Инструменты: ${[...new Set(sourceNames)].join(' → ')}`;}
        if(event==='error'){trace.textContent='API недоступен. Готовится сводка по данным.';}
        if(event==='done'){done=true;const modeLabel={llm:'Ответ LLM',tool_summary:'Проверенная сводка по данным',refusal:'Ограничение действий',template:'Резервная сводка',grounding_fallback:'Сводка после проверки ответа'};trace.textContent+=` · ${modeLabel[data.mode] || 'Сводка по данным'}`;}
      }
      $('messages').scrollTop=$('messages').scrollHeight;
      if(chunk.done) break;
    }
    if(!done || !answer) throw new Error('Ответ прервался. Повторите вопрос.');
    history=[...messages,{role:'assistant',content:answer}].slice(-18);
    $('chat-context').textContent=sentRevision===revision?`Ответ по сценарию ${sentRevision}`:`Ответ по сценарию ${sentRevision}; на экране уже ${revision}`;
  } catch(error) { reply.p.textContent=error.name==='AbortError'?'Ассистент не успел ответить. Повторите вопрос.':error.message; }
  finally {clearTimeout(timeout);chatBusy=false;$('send').disabled=false;$('clear-chat').disabled=false;}
}
document.addEventListener('click',event=>{
  const train=event.target.closest('[data-train]'); if(train) selectTrain(train.dataset.train);
  const suggestion=event.target.closest('[data-question]'); if(suggestion && state) ask(suggestion.dataset.question==='forecast'?`Объясни прогноз для поезда ${selected}`:`Что известно о поезде ${selected}?`);
});
$('search').addEventListener('input',()=>{if(state) renderTrains();});
$('parameters').addEventListener('submit',event=>event.preventDefault());
['train-type','delay','reserve','technical','restriction','closure'].forEach(id=>$(id).addEventListener('input',changeParameters));
$('preset').addEventListener('change',()=>{const t=selectedTrain();if($('preset').value==='initial'){state=structuredClone(initial);}else if($('preset').value==='delay'){t.delay_s=1200;}else if($('preset').value==='reserve'){t.time_reserve_min=12;}else if($('preset').value==='freight'){t.type='груз';}parameters();edited();});
$('reset').addEventListener('click',()=>{state=structuredClone(initial);$('preset').value='initial';parameters();edited();});
$('ask-train').addEventListener('click',()=>{$('assistant').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth'});ask(`Объясни прогноз для поезда ${selected}`);});
$('chat-form').addEventListener('submit',event=>{event.preventDefault();const q=$('question').value.trim();if(q) ask(q);});
$('clear-chat').addEventListener('click',()=>{if(chatBusy)return;history=[];$('messages').replaceChildren();addMessage('assistant','История очищена. Следующий вопрос использует текущий сценарий.');});
async function start() {
  enableControls(false); $('send').disabled=true;
  try {
    const [seed,health,info]=await Promise.all([api('/demo/state'),api('/health'),api('/forecast/model-info')]);
    initial=seed.state;state=structuredClone(initial);selected=state.trains[0].train_id;
    threshold=info.threshold ?? threshold;
    $('connection').textContent='Сервис доступен';
    $('chat-provider').textContent=health.llm_configured?'OpenAI настроен · прогноз в проверенной форме':'Без ключа API · шаблонная сводка';
    $('model-version').textContent=info.model_version;
    $('quality').textContent=info.regression?`На тесте PKP (${number(info.rows.test,0)} строк) средняя абсолютная ошибка изменения задержки — ${number(info.regression.mae,2)} мин. ROC-AUC — ${number(info.classification.roc_auc,3)}. При выбранном пороге полнота — ${number(info.classification.recall*100)}%, точность предупреждений — ${number(info.classification.precision*100)}%. Значительная часть предупреждений ложная.`:'Обученная модель недоступна. Используется резервная эвристика.';
    parameters();renderTrains();enableControls(true);$('send').disabled=false;await calculate();
  }catch(error){$('connection').textContent='Нет подключения';showError(`Не удалось загрузить демо. Проверьте запуск сервиса и обновите страницу. ${error.message}`);}
}
start();
