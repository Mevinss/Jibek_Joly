"""Person 3 contracts: real public-engine runs and explicit missing-data gates."""
from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.analytics.router import create_analytics_router
from backend.analytics.service import build_analytics, quality_index, QualityFactorConfig
from backend.analytics.what_if import perturb_snapshot, what_if
from backend.connections.service import ConnectionEdge, ConnectionGraph, analyze_connection, cascade_delay, load_demo_graph, resource_dependencies
from backend.evaluation.demo import short_route_demo
from backend.evaluation.router import create_evaluation_router
from backend.evaluation.runtime import BlockRouteEngineFork
from backend.evaluation.service import aggregate_energy, assert_same_initial_conditions, compare_policies, compare_runs, execute_plan
from backend.eta.service import get_station_arrivals, get_train_eta
from backend.planner.context import timestamp
from backend.planner.models import PlanningConfig
from backend.planner.service import build_fifo_plan
from backend.simulator.engine import Simulator
from backend.simulator.state_contract import canonical_from_backend_snapshot
from backend.speed_profile.advisory import energy_proxy
from services.ai.analytics.readonly import SnapshotAnalyticsTools


@pytest.fixture(scope="module")
def measured():
    state = short_route_demo()
    config = PlanningConfig(horizon_seconds=600, time_limit_seconds=1, category_weights={"intercity": 3, "regional": 2, "freight": 1})
    result = compare_policies(state, config=config)
    assert result.comparable, result.to_dict()
    return state, config, result


@pytest.mark.parametrize("field", ["scenario_id", "seed", "dataset_version", "snapshot_hash", "incidents_hash", "rules_hash", "initial_snapshot_version", "cohort", "incident_id"])
def test_compare_requires_same_initial_conditions(measured, field):
    a, b = deepcopy(measured[2].fifo), deepcopy(measured[2].cp_sat)
    b.initial_conditions[field] = "different"
    with pytest.raises(ValueError, match="COMPARISON_NOT_COMPARABLE"):
        assert_same_initial_conditions([a, b])
    result = compare_runs([a, b])
    assert not result.comparable and result.improvement_vs_fifo_pct is None


def test_runs_are_independent_forks():
    forks = []
    class RecordingFork(BlockRouteEngineFork):
        rules_id = "test-recording-fork-v1"
        def __init__(self, snapshot, plan, schedule):
            super().__init__(snapshot, plan, schedule)
            forks.append(self)
    state = short_route_demo(1)
    before = deepcopy(state)
    result = compare_policies(state, config=PlanningConfig(horizon_seconds=300), executor_factory=RecordingFork)
    assert result.comparable and state == before
    assert forks[0].engine is not forks[1].engine
    assert forks[0].engine.trains is not forks[1].engine.trains
    forks[0].engine.trains[next(iter(forks[0].engine.trains))].delay_min = 999
    assert all(t.delay_min != 999 for t in forks[1].engine.trains.values())


def test_fork_restores_canonical_later_block_progress():
    state = short_route_demo(1)
    train = state["trains"][0]
    bid = train["route"][1]
    train.update(block_index=1, current_block_id=bid, block_id=bid, block_progress_0_1=.5,
        route_progress_0_1=.1, progress=.1, block_elapsed=0, travel_elapsed=90, status="running",
        planned_start=(timestamp(state["virtual_time"]) - timedelta(seconds=90)).isoformat())
    block = next(b for b in state["blocks"] if b["block_id"] == bid)
    block["occupied_train_ids"], block["occupied_by"] = [train["train_id"]], train["train_id"]
    plan = build_fifo_plan(state, config=PlanningConfig(horizon_seconds=300))
    run = execute_plan(state, plan)
    assert run.status == "COMPLETED"
    assert (timestamp(run.finished_at_virtual) - timestamp(state["virtual_time"])).total_seconds() == 91


def test_runtime_headway_and_no_unrelated_incident_fixture():
    state = short_route_demo()
    config = PlanningConfig(horizon_seconds=600, headway_seconds=10)
    run = execute_plan(state, build_fifo_plan(state, config=config))
    assert run.status == "COMPLETED"
    groups = {}
    for row in run.resource_observations:
        groups.setdefault(row["resource_id"], []).append(row)
    for rows in groups.values():
        rows.sort(key=lambda r: timestamp(r["start_time"]))
        for a, b in zip(rows, rows[1:]):
            assert (timestamp(b["start_time"]) - timestamp(a["end_time"])).total_seconds() >= 10
    assert not any(e["type"].startswith("INCIDENT_") for e in run.runtime_events)


