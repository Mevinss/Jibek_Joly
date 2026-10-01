# PERSON 3 STATUS

These changes are committed directly on `main` at the user's request. No new branch, push or merge is created. Person 1/2 and frontend files are unchanged.

## DONE

Implemented executable evaluation, strict comparison, ETA, station arrivals, synthetic connections, bounded cascading delay, snapshot what-if, transparent quality index, structured analytics, optional routers and a separate read-only explanation adapter.

**Full 28-train station-capable execution is not DONE.** The public simulator does not yet execute station reservations/dwell or atomic station transitions. Its canonical station occupancy is unknown. Those runs return unavailable/unverified, never fabricated completion or improvement.

## CHANGED FILES

- `backend/evaluation/{models,service,runtime,router,demo,demo_app,export_contracts}.py`, its package exports and `backend/evaluation/contracts/*.schema.json`.
- New `backend/eta/`, `backend/connections/`, `backend/analytics/`.
- New `services/ai/analytics/readonly.py`; existing LLM/ML modules unchanged.
- `tests/test_person3_evaluation.py`.
- This report and `docs/examples/person3_*.json`.
- Existing legacy `backend/evaluation/metrics.py` remains unchanged; integration should use the new service for strict comparisons.

## COMPLETED RUN

`DispatchRunResult` / `TrainRunResult` are dataclasses with `to_dict()`, separate from `DispatchPlan`. They preserve provenance, plan policy, initial hashes, validation scope, observed train arrivals, timings, events, occupancy intervals and missing telemetry.

`execute_plan(snapshot, plan, ...)` revalidates through Person 2's common validator, calls `prepare_fork_schedule`, and creates an independent executor from deep copies. `BlockRouteEngineFork` supports block-only routes of multiple blocks, capacity one, on the existing KZ engine. It uses `restore_state`, `can_enter`, `advance(1)` and snapshot observations. Entry commands add timing gates; completion commands add holds, never assign completed status. Unsupported station operations/capacity/infrastructure/incident semantics return `EXECUTOR_UNAVAILABLE`.

End condition: all initially non-completed trains reach the engine's destination status, or the configured horizon expires. Completion time is the first observed completed frame, with one-second observation resolution. It can differ from planned arrival; the examples retain this difference.

Incomplete train: `completed=false`, `actual_final_arrival=null`, `termination_reason=OUTSIDE_HORIZON`. An observed completed subtotal is separate from the comparable total. The latter is null until the complete initial cohort has observed final arrivals and known final schedules. Already completed trains are excluded; no historical arrivals are invented.

Conflicts count distinct independent-validator/runtime violations. A runtime without an explicit monitoring log remains unverified, with null conflict count. Zero comes from an empty observed violation log, not a toy formula. Validation here covers declared demonstration rules, not operational railway safety.

Speed telemetry is not modelled by the current engine. Consequently energy and avoided-stop results are null in these runs. `aggregate_energy` uses Person 2's `energy_proxy` unchanged when an executor supplies cumulative measured components: stops + squared normalized speed changes + idle minutes/60. No physical energy or fuel savings are inferred. Stop counts record transitions from running to waiting/held; predeparture waiting is not a full stop.

## COMPARE

`compare_policies` builds FIFO/CP-SAT on separate clones, then executes separate forks. Optional HUMAN is a supplied validated plan executed under the HUMAN result label; its underlying `plan_policy` remains FIFO/CP_SAT. Interactive Human decisions are not synthesized. Supplied timeout events are counted separately.

`assert_same_initial_conditions` checks scenario, seed, dataset, version, entire canonical snapshot hash, incident schedule, movement-rule/config/infrastructure hash, cohort and selected incident baseline. Result provenance must agree with these conditions. Mismatch, incomplete execution, unknown final schedules, invalid or unverified execution yields `COMPARISON_NOT_COMPARABLE` with null improvement.

Final delay per train = `max(0, actual_final_arrival - scheduled_final_arrival)` in minutes, counted once. Category weights come from the same `PlanningConfig`, with Person 2's neutral default; weighted delay remains a separate field.

Incident-added delay = `max(0, final_delay - delay_at_incident)`. An incident at the initial instant uses supplied current delay; a future onset is observed during the run. A past onset requires an explicit historical `delay_at_incident_min`. Missing/no incident baseline returns null, not zero. By default the earliest supplied incident is selected; `incident_id` can explicitly choose one.

Improvement = `100 * (FIFO - CP_SAT) / FIFO` only for comparable completed runs and positive FIFO delay. Zero FIFO gives null; negative improvement remains negative. Human-minus-CP-SAT is computed only when Human is also comparable.

## ETA

`get_train_eta` uses revalidated plan reservation timing, station dwell reservations and complete-route arrival. Known prior resource waits/dwells are already represented in those timestamps. It never extrapolates beyond an unplanned route prefix or horizon. Invalid/stale supplied plans return unavailable instead of a different fixture.

