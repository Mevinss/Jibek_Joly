import json
import time
import numpy as np
from fastapi.testclient import TestClient
from ..main import app
from ..settings import SERVICE


def main():
    state = json.loads((SERVICE / 'fixtures/state.json').read_text(encoding='utf-8'))
    elapsed = []
    with TestClient(app) as client:
        for _ in range(10): client.post('/forecast', json=state).raise_for_status()
        for _ in range(100):
            start = time.perf_counter()
            client.post('/forecast', json=state).raise_for_status()
            elapsed.append((time.perf_counter()-start)*1000)
        result = {'trains': len(state['trains']), 'repeats': len(elapsed),
                  'http_testclient_p95_ms': float(np.percentile(elapsed, 95)),
                  'compute_p95_ms': client.get('/metrics').json()['forecast_compute_p95_ms'],
                  'model_version': client.get('/health').json()['model_version'],
                  'method': 'Warm in-process HTTP TestClient including validation/serialization; local machine, not network or production load.'}
    (SERVICE / 'reports/latency.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result))


if __name__ == '__main__': main()
