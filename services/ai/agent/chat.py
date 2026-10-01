import asyncio
import json
import re
from datetime import datetime, timezone
from .provider import respond, output_text, ProviderUnavailable
from .grounding import unsupported_numbers

REFUSAL = 'Не могу управлять движением, разрешать проезд на запрещающий сигнал или раскрывать секреты. Решение принимает диспетчер. Могу показать данные и рассмотреть сценарий в песочнице.'


def blocked(text):
    text = text.lower()
    return bool(re.search(r'(раскр|покаж|вывед|скажи|пришли).{0,35}(ключ|секрет|системн.*промпт)|на красн|игнорируй.*инструк|ignore.*instruction|api.?key|system prompt', text))


def fallback_calls(question):
    q = question.lower()
    if 'закры' in q or 'what' in q or 'вариант' in q:
        minutes = re.search(r'(\d+)\s*мин', q)
        target = re.search(r'([абвabc])\s*[-–—]\s*([абвabc])', q)
        if not minutes or not target:
            return []
        block = '-'.join(target.groups()).upper()
        return [('run_whatif', {'incident': {'id': 'whatif-demo', 'kind': 'block_closed',
                 'target_id': block, 'params': {'minutes': int(minutes.group(1))},
                 'ts': datetime.now(timezone.utc).isoformat()}})]
    train = re.search(r'(SIM-[A-Z_]+-[FR]\d+)', question, re.I) or re.search(r'(?<!\d)(\d{3,6})(?!\d)', q)
    if train and ('учебн' in q or 'расписан' in q or 'kz' in q):
        return [('get_schedule_forecast', {'train_id': train.group(1)})]
    if 'скорост' in q or 'профиль' in q:
        return [('get_advice', {'train_id': train.group(1)})] if train else []
    if 'прогноз' in q or 'риск' in q or 'конфликт' in q:
        return [('get_forecast', {'train_id': train.group(1)} if train else {})]
    if train:
        return [('get_train_status', {'train_id': train.group(1)})]
    if 'индекс' in q: return [('get_index', {})]
    if 'инцидент' in q: return [('get_incidents', {})]
    if 'план' in q: return [('get_plan', {})]
    if 'поезд' in q: return [('list_trains', {})]
    return []


def template(evidence):
    if not evidence:
        return 'Недостаточно данных для ответа. Уточните поезд или перегон и длительность сценария. Могу показать план, индекс, прогноз или инциденты.'
    lines = ['Консультативная сводка. ' + ('Используется сценарий из интерактивного демо.' if any(e.get('source') == 'demo_snapshot' for e in evidence) else 'Используются демонстрационные фикстуры.' if any(e.get('source') == 'fixture' for e in evidence) else 'Данные получены через API.')]
    for result in evidence:
        data = result.get('data', {})
        if result.get('error') or isinstance(data, dict) and data.get('error'):
            lines.append('Запрошенные сведения недоступны; результат не рассчитан.')
        elif isinstance(data, list) and data and all('reliable' in r and 'current_delay_min' in r for r in data):
            for row in data:
                lines.append(f"Поезд {row['train_id']}: текущая задержка {row['current_delay_min']:.1f} мин.")
                if row.get('known_wait_min') is not None:
                    lines.append(f"Известное ожидание {row['known_wait_min']:.1f} мин.")
                if row.get('restriction_extra_min'):
                    lines.append(f"Демонстрационная добавка ограничения {row['restriction_extra_min']:.1f} мин.")
                if row['reliable']:
                    interval = row['delay_interval_min']
                    lines.append(f"Интервал PKP {interval[0]:.1f}–{interval[2]:.1f} мин; вероятность роста задержки на следующем перегоне {row['delay_growth_probability'] * 100:.1f}%.")
                    lines.append('Это прогноз модели, не подтверждённый конфликт и не причина задержки.')
                else:
                    reason = 'перенос модели PKP на синтетический Казахстан не проверен' if 'unvalidated_kazakhstan' in row.get('reasons', []) else 'входные данные вне проверенного применения модели'
                    lines.append(f'Численная ML-добавка и риск недоступны: {reason}.')
        elif isinstance(data, list) and data and all('expected_delay_s' in r for r in data):
            for row in data:
                display = row.get('display')
                if display:
                    lines.append(f"Поезд {row['train_id']}: ожидаемое опоздание на следующем перегоне — {display['expected_delay_min']} мин. Оценка риска прокси-события — {display['proxy_probability_percent']}%.")
                else:
                    lines.append(f"Поезд {row['train_id']}: ожидаемое опоздание {row['expected_delay_s']} с; вероятность прокси-события {row['p_conflict_15m']}.")
                lines.append('Это эвристическая оценка по правилам, а не ML.' if row.get('degraded') else
                             'Это прогноз модели; он не подтверждает конфликт и не определяет причину задержки.')
                if row.get('top_features'):
                    lines.append('На оценку повлияли: ' + ', '.join(x['name'].lower() for x in row['top_features']) + '.')
        elif isinstance(data, list) and data and all('scheduled_segment_travel_min' in r for r in data):
            for row in data:
                lines.append(f"Поезд {row['train_id']}: учебная модель KZ оценивает время всего перегона {row['segment_id']} в {row['scheduled_segment_travel_min']} мин. Это синтетическое расписание, без учёта инцидентов; не прогноз фактической задержки и не подтверждённая точность для ҚТЖ.")
        elif isinstance(data, dict) and 'variants' in data:
            for v in data['variants']:
                lines.append(f"Вариант {v['label']} ({v['profile']}): суммарная задержка {v['plan']['metrics']['total_delay_s']} с, индекс {v['index']['score']}.")
            lines.append('Это пример ответа песочницы, не применение закрытия и не новый расчёт солвера.')
        elif isinstance(data, dict) and 'score' in data:
            lines.append(f"Индекс: {data['score']}; категория: {data['category']}.")
        elif isinstance(data, dict) and 'train_id' in data and 'delay_s' in data:
            lines.append(f"Поезд {data['train_id']}: задержка {data['delay_s']} с; перегон {data['position']['block_id']}. Причина задержки в состоянии не указана.")
        else:
            # Exact serialization preserves evidence, without inventing domain interpretations.
            lines.append(json.dumps(data, ensure_ascii=False, separators=(',', ':')))
    lines.append('Данные консультативные. Не заменяет СЦБ.')
    return '\n'.join(lines)


