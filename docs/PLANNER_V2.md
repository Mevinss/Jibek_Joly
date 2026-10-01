# Person 2: canonical dispatch planning and speed advice

This is a synthetic advisory demonstration. A valid plan satisfies the documented
model constraints, not certified railway safety requirements. No function here
changes the simulator, map playback, ML, LLM, or live state.

## Ownership and entry points

Person 1's authoritative input is
`backend.simulator.state_contract.CanonicalScenarioSnapshot`, schema `2.0`.
The contract arrived in repository history at `69140fe`. Its files and adapter
are unchanged. No shared FastAPI routes have been modified or added.

```python
from backend.planner import (
    DispatchRequest, PlanningConfig, build_dispatch_plan,
    build_fifo_plan, build_cp_sat_plan,
)
from backend.validator.resources import validate_plan, validate_human_decision
from backend.planner.apply import prepare_fork_schedule
from backend.speed_profile.advisory import build_speed_advice

config = PlanningConfig(horizon_seconds=3600, time_limit_seconds=5,
                        headway_seconds=0, category_weights={"passenger": 2})
fifo = build_fifo_plan(canonical_snapshot, config=config)
optimized = build_cp_sat_plan(canonical_snapshot, config=config)
payload = optimized.to_dict()
# Revalidates the same snapshot; raises if any scope is unverified.
fork_commands = prepare_fork_schedule(canonical_snapshot, optimized)
```

Both policies return the same dataclass `DispatchPlan` from `models.py`.
`.to_dict()` produces ordinary JSON data. Errors in the top-level contract or
configuration raise `ValueError`; inconsistent model inputs produce
`INVALID_INPUT`, structured violations, and no active reservations.

## Canonical input and deterministic enrichment

- Current-block release uses `block_progress_0_1`. It never interprets deprecated
  `progress` or `route_progress_0_1` as a block fraction.
- Legacy APIs prefer the explicit field, then `block_elapsed/block_seconds`.
  With neither available they conservatively reserve the full block duration.
- Read **all** `occupied_train_ids`. Reject initial `state_conflict`, occupancy
  over capacity, missing occupants, or inconsistent train/block references.
  Capacity greater than one is supported without dropping occupants.
- The existing carried-through fields `route`, `block_index`, `block_seconds`,
  `planned_start`, `entry_signals`, `entry_switches`, `required_tracks`,
  `hold_until`, and `departure_shift_seconds` supply movement metadata.
- Static infrastructure, categories, configured priorities and final scheduled
  arrivals come from the checked-in `data/kz_demo` CSV tables. No external
  railway records or ML outputs are silently inserted.
- Optional explicit `train.station_stops` records contain `after_route_index`,
  `station_id`, `min_dwell_seconds`, and optional `track_ids`. These are planner
  enrichment fields; they do not change Person 1's contract. Otherwise the
  fixture's scheduled station dwell is used as the **demo minimum**, at segment
  boundaries. It is not a validated technical minimum for real rolling stock.
- Optional `scheduled_final_arrival` overrides the static final stop schedule.
  Canonical `scheduled_arrival` is a next-station time and is never silently
  treated as the final arrival.
- Default headway is explicitly **0 seconds**, matching the existing
  demonstration resource semantics. Integrators must configure a positive
  buffer when their scenario requires one; it is not an operational standard.

## Rolling horizon and occupancy

Default horizon: 3600 seconds; supported configured range: 1–3600 seconds.
Tests may use short horizons. All active trains and scheduled trains ready
before the horizon are considered deterministically. Completed/outside-horizon
trains remain in `train_plans`; their IDs appear in `deferred_train_ids`.
Considered trains unable to move have `status=deferred` in their train plan.

Only the feasible-time prefix that could begin in the horizon creates solver
variables. A started traversal may finish after the horizon. Every remaining
route block is retained in the train's `route`, but future blocks are not given
fabricated reservations. `final_arrival_time` is null unless the final route
resource is actually planned. `planned_arrival` describes the last planned
prefix traversal, not necessarily arrival at the destination.

Resource intervals use `[start_time,end_time)`. `traversal_end_time` is the
earliest completion of running/dwell. `end_time` includes holding until the
next resource is entered. The train cannot release a block early and disappear
while waiting for its next block/track.

A terminal, non-final reservation has `release_requires_replan=true` and covers
at least the horizon. Its end timestamp is **not an instruction to release the
resource**. `prepare_fork_schedule` emits a terminal hold, never a release event
for this case. A new validated rolling plan is required for continuation.

## FIFO