def test_final_delay_counted_once_per_train(measured):
    run = measured[2].fifo
    assert len({t.train_id for t in run.train_results}) == 3
    assert run.total_arrival_delay_min == sum(t.final_delay_min for t in run.train_results)
    assert run.weighted_delay_min == sum(t.final_delay_min * t.priority_weight for t in run.train_results)
    plan = build_fifo_plan(measured[0], config=measured[1])
    assert run.train_results[0].actual_final_arrival != plan.train_plans[0].final_arrival_time


def test_added_delay_after_incident():
    state = short_route_demo(1)
    state["trains"][0]["delay_min"] = 8
    bid = state["trains"][0]["route"][0]
    next(b for b in state["blocks"] if b["block_id"] == bid)["closed"] = True
    state["active_incidents"] = [dict(incident_id="I", type="BLOCK_CLOSURE", block_id=bid,
        at=state["virtual_time"], duration_min=13)]
    run = execute_plan(state, build_fifo_plan(state, config=PlanningConfig(horizon_seconds=1000)))
    assert run.status == "COMPLETED"
    train = run.train_results[0]
    assert train.delay_at_incident_min == 8
    assert train.added_delay_after_incident_min == pytest.approx(max(0, train.final_delay_min - 8))


def test_missing_incident_baseline_not_zero(measured):
    assert measured[2].fifo.added_delay_after_incident_min is None


@pytest.mark.parametrize("fifo,cp,expected", [(0, 0, None), (10, 11, -10), (10, 5, 50)])
def test_improvement_zero_and_negative_preserved(measured, fifo, cp, expected):
    a, b = deepcopy(measured[2].fifo), deepcopy(measured[2].cp_sat)
    a.total_arrival_delay_min, b.total_arrival_delay_min = fifo, cp
    assert compare_runs([a, b]).improvement_vs_fifo_pct == expected


def test_human_optional_and_timeouts(measured):
    state, config, _ = measured
    plan = build_fifo_plan(state, config=config)
    result = compare_policies(state, config=config, human_plan=plan, human_decisions=[{"action": "AUTO_FIFO_TIMEOUT"}])
    assert result.comparable
    assert result.human.auto_fifo_timeout_count == 1
    assert result.human_minus_cp_sat_delay_min == result.human.total_arrival_delay_min - result.cp_sat.total_arrival_delay_min
    assert measured[2].human is None


def test_conflict_count_not_hardcoded():
    class ViolatingFork(BlockRouteEngineFork):
        rules_id = "test-injected-violation-v1"
        def advance(self, seconds):
            frame = super().advance(seconds)
            frame["runtime_violations"].append(dict(type="TEST_CAPACITY_VIOLATION", resource_id="test"))
            return frame
    state = short_route_demo(1)
    run = execute_plan(state, build_fifo_plan(state, config=PlanningConfig(horizon_seconds=300)), executor_factory=ViolatingFork)
    assert run.conflict_count == 1 and not run.valid
    assert run.runtime_violations[0]["type"] == "TEST_CAPACITY_VIOLATION"


def test_missing_runtime_monitoring_is_not_zero_conflicts():
    class UnmonitoredFork(BlockRouteEngineFork):
        rules_id = "test-unmonitored-v1"
        def advance(self, seconds):
            frame = super().advance(seconds)
            frame.pop("runtime_violations")
            return frame
    state = short_route_demo(1)
    run = execute_plan(state, build_fifo_plan(state, config=PlanningConfig(horizon_seconds=300)), executor_factory=UnmonitoredFork)
    assert run.conflict_count is None and not run.valid and not run.safety_scope_complete


def test_human_with_different_configuration_not_comparable(measured):
    state, config, _ = measured
    human = build_fifo_plan(state, config=PlanningConfig(horizon_seconds=400))
    result = compare_policies(state, config=config, human_plan=human)
    assert not result.comparable and result.human.plan_policy == "FIFO"


def test_energy_proxy_aggregates_person2_components(measured):
    components = [dict(full_stops=2, acceleration_changes=[30], braking_changes=[40], speed_limit_kmh=80, idle_waiting_minutes=6),
                  dict(full_stops=1, acceleration_changes=[], braking_changes=[], speed_limit_kmh=60, idle_waiting_minutes=12)]
    assert aggregate_energy(components) == pytest.approx(sum(energy_proxy(**c) for c in components))
    assert aggregate_energy(None) is None
    assert measured[2].fifo.energy_proxy_units is None
    assert measured[2].fifo.full_stop_avoided_count is None


