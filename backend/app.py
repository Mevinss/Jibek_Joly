"""FastAPI control plane and bounded 1 Hz state stream."""
from __future__ import annotations

import asyncio
import os
import statistics
import time
from contextlib import asynccontextmanager, suppress
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from .simulator import Simulator
from .store import EventStore, ROOT


class Metrics:
    def __init__(self):
        self.events_received = 0
        self.events_rejected = 0
        self.ws_clients = 0
        self.samples: dict[str, list[float]] = {key: [] for key in ("ws_emit_lag_ms", "simulator_step_ms", "SQLite_write_ms")}

    def observe(self, key: str, value: float) -> None:
        self.samples[key].append(value)
        self.samples[key] = self.samples[key][-1000:]

    def report(self) -> dict:
        def percentile(values: list[float], p: float) -> float | None:
            if not values:
                return None
            ordered = sorted(values)
            return round(ordered[round((len(ordered) - 1) * p)], 2)
        return {"events_received": self.events_received, "events_rejected": self.events_rejected, "ws_clients": self.ws_clients, **{key: {"p50": percentile(values, .5), "p95": percentile(values, .95)} for key, values in self.samples.items()}}


class Runtime:
    def __init__(self, database: Path | None = None):
        self.store = EventStore(database or Path(os.environ.get("TURKISIB_DB", ROOT / "data/history.sqlite3")))
        recent = self.store.latest_active()
        self.simulator = Simulator(recent["scenario_id"] if recent else "SCN-ALL")
        self.metrics = Metrics()
        self.lock = asyncio.Lock()
        self.clients: set[WebSocket] = set()
        self.running = False
        self.speed = 1
        current = self.store.current(self.simulator.scenario_id)
        if current:
            state = self.store.latest_state(self.simulator.scenario_id, current["run_id"])
            if state:
                self.simulator.restore_state(state)
                self.run_id = current["run_id"]
                self.running = bool(current["running"])
                self.speed = current["speed"]
            else:
                self.run_id = self.store.start_run(self.simulator.scenario_id)
                self.store.append(self.simulator.scenario_id, self.run_id, [], self.simulator.export_state())
        else:
            self.run_id = self.store.start_run(self.simulator.scenario_id)
            self.store.append(self.simulator.scenario_id, self.run_id, [], self.simulator.export_state())

    def envelope(self, kind: str, payload: dict) -> dict:
        sequence = self.store.current(self.simulator.scenario_id)["last_sequence"]
        return {"schema_version": 1, "scenario_id": self.simulator.scenario_id, "run_id": self.run_id, "sequence": sequence, "event_id": f"{self.run_id}:{sequence}:{kind}", "virtual_time": self.simulator.snapshot().virtual_time, "server_sent_at": datetime.now().astimezone().isoformat(timespec="milliseconds"), "type": kind, "payload": payload, "stale_after_ms": 3500}

    def public_event(self, event: dict) -> dict:
        message = dict(event)
        if message["type"] == "STATE":
            message["type"] = "SNAPSHOT"
            message["payload"] = message["payload"]["engine_state"]["snapshot"]
        message["stale_after_ms"] = 3500
        return message

    async def broadcast(self, message: dict) -> None:
        sent = datetime.now().timestamp()
        for client in list(self.clients):
            try:
                await asyncio.wait_for(client.send_json(message), timeout=.3)
                self.metrics.observe("ws_emit_lag_ms", (datetime.now().timestamp() - sent) * 1000)
            except Exception:
                self.clients.discard(client)
                with suppress(Exception):
                    await client.close()
        self.metrics.ws_clients = len(self.clients)

    async def loop(self) -> None:
        while True:
            await asyncio.sleep(1)
            async with self.lock:
                if self.running:
                    started = time.perf_counter()
                    self.simulator.advance(self.speed)
                    self.metrics.observe("simulator_step_ms", (time.perf_counter() - started) * 1000)
                    entries, elapsed = await asyncio.to_thread(self.store.append, self.simulator.scenario_id, self.run_id, self.simulator.events, self.simulator.export_state())
                    self.metrics.observe("SQLite_write_ms", elapsed)
                    self.metrics.events_received += len(entries)
                    message = self.public_event(entries[-1])
                else:
                    message = self.envelope("HEARTBEAT", {"running": False})
            await self.broadcast(message)


runtime: Runtime | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global runtime
    runtime = Runtime()
    task = asyncio.create_task(runtime.loop())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        runtime.store.connection.close()


app = FastAPI(title="TurkiSib simulator", lifespan=lifespan)


def active() -> Runtime:
    if runtime is None:
        raise HTTPException(503, "runtime not started")
    return runtime


