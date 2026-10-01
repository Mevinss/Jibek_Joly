# Unified dashboard API and demo scope

The main application is served at `/` on the AI service port (`8002`). The
previous frontend remains at `/legacy`. The default dashboard scenario is
`SCN-RUNTIME`: one persistent backend Simulator with 28 synthetic trains.
The browser reads canonical State v2 and does not calculate dispatch or ETA.

## Main runtime flow

| UI step | API | Effect |
| --- | --- | --- |
| Initial map, trains and clock | `GET /api/runtime/state`, `/topology`, `/stream` | One `run_id:snapshot_version` identity; SSE updates from the simulator. |
| Play, pause, reset | `POST /api/runtime/control`, `/reset` | ×1, ×10, ×60 virtual time or a new persisted run. |
| Add incident | `POST /api/runtime/incidents` | Validated resource, exact run/version, simulator advances and persists the event. |
| Detect, plan and compare | `GET /api/runtime/analysis`, `/plan` | Affected trains, Person 2 FIFO and CP-SAT status, simulator fork options A/B/C. |
| Preview | `POST /api/runtime/preview` | Independent 10-, 20- or 30-minute fork; baseline, decision, per-train delay and ETA impacts, forecast map; no live mutation. |
| Apply | `POST /api/runtime/apply` | Validated `HOLD_TRAIN` on the current run, persisted and broadcast. Stale versions get 409. |
| Derived views | `/stations/{id}/arrivals`, `/health-index`, `/trains/{id}/speed-profile` | Snapshot-bound Person 3 arrivals; explicit demo health heuristic; limit-only speed profile. |
| History and replay | `/history`, `/replay?at=...` | SQLite events and a read-only past snapshot, inspectable on the map. |

`/api/runtime/analysis` calls FIFO and CP-SAT on the same canonical snapshot.
Their station-track occupancy is not fully verified on this 28-train network,
so those plans are shown as advisory and never applied. Options A/B/C are
separate, bounded `HOLD_TRAIN` actions checked by the canonical human-decision
validator and evaluated on simulator forks. Recommendation selects the lowest
weighted delay among valid options over 20 virtual minutes, with weights 3
(intercity), 2 (regional), and 1 (freight). A can be recommended.

The health score is a transparent snapshot heuristic with capped penalties
for mean delay, waiting trains, incidents and conflicts. It is not Person 3's
observed-run QualityIndex. Speed advice exposes the existing speed-limit
profile, and does not claim a target speed, energy saving, kWh, tenge or CO₂.
Geometry is approximate reference geometry. Everything in `SCN-RUNTIME` is
synthetic demonstration data, not an operational railway feed or train control.

The other LIVE scenarios are separate demos: `SCN-ALL` is a 28-train
timetable playback whose initial state contains conflicts, while `SCN-SHORT`
is a 3-train fully validated evaluation sample. Their results must not be
presented as results from the main stateful 28-train run. `MOCK` uses labelled
frontend fixtures and never silently replaces an unavailable LIVE response.