`plan_fifo()` remains the legacy ordering-only function.
`plan_fifo_snapshot()` and `build_fifo_plan()` produce full typed prefix plans.
The event scheduler orders ready requests by request time, descending configured
priority, then stable train ID. It checks capacity, signal/switch/closure entry
windows, station tracks, direction locks, and release buffers before entry.
Waiting trains keep their resources. Deterministic blocked states may leave a
train deferred rather than inventing an available route.

## CP-SAT

`plan_snapshot()` / `solve_intervals()` keep the existing block-only API.
`build_cp_sat_plan()` is the new full-horizon path; no two-train selection is
hard-coded. All relevant trains share one model with optional route prefixes.

Constraints include block/track capacity, fixed existing occupancy, route
precedence, minimum running/dwell, entry incident windows, opposing segment
direction locks, and resource holding/headway. Station-track alternatives are
supported when explicit/static definitions allow them; fixed required tracks
are respected. Arbitrary alternative railway routes are not generated because
the input provides an ordered route, not a validated alternative-route graph.

Primary objective: weighted positive **projected final-arrival delay in
seconds**. For a completed route prefix this is its planned final arrival. For
an incomplete route it is a lower bound using remaining minimum running/dwell;
unplanned portions cannot begin before the horizon. This is documented in
`objective_components`, and is never a completed-run evaluation metric.
Missing final scheduled arrival is explicitly unverified and excluded from the
delay objective. Category weights default to 1, configurable from 1 to 1000.
The secondary objective maximizes the number of planned prefix operations;
its scale cannot outweigh a one-unit primary objective difference.

CP-SAT uses one worker and the snapshot seed. The configured solver wall-time
budget is at most five seconds (preparation and validation are measured
separately by an integrator if needed). Fixed seeds do not guarantee an identical
incumbent under a wall-time cutoff on different machines. `plan_id` hashes the
request and output, excluding runtime measurements.

`OPTIMAL` and `FEASIBLE` results pass the common public validator before they
become candidates. OR-Tools `UNKNOWN` at the time budget is reported as
`TIMEOUT`; `INFEASIBLE`, `UNKNOWN`, `UNAVAILABLE` and `INVALID_INPUT` do not
activate a plan. A feasible incumbent at timeout is usable only after validation.
On rejection, reservation payloads are cleared, validation evidence retained,
and `fallback_used=true` / `fallback_reason` tell the integration owner to retain
the previous valid plan. This module does not persist or fabricate that fallback.

## Independent validation and unknown state

`validate_plan(snapshot, dispatch_plan, infrastructure=None)` dispatches to the
public v2 gate while preserving the legacy dict-plan validator.
It re-derives operations from the canonical state instead of trusting candidate
metadata. Violations identify type, resource, train IDs, reason, and overlap
times when relevant. Checks cover capacities, release buffers, opposing
directions, closures, signal/switch failures, route order, minimum run/dwell,
continuous train occupancy, provenance, and train-summary consistency.

- `valid`: no violations in checked constraints.
- `fully_validated`: valid, with no unverified scope.
- `eligible_for_application`: valid and fully validated.
- `validation_scope` / `unverified_scope`: precise coverage.

`UNAVAILABLE` station occupancy or `available=null` is never free space.
Plans can reserve static station tracks against each other for analysis, but
carry `station_track_occupancy_unverified`; their fork handoff is blocked.
Known occupants reserve their track until an explicit `release_time`, or the
entire horizon if no release is known. A track explicitly unavailable without
occupants cannot be selected. Unknown signal/switch state is likewise unverified.

A STOP signal derived from current occupancy/direction is governed by those
reservations. An unexplained STOP/failure without a known end blocks new entry
through the horizon. Known incident windows forbid entry, not exit by a train
already inside a block. Future `TRAIN_DELAY` events not yet materialized as
Person 1's departure shift/hold are flagged `FUTURE_TRAIN_DELAY`; such plans are
not application-eligible. Unsupported incident types fail explicitly.

## Human decisions

`validate_human_decision(canonical_snapshot, decision)` validates server-side
`GRANT_ENTRY`, `HOLD_TRAIN`, and `SELECT_STATION_TRACK`. It ignores any client
`accepted` field. Supply `snapshot_version` and, for a persisted run, `run_id`;
either stale identifier produces `STALE_SNAPSHOT`. It checks movement readiness,
occupancy, signals, switches, route and station state without applying actions.
The result's `.to_dict()` includes `accepted`, `reason`, `reason_code`,
`snapshot_version`, `run_id`, and `affected_resource`.
Stateless demo versions remain advisory; they are not live concurrency tokens.

## Eco-driving

`build_speed_advice()` accepts a canonical snapshot, validated DispatchPlan,
train ID, next block ID, distance in km, current speed in km/h, and speed limit
in km/h. It revalidates the plan, then reads the target time from that train's
next new-entry reservation. A stale, invalid or partially checked plan is
rejected. Missing target times/speeds/distances are not invented.

