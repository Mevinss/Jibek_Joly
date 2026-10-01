from collections import deque
from contextlib import asynccontextmanager
import json
import time
import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool
from .settings import settings
from .api.schemas import State, Forecast, ChatRequest, TelegramRequest, ReportRequest
from .ml.infer import Forecaster
from .agent.tools import Tools
from .agent.chat import stream_chat
from .texts.generate import telegram_template, report_template, polish

latencies = deque(maxlen=2000)
requests = deque()


@asynccontextmanager
async def lifespan(app):
    app.state.forecaster = Forecaster()
    app.state.tools = Tools(app.state.forecaster)
    yield


app = FastAPI(title='Автодиспетчер — ML/LLM', version='0.1.0', lifespan=lifespan,
              description='Демонстрационная консультативная система. Не заменяет СЦБ.')
app.add_middleware(CORSMiddleware, allow_origins=['http://localhost:5173', 'http://127.0.0.1:5173'],
                   allow_methods=['GET', 'POST'], allow_headers=['Content-Type'])


def rate_limit():
    now = time.monotonic()
    while requests and requests[0] <= now - 60: requests.popleft()
    if len(requests) >= settings.requests_per_minute:
        raise HTTPException(429, 'Request budget exceeded', headers={'Retry-After': '60'})
    requests.append(now)


@app.get('/health')
def health():
    return {'status': 'ok', 'model_version': app.state.forecaster.info['model_version'],
            'tools_mode': 'fixture' if settings.use_fixtures else 'api',
            'llm_configured': bool(settings.llm_api_key.get_secret_value()), 'advisory_only': True}


@app.post('/forecast', response_model=list[Forecast])
def forecast(state: State):
    start = time.perf_counter()
    result = app.state.forecaster.forecast(state)
    latencies.append((time.perf_counter() - start) * 1000)
    return result


@app.get('/forecast/model-info')
def model_info():
    return app.state.forecaster.info


@app.get('/metrics')
def metrics():
    return {'forecast_calls_retained': len(latencies),
            'forecast_compute_p95_ms': float(np.percentile(latencies, 95)) if latencies else None}


@app.post('/chat')
async def chat(request: ChatRequest):
    rate_limit()
    async def events():
        async for event, payload in stream_chat(request, app.state.tools):
            yield f'event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n'
    return StreamingResponse(events(), media_type='text/event-stream',
                             headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


@app.post('/telegram')
async def telegram(request: TelegramRequest):
    rate_limit()
    text = telegram_template(request.incident)
    # Preserve exact telegram structure and avoid unsupported operational recommendations.
    return {'text': text, 'mode': 'template'}


@app.post('/report')
async def report(request: ReportRequest):
    rate_limit()
    return {'markdown': report_template(request.analytics), 'mode': 'template'}


if __name__ == '__main__':
    import uvicorn
    import logging
    logging.basicConfig(level=logging.INFO)
    uvicorn.run('services.ai.main:app', host='127.0.0.1', port=settings.ai_port)
