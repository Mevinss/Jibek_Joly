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
    train = re.search(r'(?<!\d)(\d{3,6})(?!\d)', q)
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
    lines = ['Консультативная сводка. ' + ('Используются демонстрационные фикстуры.' if any(e.get('source') == 'fixture' for e in evidence) else 'Данные получены через API.')]
    for result in evidence:
        data = result.get('data', {})
        if result.get('error') or isinstance(data, dict) and data.get('error'):
            lines.append('Запрошенные сведения недоступны; результат не рассчитан.')
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
    # Buffer model output until grounding completes; then deliver checked text over SSE.
    for pos in range(0, len(text), 100):
        yield 'token', {'text': text[pos:pos + 100]}
    yield 'done', {'mode': mode, 'grounded': not unsupported_numbers(text, evidence)}
