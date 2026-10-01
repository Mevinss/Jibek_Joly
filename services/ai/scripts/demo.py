"""End-to-end CLI demo against the running AI HTTP service."""
import json
import httpx
from ..settings import SERVICE, settings


def main():
    base = f'http://127.0.0.1:{settings.ai_port}'
    state = json.loads((SERVICE / 'fixtures/state.json').read_text(encoding='utf-8'))
    with httpx.Client(timeout=120) as client:
        health = client.get(base + '/health'); health.raise_for_status()
        print('HEALTH', health.json())
        r = client.post(base + '/forecast', json=state); r.raise_for_status()
        print('FORECAST', json.dumps(r.json()[:3], ensure_ascii=False, indent=2))
        request = {'session_id': 'demo', 'messages': [{'role': 'user', 'content': 'Что будет, если закрыть перегон Б–В на 20 минут?'}]}
        print('\nCHAT — подготовленные фикстуры, не live-оптимизация')
        with client.stream('POST', base + '/chat', json=request) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if line.startswith('data:'):
                    data = json.loads(line[5:])
                    print(data.get('text', json.dumps(data, ensure_ascii=False)), flush=True)


if __name__ == '__main__': main()