def test_incomplete_train_not_given_fake_arrival():
    state = short_route_demo(1)
    run = execute_plan(state, build_fifo_plan(state, config=PlanningConfig(horizon_seconds=30)))
    assert run.status == "HORIZON_REACHED"
    assert run.train_results[0].termination_reason == "OUTSIDE_HORIZON"
    assert run.train_results[0].actual_final_arrival is None
    assert run.total_arrival_delay_min is None


def test_default_network_is_explicitly_unavailable():
    state = canonical_from_backend_snapshot(Simulator().snapshot().to_dict())
    result = compare_policies(state, config=PlanningConfig(horizon_seconds=300, time_limit_seconds=.1))
    assert not result.comparable
    assert result.fifo.status in {"UNVERIFIED_PLAN", "EXECUTOR_UNAVAILABLE", "INVALID_PLAN"}
    assert result.improvement_vs_fifo_pct is None
    assert not result.fifo.safety_scope_complete


def test_invalid_plan_and_unverified_scope_are_retained(measured):
    state, config, _ = measured
    plan = build_fifo_plan(state, config=config).to_dict()
    plan["seed"] += 1
    run = execute_plan(state, plan)
    assert run.status == "INVALID_PLAN" and run.conflict_count > 0
    assert run.simulation_ms is None
    state = deepcopy(state)
    state["station_tracks"] = canonical_from_backend_snapshot(Simulator().snapshot().to_dict())["station_tracks"]
    run = execute_plan(state, build_fifo_plan(state, config=config))
    assert run.status == "UNVERIFIED_PLAN"
    assert run.validation["unverified_scope"]


def test_eta_from_dispatch_plan(measured):
    state, config, _ = measured
    plan = build_fifo_plan(state, config=config)
    eta = get_train_eta(state, state["trains"][0]["train_id"], "BOR", plan)
    row = next(t for t in plan.train_plans if t.train_id == eta.train_id)
    assert eta.source == "PLAN_BASED" and eta.eta == row.final_arrival_time
    assert eta.track_status == "UNKNOWN" and eta.recommended_track is None


def test_eta_schedule_fallback(measured):
    state = deepcopy(measured[0])
    train = state["trains"][0]
    train["delay_min"] = 5
    eta = get_train_eta(state, train["train_id"], "BOR")
    assert eta.source == "SCHEDULE_FALLBACK" and eta.delay_min == 5


def test_eta_unavailable_when_data_missing(measured):
    state = deepcopy(measured[0])
    train = state["trains"][0]
    train["scheduled_final_arrival"] = train["scheduled_arrival"] = None
    infra = dict(blocks={}, segments={}, signals={}, stops=[])
    assert get_train_eta(state, train["train_id"], "BOR", infrastructure=infra).eta is None


def test_eta_stale_and_partial_plan_not_substituted(measured):
    state, config, _ = measured
    plan = build_fifo_plan(state, config=config).to_dict()
    plan["snapshot_version"] += 1
    assert get_train_eta(state, state["trains"][0]["train_id"], "BOR", plan).source == "UNAVAILABLE"


def test_station_arrivals_sorted(measured):
    state, config, _ = measured
    result = get_station_arrivals(state, "BOR", build_fifo_plan(state, config=config))
    assert [timestamp(t.eta) for t in result.arrivals] == sorted(timestamp(t.eta) for t in result.arrivals)
    assert len(result.arrivals) == 3


def test_connection_graph_synthetic_label():
    graph = load_demo_graph()
    assert graph.source_type == "SYNTHETIC_DEMO" and len(graph.edges) == 5
    assert all(e.passenger_weight_proxy is None for e in graph.edges)


def test_connection_wait_analysis():
    result = analyze_connection(load_demo_graph(), 0, 5)
    assert result["wait"]["direct_wait_min"] == 5 and result["wait"]["protected_connection"]
    assert not result["depart_on_time"]["protected_connection"]
    assert result["wait"]["network_added_delay_min"] > result["depart_on_time"]["network_added_delay_min"]
    assert result["passenger_count"] is None


def test_cascade_propagates_and_network_added_delay():
    result = cascade_delay(load_demo_graph(), "SIM-DEMO-A", 5)
    delays = {t["train_id"]: t["added_delay_min"] for t in result.affected_trains}
    assert delays["SIM-DEMO-B"] == 5 and delays["SIM-DEMO-C"] == 3
    assert delays["SIM-DEMO-E"] == 1  # maximum at join, not summed
    assert result.network_added_delay_min == 5 + sum(delays.values())


def test_cascade_cycle_detection():
    graph = load_demo_graph()
    graph.edges.append(ConnectionEdge("SIM-DEMO-B", "SIM-DEMO-A", "AST", 0,
        "2026-10-01T10:10:00+05:00", "2026-10-01T10:10:00+05:00"))
    result = cascade_delay(graph, "SIM-DEMO-A", 5)
    assert result.cycle_detected
    assert all(t["train_id"] != "SIM-DEMO-A" for t in result.affected_trains)