Without a plan: schedule + current delay, labelled `SCHEDULE_FALLBACK`; future contention is not modelled. Missing or past estimates return `UNAVAILABLE`. Source labels are `PLAN_BASED`, `SCHEDULE_FALLBACK`, `UNAVAILABLE`; no calibrated confidence probability is supplied.

`get_station_arrivals` sorts known arrivals by timestamp and train ID; missing estimates follow. Track occupancy stays UNKNOWN unless the supplied snapshot confirms track state and the plan reserves it; `PLAN_RESERVED` does not claim the track is currently free.

## CONNECTION GRAPH

`backend/connections/fixtures/kz_connections.json`: five explicit `SYNTHETIC_DEMO` edges with SIM-DEMO identifiers and Kazakhstan stations. This separate illustrative schedule is **not** the live 28-train timetable and is never loaded as a live/chat fallback. No passenger counts are fabricated; proxy fields are null.

`analyze_connection(graph, edge_index, incoming_delay_min)` compares waiting versus removing that connection wait. Outputs direct wait, protection, downstream affected count and network-added delay. This is analytical schedule propagation, not a completed dispatch run or a recommendation calibrated to passenger demand. Listed other connections are assumed to wait in both options.

## CASCADING DELAY

`cascade_delay`: successor delay = max(0, predecessor delay - baseline schedule slack). At joins use maximum required delay. Root and each affected train contribute once to network total. Chain entries are computed edges with slack/cause/depth, not LLM text.

Synchronous bounded propagation costs O(depth × edge count). Default depth 4 and horizon 60 minutes; configurable bounds, path cycle detection, and truncation markers. Results outside these bounds are omitted; the total is the bounded estimate. Baseline infeasible connections are rejected explicitly.

`resource_dependencies` derives capacity-one block/track successors from a validated plan; no assumed dependency is added for multi-capacity resources. `cascade_from_snapshot` requires all graph IDs in the supplied snapshot, optionally includes those resource dependencies and binds a snapshot hash. Only bound cascades can enter snapshot chat tools.

## QUALITY INDEX

Implemented after core metrics. `quality_index`: 100 minus sum of penalty contributions. Each contribution is `100 * weight * clip(value/cap, 0, 1)`. Weights must sum to one.

Demonstration defaults: mean final delay weight .5/cap 20 min, stops per train weight .25/cap 2, invalid/unverified run weight .25/cap 1. Each factor exposes value, cap, weight, normalized value, contribution and reason. Missing configured metrics or incomplete runs produce null score. Configurable, transparent, **not scientifically calibrated**. Timing/energy factors are optional and are not silently substituted.

## WHAT-IF / ANALYTICS

`what_if(snapshot, kind, target_id, minutes, ...)` supports EXTRA_DELAY, CONNECTION_WAIT (explicit chosen waiting minutes), BLOCK_CLOSURE and SIGNAL_DELAY. It clones before applying shifts/holds/incident windows, runs base/scenario comparisons and returns observed delay deltas by policy only when available. Connection protection/network analysis is separately provided by `analyze_connection`. No live simulator is accessed. Whole-minute incident durations follow existing engine semantics.

`build_analytics` exposes observed occupied-time union/fraction per resource, busiest blocks, category completed delay, incomplete counts, stops, proxy availability, fallback/rejection counts and incident events. Unattributed waits remain unattributed; incident co-occurrence is not labelled causal impact. Capacity utilization or passenger impact is not inferred from missing data.

Robustness analysis: not implemented; optional in the prompt. No invented robustness percentage.

## LLM

Existing agent/ML code unchanged. Optional `SnapshotAnalyticsTools` supplies only six allowlisted read-only data functions: compare, plan summary, train ETA, station arrivals, cascade, quality. It rejects unrelated plans/runs and cascades without matching snapshot provenance. Missing values return DATA_NOT_SUPPLIED. It contains no model calls, control tools or fuel-saving claims. Provider/tool wiring remains the AI integration owner's responsibility.

## TESTS