Required average speed is `distance_km * 3600 / remaining_seconds`. It must fit
the supplied/known caps and the configurable minimum demo speed (default 5 km/h).
The profile contains three constant-average-speed points. Changes of speed are
instantaneous assumptions in this demonstration; these are **not braking curves
or locomotive commands**. An actual STOP indication still overrides the advice.

`full_stop_avoided=true` only when the constant-current-speed reference would
arrive before its reserved slot and the advised trajectory reaches that slot
without dropping below the configured demo minimum. Otherwise it is false, or
null when necessary evidence is absent. The output names the plan and time.

Transparent dimensionless proxy:

```
energy_proxy_units = full_stops
                   + sum((acceleration_delta_kmh / speed_cap_kmh)^2)
                   + sum((braking_delta_kmh / speed_cap_kmh)^2)
                   + idle_waiting_minutes / 60
```

Both trajectories include an idealized return to the same reference speed
after the control point. Component inputs, before/after values and signed delta
are returned. This is an event penalty index, not calibrated energy or fuel.
No monetary, fuel-saving, CO2, or physical-energy claims are made.

`build_speed_profile_with_plan(..., plan=None)` returns the original limit-only
response unchanged. The existing GET endpoint remains unchanged; Person 1 can
choose the new service when a validated plan and distance/speed inputs exist.

## Integration handoff

**Person 1:** provide verified station/signal/switch state and a compatible
isolated simulation fork; connect the service functions to shared routes.
`prepare_fork_schedule` returns deterministic resource transitions, final
completion events and terminal holds. Equal-time transitions must be processed
as an atomic batch using the simulator's rules. It does not run a simulation.

**Person 3:** consume DispatchPlan provenance, per-train planned arrivals,
holding, reservations, solver wall time, validation scope and speed proxy basis.
Perform completed runs from the same initial snapshot using the same horizon,
constraints, dwell and headway settings. Do not compare the lower-bound
objective with a completed-run metric or compute improvement from it.

**Person 4:** use `solver_status`, `valid`, `fully_validated`, unverified scope,
train statuses and speed `reason_code`. Never show an unknown track as free.
`docs/examples/person2_dispatch_v2.json` is an actual generated synthetic test
example containing the input, FIFO/CP-SAT results, fork commands and speed advice.
It is for contract illustration, not the real Kazakhstan scenario or benefits.

## Tests and known integration issue

Use Python 3.11 with local `.venv`; no system-wide packages are required.

```
.venv\Scripts\python.exe -m pytest tests/test_planner_v2.py tests/test_state_contract.py -q
.venv\Scripts\python.exe -m pytest services/ai/tests tests -q
.venv\Scripts\python.exe -m services.ai.scripts.export_contracts
git diff --check
```

The existing AI test `test_canonical_demo_state_and_topology_routes` sends
`seed=20261001`. The unchanged `services/ai/main.py` v2 endpoint limits seed to
999999 and returns 422 before planning is called. Person 1 must reconcile this
endpoint limit with the canonical contract/test. This is separate from the new
planner regression suite. Current demo playback can also have initial block
capacity conflicts; the planner reports them rather than repairing the snapshot.

### Execution evidence for this change

- Python 3.11.9 runs successfully. A local ignored `.venv` was created and the
  existing AI requirements installed there; the earlier runtime blocker is gone.
- Final `python -m pytest services/ai/tests tests -q`: **111 passed, 1 failed**
  in 31.93 seconds, including all **53 new planner/validator/speed regressions**.
  The single failure is the unchanged seed-limit mismatch described above.
- Legacy pair advisory smoke: FIFO `DISPATCH_ORDER_ONLY`, CP-SAT `OPTIMAL`,
  legacy `validate_plan=true`.
- The checked-in JSON example independently passes the common validator for
  both policies. Its 7 km / 600 second example produces 42 km/h by calculation.
- Initial `SCN-ALL` canonical simulator smoke: FIFO `FEASIBLE`, CP-SAT `OPTIMAL`,
  both pass checked constraints, both explicitly unverified for station occupancy.
- `compileall`, `pip check`, and `git diff --check` completed successfully.
- The existing contract exporter completed successfully; its schema contents
  did not change. Line-ending-only output was restored to the original bytes.
- Protected Person 1 contract/adapter/store, shared app files, frontend, ML and
  agent files have no diff against the starting commit. No merge or push was made.

Do not merge this as a completed end-to-end integration: the seed-limit failure,
authoritative missing occupancy, and the simulator fork/API wiring belong to
the integration owner and are still open.
