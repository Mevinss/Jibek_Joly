# Canonical state v2 — Person 1 handoff

This contract describes a **synthetic advisory demo**, not operational railway
telemetry or train control. The authoritative v2 field definitions and projection
are in `backend.simulator.state_contract`. `ScenarioSnapshot` v1 in
`backend.simulator.engine` remains the persisted movement format.

## Endpoints and imports

| Endpoint | Source | Purpose |
| --- | --- | --- |
| `GET :8000/api/state` | backend simulator | Unchanged v1 response. |
| `GET :8000/api/v2/state` | backend simulator | Canonical v2 projection with current `run_id`. |
| `GET :8000/api/v2/replay?scenario_id=...&at=...` | SQLite replay | Canonical read-only projection of a stored v1 snapshot. |
| `GET :8000/api/topology` | checked-in fixture CSV | Stable topology IDs; geometry unavailable. |
| `GET :8002/api/v2/state?elapsed=...&incident=...&incident_at=...&seed=...` | existing timetable playback | Canonical v2 projection; stateless advisory view. |
| `GET :8002/api/topology` | fixture CSV + local corridor geometry | Stable IDs and approximate reference geometry. |

`/demo/stream`, `/demo/snapshot`, `/infra/geometry`, `/dispatch/analysis`,
`/dispatch/decision`, `/api/state`, `/ws/state`, history and legacy replay
remain available with their original response shapes.

Public Python functions:

```python
from backend.simulator.state_contract import (
    CanonicalScenarioSnapshot, canonical_from_backend_snapshot, topology,
)
from services.ai.demo.state_adapter import (
    canonical_from_demo_snapshot, planner_snapshot_from_canonical,
    ai_state_from_canonical,
)
```

The v2 `schema_version` is `"2.0"`. The `dataset_version` is a SHA-256 prefix
over the eight checked-in infrastructure/service CSV files. It identifies a
fixture revision, not an operational data release.

## CanonicalScenarioSnapshot

Required top-level keys: `schema_version`, `scenario_id`, `seed`, `run_id`,
`dataset_version`, `virtual_time`, `snapshot_version`, `source_type`, `trains`,
`blocks`, `station_tracks`, `signals`, `switches`, `active_incidents`.
`virtual_time` is an ISO 8601 timestamp with timezone offset. `run_id` is the
SQLite run UUID for the backend service. Demo playback is stateless, so its
`run_id` is `null`. `source_type=SIMULATED_DEMO` never means live KTZ input.

### TrainState

Stable `train_id`; optional `train_number`, `category`, `direction`, `route_id`,
`origin_station_id`, `destination_station_id`; ordered block-ID `route`;
`current_segment_id` and `current_block_id` (nullable while scheduled/completed);
`route_progress_0_1`, `block_progress_0_1`; optional `speed_kmh`;
`delay_min`; nullable `next_station_id`, `scheduled_arrival`,
`estimated_arrival`; `data_mode`, `source_type`, `updated_at`.
Existing simulator fields (`block_index`, `block_seconds`, `entry_signals`,
`entry_switches`, `required_tracks`, etc.) are carried through for planner
compatibility. Unknown measurements are `null`, never estimated implicitly.
Demo `estimated_arrival` is derived from the playback's displayed ETA and
marked `estimated_arrival_source=DERIVED`; it is not an observed arrival.

**Progress semantics:**

- `route_progress_0_1`: fraction of the *entire ordered route* completed.
- `block_progress_0_1`: fraction of the *current block* completed. It is `0`
  before departure and `1` at completed status.
- `progress`: deprecated v1 compatibility alias for **route progress in a
  canonical response and in backend simulator v1**. It must not be used for
  occupied-block release time.
- The existing CP-SAT v1 interface interprets its input `progress` as **block
  progress**. `planner_snapshot_from_canonical()` intentionally maps the
  explicit `block_progress_0_1` to that legacy input until Person 2 updates
  the planner to read the explicit field. The existing demo `platform_snapshot`
  also keeps this planner-v1 behavior, with both explicit fields alongside it.

Example: route length 10, current block index 2, 75% through that block gives
`route_progress_0_1=0.275` and `block_progress_0_1=0.75`. A 100-second block
has 25 seconds remaining, not 72.5 seconds.

### BlockState

Stable `block_id`, `segment_id`, `capacity`, `occupied_train_ids`, `closed`,
nullable `direction_lock`, `speed_limit_kmh`, `entry_signal_id`, and
`state_conflict`. `state_conflict` is exactly
`len(occupied_train_ids) > capacity`. All occupants are retained even when the
demo timetable places multiple trains in a capacity-one block. `occupied_by`
is a **deprecated first-occupant compatibility field**. Consumers must not use
it to prove conflict freedom. The strict planner projection rejects such a
snapshot because planner v1 cannot represent all occupants. `direction_lock`
is `null` when no runtime lock state exists; `direction_lock_rule` separately
reports the fixture's static `one_direction_at_a_time` policy.

### StationTrackState

Stable `station_id`, `track_id`, fixture `capacity`, `occupied_train_ids`,
nullable `available`, and `occupancy_source`. The current simulator does not
maintain individual station-track occupancy: `occupied_train_ids=[]`,
`available=null`, `occupancy_source=UNAVAILABLE`. The empty list is **not** a
claim that a track is free. Person 2 must not approve a track decision from it.

### SignalState and SwitchState

Signal: `signal_id`, `block_id`, nullable `aspect`, nullable `failed`, nullable
`updated_at`. Backend signals come from the simulator; failed state follows
active `SIGNAL_FAILURE`. Demo playback has no live signal observations, so
its signal aspect/failure fields are `null` with `state_source=UNAVAILABLE`.