Commands (Python 3.11 in `.venv`):

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_person3_evaluation.py -q
.\.venv\Scripts\python.exe -m pytest services/ai/tests tests -q
.\.venv\Scripts\python.exe -m services.ai.scripts.export_contracts
.\.venv\Scripts\python.exe -m backend.evaluation.export_contracts
.\.venv\Scripts\python.exe -m backend.evaluation.demo
```

Final verification: **47 new tests passed**. Full suite: **163 passed, 1 failed**, with the same existing seed-restriction failure in `services/ai/tests/test_kz_demo.py::test_canonical_demo_state_and_topology_routes` (422 instead of 200 for seed 20261001). No new failure. FastAPI emits an existing httpx/TestClient deprecation warning.

Both schema exporters succeeded; all six requested contract examples validate against their published JSON schemas. Example generation completed real independent FIFO/CP-SAT short-route runs. The isolated API was started on port 8003 and HTTP-checked for OpenAPI, measured comparison, plan-based station arrivals and quality. `git diff --check` passed. All changes are in owned modules/tests/docs. Shared export was run; newline-only regeneration was reverted, leaving shared contract files unchanged.

## PERSON 4 HANDOFF

Dataclass/JSON-schema contracts live in `backend/evaluation/contracts/`. Generated examples:

- CompareResult: `docs/examples/person3_compare.json`.
- StationArrivalsResult: `docs/examples/person3_station_arrivals.json`.
- TrainETA: `docs/examples/person3_train_eta.json`.
- CascadingDelayResult: `docs/examples/person3_cascade.json`.
- QualityIndexResult: `docs/examples/person3_quality_index.json`.
- WhatIfResult: `docs/examples/person3_what_if.json`.
- Additional analytics/connection decision/input evidence: the corresponding `person3_analytics`, `person3_connection_decision`, `person3_initial_snapshot` JSON files.

Reproduce via `python -m backend.evaluation.demo`. Runtime examples use three synthetic shortened KOK→BOR journeys, all three real segment blocks, 60 demonstration seconds/block, explicitly changed schedule/dataset version, no station dwell, 600-second horizon. The incident/energy-null fields are intentional. Do not present this as measured benefit on all 28 original journeys. Planner/simulation wall times vary by machine; virtual arrivals and arithmetic are deterministic with fixed inputs.

Optional isolated API demo: `python -m backend.evaluation.demo_app`, then `http://127.0.0.1:8003/docs`. `/demo/input` and `/demo/compare` expose the explicitly labelled short-route fixture/evidence; other routes use the same supplied snapshot. This separate service does not install routes in the shared port-8002 application.

The running API demo uses neutral category weights (the JSON evidence generator uses explicit 3/2/1 weights). Its checked runtime result was FIFO 3.05 total delay minutes and CP-SAT 3.10, improvement approximately **−1.64%**. This measured loss is preserved. It is a result of this scoped demonstration/one-second engine execution, not an estimate for operational journeys or a fixed optimizer benefit. Every result includes its planning config and movement-rules identifier.

## PERSON 1 INTEGRATION HANDOFF

Service imports:

```python
from backend.evaluation.service import compare_policies, execute_plan, compare_runs
from backend.eta.service import get_train_eta, get_station_arrivals
from backend.connections.service import cascade_from_snapshot, analyze_connection
from backend.analytics.service import quality_index, build_analytics
from backend.analytics.what_if import what_if
```

Opt-in router imports (no shared app changes or duplicate existing routes):

```python
from backend.evaluation.router import create_evaluation_router
from backend.analytics.router import create_analytics_router

app.include_router(create_evaluation_router(executor_factory=YourStationCapableFork))
app.include_router(create_analytics_router(
    snapshot_provider=get_current_canonical_snapshot,
    plan_provider=get_current_dispatch_plan,
    run_provider=get_current_observed_run,
    executor_factory=YourStationCapableFork,
))
```

Request models: CompareRequest, CascadeRequest, WhatIfRequest. Response models: dataclasses listed above; routes expose them in OpenAPI. Canonical snapshot validation uses Person 2's existing contract; no new seed cap is introduced.

Routes ready to include: POST `/api/compare`, GET `/api/stations/{station_id}/arrivals`, GET `/api/trains/{train_id}/eta`, POST `/api/analytics/cascade`, GET `/api/quality-index`, POST `/api/what-if`. Missing current snapshot/run providers return 503; stale quality-run provenance returns 409; invalid inputs return 422. These routes are **not yet installed** in the main service.

Executor protocol: factory `(snapshot_copy, plan_dict_copy, prepared_schedule_copy)` creates a completely independent fork and declares stable `rules_id`. `snapshot()` exposes initial scenario/seed/version/time/cohort; `advance(1)` advances one virtual second using the shared movement rules, returning train state/status/block, explicit `runtime_violations` list and optional events. Do not copy planned final arrival into runtime completion. Optional row `energy_components` must be cumulative **observed** Person 2 component dictionaries; optional `full_stop_avoided` must represent adopted measured advice. Missing telemetry is unknown. Resource observation collector currently records blocks; a station-capable integration must extend its observed station interval reporting before claiming station utilization.

## BLOCKERS

1. Existing `test_canonical_demo_state_and_topology_routes`: `/api/v2/state` rejects seed 20261001 with 422 due to the shared maximum 999999. Person 3 does not change that restriction.
2. Full KZ station execution requires Person 1's compatible independent fork executor and explicit track occupancy. `prepare_fork_schedule` intentionally refuses partially validated plans. The current engine has no atomic station-reservation execution API; no bypass was added.
3. Energy/avoided-stop metrics require actual executor telemetry; null until supplied. Main application/router and frontend replacement are integration/Person 4 tasks.

## DO NOT MERGE YET

Yes for full shared integration: resolve the existing seed mismatch, provide station-capable execution, agree router inclusion and replace browser toy metrics through Person 4. Local owned-module implementation and short-route evidence are reviewable; no merge or push was performed.