@app.get("/health")
def health() -> dict:
    rt = active()
    return {"status": "ok", "scenario_id": rt.simulator.scenario_id, "virtual_time": rt.simulator.snapshot().virtual_time, "running": rt.running}


@app.get("/metrics")
def metrics() -> dict:
    return active().metrics.report()


@app.get("/api/state")
def state() -> dict:
    return active().simulator.snapshot().to_dict()


@app.post("/api/scenarios/{scenario_id}/reset")
async def reset(scenario_id: str) -> dict:
    rt = active()
    async with rt.lock:
        try:
            snapshot = rt.simulator.reset(scenario_id)
        except KeyError:
            raise HTTPException(404, "unknown scenario") from None
        rt.run_id = rt.store.start_run(scenario_id)
        rt.running = False
        rt.speed = 1
        entries, _ = await asyncio.to_thread(rt.store.append, scenario_id, rt.run_id, [], rt.simulator.export_state())
        message = rt.public_event(entries[-1])
    await rt.broadcast(message)
    return snapshot.to_dict()


@app.post("/api/scenarios/{scenario_id}/start")
async def start(scenario_id: str, speed: int = Query(1)) -> dict:
    rt = active()
    if scenario_id != rt.simulator.scenario_id:
        raise HTTPException(409, "reset requested scenario first")
    if speed not in (1, 10, 60):
        raise HTTPException(422, "speed must be 1, 10 or 60")
    async with rt.lock:
        rt.speed = speed
        rt.running = True
        rt.store.update_control(scenario_id, True, speed)
    return {"scenario_id": scenario_id, "running": True, "speed": speed}


@app.post("/api/scenarios/{scenario_id}/pause")
async def pause(scenario_id: str) -> dict:
    rt = active()
    if scenario_id != rt.simulator.scenario_id:
        raise HTTPException(404, "inactive scenario")
    async with rt.lock:
        rt.running = False
        rt.store.update_control(scenario_id, False, rt.speed)
    return {"running": False, "virtual_time": rt.simulator.snapshot().virtual_time}


@app.get("/api/history")
def history(scenario_id: str, from_time: str = Query(alias="from"), to_time: str = Query(alias="to"), run_id: str | None = None) -> dict:
    rt = active()
    try:
        start = datetime.fromisoformat(from_time)
        end = datetime.fromisoformat(to_time)
        if start > end or (end - start).total_seconds() > 86400:
            raise ValueError("invalid range")
    except ValueError:
        raise HTTPException(422, "invalid history range") from None
    return {"events": rt.store.history(scenario_id, from_time, to_time, run_id)}


@app.get("/api/replay")
def replay(scenario_id: str, at: str, run_id: str | None = None) -> dict:
    try:
        datetime.fromisoformat(at)
    except ValueError:
        raise HTTPException(422, "invalid at") from None
    snapshot = active().store.replay(scenario_id, at, run_id)
    if snapshot is None:
        raise HTTPException(404, "no state at requested time")
    return snapshot


class HumanAction(BaseModel):
    actor: str
    action: str
    accepted: bool
    reason: str = ""
    snapshot_version: int


@app.post("/api/human-actions")
async def human_action(action: HumanAction) -> dict:
    rt = active()
    async with rt.lock:
        current_version = rt.simulator.version
        accepted = action.accepted and action.snapshot_version == current_version
        reason = action.reason if accepted else ("stale snapshot version" if action.snapshot_version != current_version else action.reason)
        rt.store.log_human_action(rt.simulator.scenario_id, rt.run_id, action.actor, action.action, accepted, reason, action.snapshot_version)
        if not accepted:
            rt.metrics.events_rejected += 1
        return {"accepted": accepted, "reason": reason, "snapshot_version": current_version}


@app.websocket("/ws/state")
async def websocket_state(websocket: WebSocket, last_sequence: int | None = None):
    rt = active()
    await websocket.accept()
    async with rt.lock:
        current = rt.store.current(rt.simulator.scenario_id)
        missed = rt.store.since(rt.simulator.scenario_id, rt.run_id, last_sequence) if last_sequence is not None else None
        if missed is None or not missed or last_sequence > current["last_sequence"]:
            latest = rt.store.latest_event(rt.simulator.scenario_id, rt.run_id)
            initial = [rt.public_event(latest)] if latest else [rt.envelope("SNAPSHOT", rt.simulator.snapshot().to_dict())]
        else:
            initial = [rt.public_event(event) for event in missed]
        for message in initial:
            await websocket.send_json(message)
        rt.clients.add(websocket)
        rt.metrics.ws_clients = len(rt.clients)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        rt.clients.discard(websocket)
        rt.metrics.ws_clients = len(rt.clients)