Switch: `switch_id`, nullable `position`, `locked`, `failed`, and
`available_routes` (fixture controlled track IDs). Backend switch state comes
from the simulator. Demo playback has no live switch observations; its state
fields are `null` with `state_source=UNAVAILABLE`.

### Incidents and provenance

Backend `active_incidents` carries incident IDs, type, time, duration and
target as supplied by the simulator. Demo closure maps to `BLOCK_CLOSURE`;
restriction and chaos receive explicitly synthetic marker incidents without
invented infrastructure targets. `source_type=SIMULATED_DEMO` labels movement
state. Topology on port 8002 uses `geometry_source=EXTERNAL_REFERENCE_APPROXIMATE`;
its coordinates are map references, not a certified technical scheme.

## Versions, WebSocket and replay

Backend `snapshot_version` aliases v1 `version`. The simulator increments it
once per movement step, including incident transitions. Reset starts a new
run at version 0, identified by a new `run_id`; compare both run and version
when checking a stale action. The stateless demo endpoint derives its version
from playback elapsed time; it is **not an authoritative concurrency token**.
The existing `/dispatch/decision` is advisory and never applies an action.

`/ws/state` keeps envelope `schema_version=1` and v1 `payload` for existing
clients. It now also carries `snapshot_version` at envelope level. Existing
`scenario_id`, `run_id`, monotonic per-scenario `sequence`, deduplication
`event_id`, `virtual_time`, `server_sent_at`, `type`, and `stale_after_ms=3500`
remain. On reconnect, use `last_sequence`; discard older/duplicate sequences,
and replace local state when `run_id` changes. A gap beyond the bounded replay
returns a full snapshot. New clients may fetch `/api/v2/state` after reconnect.

SQLite continues storing v1 engine snapshots. The canonical projection is
deterministically reconstructed from a replayed v1 snapshot and the same
versioned fixture tables; replay does not mutate the live simulator. Previously
stored v1 rows remain readable; no table migration is required. A fixture
revision changes `dataset_version`, so historical reconstruction should use
the matching fixture revision for exact metadata.

## Example (abbreviated)

```json
{
  "schema_version": "2.0",
  "scenario_id": "KZ-DEMO-ADVISORY",
  "seed": 42,
  "run_id": null,
  "dataset_version": "sha256:<fixture-hash-prefix>",
  "virtual_time": "2026-10-01T11:05:00+05:00",
  "snapshot_version": 300000,
  "source_type": "SIMULATED_DEMO",
  "trains": [{
    "train_id": "SIM-KOK_AST-F01", "current_block_id": "KOK-BOR-B01",
    "route_progress_0_1": 0.0275, "block_progress_0_1": 0.275,
    "progress": 0.0275, "speed_kmh": 60.0, "delay_min": 0.0
  }],
  "blocks": [{
    "block_id": "KOK-BOR-B01", "capacity": 1,
    "occupied_train_ids": ["SIM-KOK_AST-F01", "SIM-KOK_AST-F02"],
    "occupied_by": "SIM-KOK_AST-F01", "closed": false,
    "state_conflict": true
  }],
  "station_tracks": [{
    "station_id": "KOK", "track_id": "KOK-T1", "capacity": 1,
    "occupied_train_ids": [], "available": null,
    "occupancy_source": "UNAVAILABLE"
  }],
  "signals": [], "switches": [], "active_incidents": []
}
```

Values in this example illustrate field semantics; request an endpoint for an
actual fixture snapshot.

## Team handoff

### Person 2 — Planner

Import `CanonicalScenarioSnapshot` from `backend.simulator.state_contract`.
For current-block release use `block_progress_0_1`, not canonical `progress`.
For route completion use `route_progress_0_1`. Read the full
`occupied_train_ids`, `capacity`, and `state_conflict`; never infer safety from
`occupied_by`. `station_tracks` currently reports unknown occupancy, so track
selection requires an authoritative state source. Read `active_incidents`,
and join resources by stable IDs in `GET /api/topology`. Fixture path:
`data/kz_demo/`. Temporary v1 bridge:
`services.ai.demo.state_adapter.planner_snapshot_from_canonical`; it rejects
capacity conflicts. Planner code is unchanged in this handoff.

### Person 3 — Analytics

Group runs by `scenario_id`, `seed`, `run_id`, `dataset_version`, and
`source_type`; align events by `virtual_time` and `snapshot_version`.
`delay_min`, `scheduled_arrival`, and demo-only `estimated_arrival` are present
when known. Backend current speed/ETA and station-track occupancy are not
currently measured. No validated energy, kWh, CO2, improvement percentage or
full-run comparison is produced by this contract.

### Person 4 — Frontend

Fetch `GET :8002/api/topology` for stable `station_id`, `segment_id`,
`block_id`, `track_id`, `signal_id`, `switch_id`, and approximate geometry.
Fetch `GET :8002/api/v2/state` for demo canonical state or
`GET :8000/api/v2/state` for simulator canonical state; these are **different
state sources**. Existing `/demo/stream` still drives the current map.
Use `train_id` and resource IDs for joins, not display names. Display
`occupied_train_ids` and `state_conflict`; do not render an unknown station
track as available. Backend `/ws/state` has envelope-level
`snapshot_version`, monotonic `sequence`, stable `event_id`, `run_id`, and
`stale_after_ms`. Reconnect with `last_sequence`; reject stale run/version
when submitting a future validated action. Demo `/dispatch/decision` does not
currently apply actions or enforce an authoritative snapshot version.