def test_cascade_max_depth_and_time_horizon():
    graph = load_demo_graph()
    result = cascade_delay(graph, "SIM-DEMO-A", 5, max_depth=1)
    assert result.truncated and all(t["depth"] == 1 for t in result.affected_trains)
    bounded = cascade_delay(graph, "SIM-DEMO-A", 5, horizon_min=5)
    assert {t["train_id"] for t in bounded.affected_trains} == {"SIM-DEMO-B", "SIM-DEMO-D"}


def test_resource_dependencies_derived_from_validated_plan(measured):
    state, config, _ = measured
    edges = resource_dependencies(state, build_fifo_plan(state, config=config))
    assert len(edges) == 6 and all(e.connection_type == "BLOCK_RELEASE" for e in edges)


def test_quality_contributions_sum_and_deterministic(measured):
    result = quality_index(measured[2].fifo)
    assert result.score == pytest.approx(100 - sum(f["contribution"] for f in result.factors))
    assert result.to_dict() == quality_index(measured[2].fifo).to_dict()
    unknown = quality_index(measured[2].fifo, [QualityFactorConfig("energy_proxy_units", 1, 10)])
    assert unknown.score is None


@pytest.mark.parametrize("kind", ["EXTRA_DELAY", "CONNECTION_WAIT", "BLOCK_CLOSURE", "SIGNAL_DELAY"])
def test_what_if_isolated_clones(kind):
    state = short_route_demo(1)
    before = deepcopy(state)
    train = state["trains"][0]
    target = train["route"][0] if kind == "BLOCK_CLOSURE" else train["entry_signals"][0] if kind == "SIGNAL_DELAY" else train["train_id"]
    result = what_if(state, kind, target, 2, config=PlanningConfig(horizon_seconds=600))
    assert state == before and result.original_snapshot_unchanged
    assert result.delta["fifo"] is not None and result.delta["fifo"] > 0


def test_analytics_uses_observations(measured):
    result = build_analytics(measured[2].fifo)
    assert result["resource_utilization"]
    assert all(0 <= r["occupied_time_fraction"] <= 1 for r in result["resource_utilization"])
    assert result["incident_impact"]["causal_attribution"] == "NOT_ESTABLISHED"


def test_llm_read_only_tools_and_grounding(measured):
    state, config, compare = measured
    tools = SnapshotAnalyticsTools(state, compare=compare, run=compare.fifo, plan=build_fifo_plan(state, config=config))
    assert tools.call("get_compare_result")["source"] == "RUNTIME_EVALUATION"
    assert tools.call("get_cascade_result")["status"] == "UNAVAILABLE"
    with pytest.raises(ValueError, match="READ_ONLY"):
        tools.call("apply_plan")
    other = deepcopy(state)
    other["seed"] += 1
    with pytest.raises(ValueError, match="UNRELATED"):
        SnapshotAnalyticsTools(other, compare=compare)


def test_router_contract_seed_and_missing_provider():
    app = FastAPI()
    state = short_route_demo(1)
    app.include_router(create_evaluation_router())
    app.include_router(create_analytics_router(lambda: state))
    client = TestClient(app)
    response = client.post("/api/compare", json={"snapshot": state, "config": {"horizon_seconds": 300}})
    assert response.status_code == 200 and response.json()["seed"] == 20261001
    assert client.get("/api/stations/BOR/arrivals").status_code == 200
    assert client.get("/api/quality-index").status_code == 503
    assert client.post("/api/compare", json={"snapshot": state, "config": {"horizon_seconds": -1}}).status_code == 422


def test_no_physical_energy_or_fake_fuel_claims(measured):
    payload = json.dumps(measured[2].to_dict()).lower()
    assert "kwh" not in payload and "fuel saved" not in payload and "co2" not in payload


def test_generated_examples_match_published_json_schemas():
    from jsonschema import Draft202012Validator
    root = Path(__file__).resolve().parents[1]
    pairs = dict(compare="CompareResult", station_arrivals="StationArrivalsResult", train_eta="TrainETA",
        cascade="CascadingDelayResult", quality_index="QualityIndexResult", what_if="WhatIfResult")
    for example, contract in pairs.items():
        schema = json.loads((root / "backend/evaluation/contracts" / (contract + ".schema.json")).read_text(encoding="utf-8"))
        payload = json.loads((root / "docs/examples" / ("person3_" + example + ".json")).read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(payload)
