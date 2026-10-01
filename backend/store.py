"""Append-only SQLite timeline. Each STATE event is a replayable state delta."""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class EventStore:
    def __init__(self, path: Path = ROOT / "data" / "history.sqlite3"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.path, check_same_thread=False, timeout=10)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS scenarios (
                scenario_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, last_sequence INTEGER NOT NULL,
                running INTEGER NOT NULL, speed INTEGER NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS events (
                scenario_id TEXT NOT NULL, run_id TEXT NOT NULL, sequence INTEGER NOT NULL,
                event_id TEXT NOT NULL UNIQUE, virtual_time TEXT NOT NULL, type TEXT NOT NULL,
                payload TEXT NOT NULL, server_sent_at TEXT NOT NULL,
                PRIMARY KEY (scenario_id, sequence)
            );
            CREATE INDEX IF NOT EXISTS events_time ON events (scenario_id, run_id, virtual_time, sequence);
            CREATE TABLE IF NOT EXISTS snapshots (
                scenario_id TEXT NOT NULL, run_id TEXT NOT NULL, sequence INTEGER NOT NULL,
                virtual_time TEXT NOT NULL, state TEXT NOT NULL,
                PRIMARY KEY (scenario_id, sequence)
            );
            CREATE TABLE IF NOT EXISTS human_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT, scenario_id TEXT NOT NULL, run_id TEXT NOT NULL,
                actor TEXT NOT NULL, action TEXT NOT NULL, accepted INTEGER NOT NULL,
                reason TEXT NOT NULL, snapshot_version INTEGER NOT NULL, at TEXT NOT NULL
            );
        """)
        self.connection.commit()

    def current(self, scenario_id: str) -> dict | None:
        row = self.connection.execute("SELECT * FROM scenarios WHERE scenario_id=?", (scenario_id,)).fetchone()
        return dict(row) if row else None

    def latest_active(self) -> dict | None:
        row = self.connection.execute("SELECT * FROM scenarios ORDER BY updated_at DESC LIMIT 1").fetchone()
        return dict(row) if row else None

    def latest_event(self, scenario_id: str, run_id: str) -> dict | None:
        row = self.connection.execute("SELECT * FROM events WHERE scenario_id=? AND run_id=? ORDER BY sequence DESC LIMIT 1", (scenario_id, run_id)).fetchone()
        if row is None:
            return None
        return {"schema_version": 1, "scenario_id": row["scenario_id"], "run_id": row["run_id"], "sequence": row["sequence"], "event_id": row["event_id"], "virtual_time": row["virtual_time"], "server_sent_at": row["server_sent_at"], "type": row["type"], "payload": json.loads(row["payload"])}

    def latest_state(self, scenario_id: str, run_id: str) -> dict | None:
        row = self.connection.execute("SELECT payload FROM events WHERE scenario_id=? AND run_id=? AND type='STATE' ORDER BY sequence DESC LIMIT 1", (scenario_id, run_id)).fetchone()
        return json.loads(row["payload"])["engine_state"] if row else None

    def start_run(self, scenario_id: str) -> str:
        run_id = str(uuid.uuid4())
        old = self.current(scenario_id)
        next_sequence = old["last_sequence"] if old else 0
        with self.connection:
            self.connection.execute("INSERT INTO scenarios VALUES (?,?,?,?,?,?) ON CONFLICT(scenario_id) DO UPDATE SET run_id=excluded.run_id, running=0, speed=1, updated_at=excluded.updated_at", (scenario_id, run_id, next_sequence, 0, 1, datetime.now().astimezone().isoformat()))
        return run_id

    def update_control(self, scenario_id: str, running: bool, speed: int) -> None:
        with self.connection:
            self.connection.execute("UPDATE scenarios SET running=?, speed=?, updated_at=? WHERE scenario_id=?", (int(running), speed, datetime.now().astimezone().isoformat(), scenario_id))

    def append(self, scenario_id: str, run_id: str, entries: list[dict], engine_state: dict, snapshot_interval_seconds: int = 300) -> tuple[list[dict], float]:
        started = time.perf_counter()
        row = self.current(scenario_id)
        sequence = row["last_sequence"] if row else 0
        now = datetime.now().astimezone().isoformat(timespec="milliseconds")
        out = []
        with self.connection:
            for entry in entries + [{"type": "STATE", "virtual_time": engine_state["snapshot"]["virtual_time"], "engine_state": engine_state}]:
                # The containing movement step has one snapshot_version. Keep
                # it with incident events so reconnect can replay their exact
                # version without consulting the current live simulator.
                if entry["type"] != "STATE":
                    entry = {**entry, "snapshot_version": engine_state["snapshot"]["version"]}
                sequence += 1
                event_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{scenario_id}/{sequence}"))
                envelope = {"schema_version": 1, "scenario_id": scenario_id, "run_id": run_id, "sequence": sequence, "event_id": event_id, "virtual_time": entry["virtual_time"], "server_sent_at": now, "type": entry["type"], "payload": entry}
                self.connection.execute("INSERT INTO events VALUES (?,?,?,?,?,?,?,?)", (scenario_id, run_id, sequence, event_id, entry["virtual_time"], entry["type"], json.dumps(entry, ensure_ascii=False), now))
                out.append(envelope)
            self.connection.execute("UPDATE scenarios SET last_sequence=?, updated_at=? WHERE scenario_id=?", (sequence, now, scenario_id))
            virtual_time = datetime.fromisoformat(engine_state["snapshot"]["virtual_time"])
            previous = self.connection.execute("SELECT virtual_time FROM snapshots WHERE scenario_id=? AND run_id=? ORDER BY sequence DESC LIMIT 1", (scenario_id, run_id)).fetchone()
            if previous is None or (virtual_time - datetime.fromisoformat(previous["virtual_time"])).total_seconds() >= snapshot_interval_seconds:
                self.connection.execute("INSERT INTO snapshots VALUES (?,?,?,?,?)", (scenario_id, run_id, sequence, engine_state["snapshot"]["virtual_time"], json.dumps(engine_state, ensure_ascii=False)))
        return out, (time.perf_counter() - started) * 1000

    def history(self, scenario_id: str, from_time: str, to_time: str, run_id: str | None = None) -> list[dict]:
        current = self.current(scenario_id)
        run_id = run_id or (current["run_id"] if current else "")
        rows = self.connection.execute("SELECT * FROM events WHERE scenario_id=? AND run_id=? AND virtual_time>=? AND virtual_time<=? ORDER BY sequence", (scenario_id, run_id, from_time, to_time)).fetchall()
        return [{"schema_version": 1, "scenario_id": row["scenario_id"], "run_id": row["run_id"], "sequence": row["sequence"], "event_id": row["event_id"], "virtual_time": row["virtual_time"], "server_sent_at": row["server_sent_at"], "type": row["type"], "payload": json.loads(row["payload"])} for row in rows]

    def since(self, scenario_id: str, run_id: str, last_sequence: int, limit: int = 100) -> list[dict] | None:
        rows = self.connection.execute("SELECT * FROM events WHERE scenario_id=? AND run_id=? AND sequence>? ORDER BY sequence LIMIT ?", (scenario_id, run_id, last_sequence, limit + 1)).fetchall()
        if len(rows) > limit:
            return None
        return [{"schema_version": 1, "scenario_id": row["scenario_id"], "run_id": row["run_id"], "sequence": row["sequence"], "event_id": row["event_id"], "virtual_time": row["virtual_time"], "server_sent_at": row["server_sent_at"], "type": row["type"], "payload": json.loads(row["payload"])} for row in rows]

    def replay(self, scenario_id: str, at: str, run_id: str | None = None) -> dict | None:
        current = self.current(scenario_id)
        run_id = run_id or (current["run_id"] if current else "")
        row = self.connection.execute("SELECT payload FROM events WHERE scenario_id=? AND run_id=? AND type='STATE' AND virtual_time<=? ORDER BY virtual_time DESC, sequence DESC LIMIT 1", (scenario_id, run_id, at)).fetchone()
        return json.loads(row["payload"])["engine_state"]["snapshot"] if row else None

    def log_human_action(self, scenario_id: str, run_id: str, actor: str, action: str, accepted: bool, reason: str, snapshot_version: int) -> None:
        with self.connection:
            self.connection.execute("INSERT INTO human_actions (scenario_id,run_id,actor,action,accepted,reason,snapshot_version,at) VALUES (?,?,?,?,?,?,?,?)", (scenario_id, run_id, actor, action, int(accepted), reason, snapshot_version, datetime.now().astimezone().isoformat()))