async def stream_chat(request, tools, *, use_llm=True, responder=respond):
    question = request.messages[-1].content
    if blocked(question):
        yield 'token', {'text': REFUSAL}
        yield 'done', {'mode': 'refusal', 'grounded': True}
        return
    evidence = []
    items = [m.model_dump() for m in request.messages]
    text, mode = '', 'llm'
    try:
        if not use_llm: raise ProviderUnavailable('offline')
        async with asyncio.timeout(90):
            for iteration in range(6):
                result = await responder(items, tools=iteration < 5)
                items.extend(result.get('output', []))
                calls = [i for i in result.get('output', []) if i.get('type') == 'function_call']
                if not calls:
                    text = output_text(result)
                    break
                if iteration == 5 or len(calls) > 8: raise ProviderUnavailable('tool_limit')
                for call in calls:
                    args = json.loads(call['arguments'])
                    yield 'tool_call', {'name': call['name'], 'arguments': args}
                    data = await tools.call(call['name'], args)
                    evidence.append(data)
                    yield 'tool_result', {'name': call['name'], 'result': data}
                    items.append({'type': 'function_call_output', 'call_id': call['call_id'], 'output': json.dumps(data, ensure_ascii=False)})
            if not text: raise ProviderUnavailable('empty_response')
            bad = unsupported_numbers(text, evidence)
            if bad or not evidence:
                items.append({'role': 'user', 'content': 'Переформулируй ответ только по результатам инструментов. Не добавляй чисел. Если данных нет, прямо скажи об этом.'})
                result = await responder(items, tools=False)
                text = output_text(result)
                if not text or unsupported_numbers(text, evidence) or not evidence:
                    text, mode = template(evidence), 'grounding_fallback'
    except (ProviderUnavailable, TimeoutError, ValueError, KeyError) as exc:
        code = str(exc) if isinstance(exc, ProviderUnavailable) else 'llm_invalid_or_timeout'
        yield 'error', {'code': code, 'recoverable': True}
        mode = 'template'
        if not evidence:
            for name, args in fallback_calls(question):
                yield 'tool_call', {'name': name, 'arguments': args}
                data = await tools.call(name, args)
                evidence.append(data)
                yield 'tool_result', {'name': name, 'result': data}
        text = template(evidence)
    # Render scenario metrics directly: numeric membership alone cannot distinguish
    # total delay from added delay or establish a FIFO comparison.
    variants = [e for e in evidence if isinstance(e.get('data'), dict) and 'variants' in e['data']]
    forecasts = [e for e in evidence if isinstance(e.get('data'), list) and e['data']
                 and all(isinstance(row, dict) and ('expected_delay_s' in row or 'scheduled_segment_travel_min' in row or 'reliable' in row) for row in e['data'])]
    if variants:
        text, mode = template(variants), 'tool_summary'
    elif forecasts:
        # Numeric grounding alone cannot stop SHAP classifier effects being described
        # as causes of delay, or proxy risk being relabelled as conflict probability.
        text, mode = template(evidence), 'tool_summary'
    elif evidence and any(e.get('source') == 'fixture' for e in evidence) and mode == 'llm':
        text = 'Демонстрационные данные из фикстур; не живое состояние.\n\n' + text
    # Buffer model output until grounding completes; then deliver checked text over SSE.
    for pos in range(0, len(text), 100):
        yield 'token', {'text': text[pos:pos + 100]}
    yield 'done', {'mode': mode, 'grounded': not unsupported_numbers(text, evidence)}
