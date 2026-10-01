from collections import deque
from contextlib import asynccontextmanager
import json
import time
import asyncio
from typing import Literal
import numpy as np
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from .settings import settings, SERVICE
from .api.schemas import State, Forecast, ChatRequest, TelegramRequest, ReportRequest
from .ml.infer import Forecaster
from .agent.tools import Tools
from .agent.chat import stream_chat
from .texts.generate import telegram_template, report_template, polish
from .demo.simulation import geometry, snapshot
from .ml.kz_schedule import ScheduleForecaster

latencies = deque(maxlen=2000)
requests = deque()


@asynccontextmanager
async def lifespan(app):
    app.state.forecaster = Forecaster()
    app.state.tools = Tools(app.state.forecaster)
    try:
        app.state.schedule_forecaster = ScheduleForecaster()
    except (OSError, ValueError):
        app.state.schedule_forecaster = None
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


@app.get('/forecast/schedule-info')
def schedule_info():
    if app.state.schedule_forecaster is None: raise HTTPException(503, 'Schedule model unavailable')
    return app.state.schedule_forecaster.info


@app.post('/forecast/schedule')
def schedule_forecast(state: State):
    if app.state.schedule_forecaster is None: raise HTTPException(503, 'Schedule model unavailable')
    return app.state.schedule_forecaster.forecast(state)


@app.get('/metrics')
def metrics():
    return {'forecast_calls_retained': len(latencies),
            'forecast_compute_p95_ms': float(np.percentile(latencies, 95)) if latencies else None}


@app.post('/chat')
async def chat(request: ChatRequest):
    rate_limit()
    request_tools = Tools(app.state.forecaster, snapshot=request.state) if request.state is not None else app.state.tools
    async def events():
        async for event, payload in stream_chat(request, request_tools):
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


@app.get('/demo/state')
def demo_state():
    return {'source': 'fixture', 'state': app.state.tools.fixture('state')}


@app.get('/infra/geometry')
def infra_geometry():
    return geometry()


@app.get('/demo/snapshot')
def demo_snapshot(elapsed: float = Query(0, ge=0, le=86400, allow_inf_nan=False),
                  incident: Literal['none','closure','restriction','chaos']='none',
                  incident_at: float = Query(0, ge=0, le=86400, allow_inf_nan=False)):
    return snapshot(elapsed, incident, incident_at)


@app.get('/demo/stream')
async def demo_stream(request: Request, elapsed: float = Query(0, ge=0, le=86400, allow_inf_nan=False),
                      speed: Literal['1','10']='1', incident: Literal['none','closure','restriction','chaos']='none',
                      incident_at: float = Query(0, ge=0, le=86400, allow_inf_nan=False)):
    async def events():
        start=time.monotonic()
        while not await request.is_disconnected():
            clock=min(86400.,elapsed+(time.monotonic()-start)*int(speed))
            yield 'event: state\ndata: '+json.dumps(snapshot(clock,incident,incident_at),ensure_ascii=False)+'\n\n'
            await asyncio.sleep(1)
    return StreamingResponse(events(),media_type='text/event-stream',headers={'Cache-Control':'no-cache','X-Accel-Buffering':'no'})


if (SERVICE / 'web').is_dir():
    app.mount('/', StaticFiles(directory=SERVICE / 'web', html=True), name='demo')


if __name__ == '__main__':
    import uvicorn
    import logging
    logging.basicConfig(level=logging.INFO)
    uvicorn.run('services.ai.main:app', host='127.0.0.1', port=settings.ai_port)
