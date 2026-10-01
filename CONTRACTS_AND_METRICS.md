# Simulator contract and handoff

This contract was derived from the supplied task because the referenced original document was absent from this repository.

## ScenarioSnapshot v1

`GET /api/state` and a WebSocket `SNAPSHOT` payload contain:

```text
scenario_id, seed, virtual_time (ISO 8601 with offset), version,
trains[] {train_id, route[] ordered block IDs, block_id|null, block_index,
          progress [0..1], delay_min, status, planned_start,
          block_seconds[], entry_signals[], entry_switches[], required_tracks[]},
blocks[] {block_id, occupied_by|null, closed},
signals[] {signal_id, aspect: STOP|CLEAR},
switches[] {switch_id, position, failed},
active_incidents[] {incident_id, type, at, duration_min, target ID},
source_type: SIMULATED_DEMO
```

The message envelope has `schema_version=1`, `scenario_id`, `run_id`, monotonically increasing `sequence`, stable `event_id`, `virtual_time`, `server_sent_at`, `type`, `payload`, and `stale_after_ms=3500`. A reset starts a new `run_id`; sequence remains increasing per scenario across runs. The client must discard an older sequence and clear local state when `run_id` changes. `last_sequence` replay is bounded at 100 events, after which a full snapshot is sent.

## Resource graph and movement interface

`Simulator(data_root)` reads only `data/kz_demo/{KZ,mock,scenarios}`. `reset(scenario_id)` returns the same snapshot for the same scenario seed. `advance(seconds)` mutates only the virtual clock and returns the new snapshot. `can_enter(train, block_index)` is the authoritative entry constraint used by FIFO and intended for optimizer integration. A train can enter if the block is open and unoccupied, its entry signal is working, a failed destination switch is already in its required position, and no opposite-direction train occupies that segment. A closure does not remove a train already inside; it denies new entries. Route order and progress remain monotonic.

Incident constraints: `TRAIN_DELAY` shifts a scheduled departure or holds an active train; `SIGNAL_FAILURE` forces the named signal to STOP; `SWITCH_FAILURE` locks the named switch at its current position; `BLOCK_CLOSURE` denies entry to the named block. All four have onset and resolution events. Future events are applied only when virtual time reaches their timestamp; no historical realized delay is injected into planning.

## History and metrics

SQLite tables: `scenarios`, append-only `events`, periodic `snapshots`, and `human_actions`. Uniqueness is `(scenario_id, sequence)`. `STATE` events carry full state for exact replay between periodic snapshots; replay reads stored state and never advances the live simulator. Human actions record `actor/action/accepted/reason/snapshot_version` and reject stale versions. The database uses WAL; writes are moved off the asyncio event loop.

`/metrics` reports `events_received`, `events_rejected`, `ws_clients`, and p50/p95 samples for `ws_emit_lag_ms`, `simulator_step_ms`, and `SQLite_write_ms`. These are backend measurements. Browser render p95 must be measured in the browser, not inferred from these values.

`SCN-ALL` is the deterministic handoff fixture. `SCN-CHAOS` uses the separate `data/fixtures/chaos_spec.json` seed and yields 40 distinct timed incidents. External PKP and DISPLIB data remain outside this graph. The demo has no CP-SAT or optimizer implementation in this module.
