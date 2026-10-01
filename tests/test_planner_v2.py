"""Full-plan contract regressions: independent validation and actual CP-SAT."""
from copy import deepcopy
from datetime import datetime, timedelta

import pytest

from backend.planner.cp_sat import build_snapshot_block_operations
from backend.planner.models import PlanningConfig
from backend.planner.service import build_cp_sat_plan, build_fifo_plan
from backend.validator.resources import validate_human_decision, validate_plan
from backend.speed_profile.advisory import build_speed_advice, energy_proxy

BASE = datetime.fromisoformat("2026-10-01T09:00:00+05:00")


def iso(seconds=0):
    return (BASE + timedelta(seconds=seconds)).isoformat()


def fixture(count=3, blocks=2, *, dwell=0):
    infra = {"blocks": {}, "segments": {"SEG": {"direction_lock": "one_direction_at_a_time"}},
             "signals": {}, "switches": {}, "station_tracks": {"S-T1": {"station_id": "S", "demo_capacity_trains": 1}}}
    state = dict(schema_version="2.0", scenario_id="SCN-TEST", seed=42, run_id="RUN-1", dataset_version="test-v1",
                 snapshot_version=9, virtual_time=iso(), source_type="SIMULATED_DEMO", trains=[], blocks=[], signals=[], switches=[],
                 active_incidents=[], station_tracks=[dict(track_id="S-T1", station_id="S", capacity=1,
                     occupied_train_ids=[], available=True, occupancy_source="SIMULATED")])
    for i in range(blocks):
        bid, sid = f"B{i}", f"SIG{i}"
        infra["blocks"][bid] = dict(segment_id="SEG", demo_capacity_trains=1)
        infra["signals"][sid] = dict(block_id=bid, entry_direction_from="S")
        state["blocks"].append(dict(block_id=bid, segment_id="SEG", capacity=1, occupied_train_ids=[],
                                    occupied_by=None, closed=False, state_conflict=False, speed_limit_kmh=80))
        state["signals"].append(dict(signal_id=sid, aspect="CLEAR", failed=False))
    for i in range(count):
        state["trains"].append(dict(train_id=f"SIM-{i}", route=[f"B{j}" for j in range(blocks)],
            block_seconds=[100] * blocks, entry_signals=[f"SIG{j}" for j in range(blocks)],
            entry_switches=[None] * blocks, required_tracks=[None] * blocks,
            block_index=-1, current_block_id=None, block_id=None, block_progress_0_1=0.0,
            route_progress_0_1=0.0, progress=0.0, status="scheduled", planned_start=iso(),
            scheduled_final_arrival=iso(blocks * 100 + dwell), category="passenger", priority=i,
            speed_kmh=80, station_stops=[dict(after_route_index=0, station_id="S", track_ids=["S-T1"], min_dwell_seconds=dwell)] if dwell else []))
    return state, infra


def moving(state, index, progress, tid=0):
    train = state["trains"][tid]
    train.update(block_index=index, current_block_id=f"B{index}", block_id=f"B{index}",
                 block_progress_0_1=progress, route_progress_0_1=.1, progress=.1, status="running")
    state["blocks"][index]["occupied_train_ids"].append(train["train_id"])
    state["blocks"][index]["occupied_by"] = state["blocks"][index]["occupied_train_ids"][0]


def test_cp_sat_uses_block_progress_not_route_progress():
    state, infra = fixture(1, 4)
    moving(state, 2, .75)
    assert build_snapshot_block_operations(state, infrastructure=infra)[0]["earliest_start_offset"] == 25


def test_later_route_block_remaining_time():
    state, infra = fixture(1, 4)
    moving(state, 2, .75)
    plan = build_cp_sat_plan(state, infrastructure=infra)
    assert plan.valid, plan.validation
    assert plan.resource_intervals[0].traversal_end_time == iso(25)
    assert plan.resource_intervals[1].start_time >= iso(25)


@pytest.mark.parametrize("builder", [build_fifo_plan, build_cp_sat_plan])
def test_multiple_block_occupants_not_dropped(builder):
    state, infra = fixture(2, 1)
    moving(state, 0, .5, 0)
    moving(state, 0, .5, 1)
    state["blocks"][0]["capacity"] = 2
    infra["blocks"]["B0"]["demo_capacity_trains"] = 2
    plan = builder(state, infrastructure=infra)
    assert plan.valid, plan.validation
    assert {r.train_id for r in plan.resource_intervals} == {"SIM-0", "SIM-1"}


def test_initial_capacity_conflict_detected():
    state, infra = fixture(2, 1)
    moving(state, 0, .5, 0)
    moving(state, 0, .5, 1)
    for builder in (build_fifo_plan, build_cp_sat_plan):
        plan = builder(state, infrastructure=infra)
        assert not plan.valid and not plan.resource_intervals
        assert plan.validation.violations[0].type == "INITIAL_CAPACITY_CONFLICT"
        assert plan.validation.violations[0].train_ids == ["SIM-0", "SIM-1"]


def test_fifo_deterministic():
    state, infra = fixture()
    original = deepcopy(state)
    a, b = (build_fifo_plan(state, infrastructure=infra) for _ in range(2))
    assert a.plan_id == b.plan_id
    assert a.resource_intervals == b.resource_intervals
    assert state == original
    first = min(a.resource_intervals, key=lambda r: r.start_time)
    assert first.train_id == "SIM-2"


@pytest.mark.parametrize("builder", [build_fifo_plan, build_cp_sat_plan])
@pytest.mark.parametrize("kind", ["BLOCK_CLOSURE", "SIGNAL_FAILURE", "SWITCH_FAILURE"])
def test_plans_respect_incident_windows(builder, kind):
    state, infra = fixture(1, 1)
    event = dict(incident_id="I", type=kind, at=iso(), duration_min=5)
    if kind == "BLOCK_CLOSURE":
        event["block_id"] = "B0"
        state["blocks"][0]["closed"] = True
    elif kind == "SIGNAL_FAILURE":
        event["signal_id"] = "SIG0"
        state["signals"][0].update(aspect="STOP", failed=True)
    else:
        event["switch_id"] = "SW"
        state["switches"] = [dict(switch_id="SW", position="T2", failed=True, available_routes=["S-T1", "S-T2"])]
        state["trains"][0].update(entry_switches=["SW"], required_tracks=["S-T1"])
    state["active_incidents"] = [event]
    plan = builder(state, infrastructure=infra)
    assert plan.valid, plan.validation
    assert plan.resource_intervals[0].start_time >= iso(300)


@pytest.mark.parametrize("builder", [build_fifo_plan, build_cp_sat_plan])
def test_full_plan_passes_common_validator(builder):
    state, infra = fixture()
    plan = builder(state, infrastructure=infra)
    assert plan.valid and plan.fully_validated, plan.validation
    assert validate_plan(state, plan.to_dict(), infra).valid
    assert len(plan.train_plans) == 3


def test_cp_sat_considers_more_than_two_relevant_trains():
    state, infra = fixture(6)
    plan = build_cp_sat_plan(state, infrastructure=infra)
    assert len(plan.considered_train_ids) == 6
    assert {r.train_id for r in plan.resource_intervals} == {t["train_id"] for t in state["trains"]}


def test_direction_lock():
    state, infra = fixture(2, 2)
    state["trains"][1].update(route=["B1", "B0"], entry_signals=["R1", "R0"])
    for i in range(2):
        infra["signals"][f"R{i}"] = dict(block_id=f"B{i}", entry_direction_from="OTHER")
        state["signals"].append(dict(signal_id=f"R{i}", aspect="CLEAR", failed=False))
    for builder in (build_fifo_plan, build_cp_sat_plan):
        plan = builder(state, infrastructure=infra)
        assert plan.valid, plan.validation
        a = [r for r in plan.resource_intervals if r.train_id == "SIM-0"]
        b = [r for r in plan.resource_intervals if r.train_id == "SIM-1"]
        assert a[-1].end_time <= b[0].start_time or b[-1].end_time <= a[0].start_time


def tamper(plan, row_index, **changes):
    data = plan.to_dict()
    row = data["resource_intervals"][row_index]
    row.update(changes)
    train = next(t for t in data["train_plans"] if t["train_id"] == row["train_id"])
    next(r for r in train["resource_reservations"] if r["sequence"] == row["sequence"]).update(changes)
    return data


def test_station_track_overlap_rejected():
    state, infra = fixture(2, 2, dwell=120)
    plan = build_fifo_plan(state, infrastructure=infra)
    assert plan.valid
    track_indexes = [i for i, r in enumerate(plan.resource_intervals) if r.resource_type == "station_track"]
    a, b = track_indexes
    row = plan.resource_intervals[a]
    bad = tamper(plan, b, start_time=row.start_time, end_time=row.end_time, traversal_end_time=row.traversal_end_time)
    assert "STATION_TRACK_OVERLAP" in {v.type for v in validate_plan(state, bad, infra).violations}


@pytest.mark.parametrize("builder", [build_fifo_plan, build_cp_sat_plan])
def test_minimum_dwell(builder):
    state, infra = fixture(1, 2, dwell=60)
    plan = builder(state, infrastructure=infra)
    assert plan.valid, plan.validation
    assert plan.resource_intervals[1].traversal_end_time == iso(160)
    bad = tamper(plan, 1, traversal_end_time=iso(110))
    assert "MINIMUM_DWELL" in {v.type for v in validate_plan(state, bad, infra).violations}


@pytest.mark.parametrize("builder", [build_fifo_plan, build_cp_sat_plan])
def test_headway(builder):
    state, infra = fixture(2, 1)
    plan = builder(state, config=PlanningConfig(headway_seconds=30), infrastructure=infra)
    assert plan.valid, plan.validation
    rows = sorted(plan.resource_intervals, key=lambda r: r.start_time)
    assert (datetime.fromisoformat(rows[1].start_time) - datetime.fromisoformat(rows[0].end_time)).total_seconds() >= 30


def test_solver_timeout_does_not_return_unvalidated_plan(monkeypatch):
    from backend.planner import service
    state, infra = fixture()
    monkeypatch.setattr(service, "_cp_sat", lambda ctx: ([], "TIMEOUT", 5_000.0))
    plan = build_cp_sat_plan(state, infrastructure=infra)
    assert plan.fallback_used and not plan.valid and not plan.resource_intervals
    assert plan.solver_status == "TIMEOUT" and not plan.eligible_for_application


def test_invalid_cp_sat_plan_rejected(monkeypatch):
    from backend.planner import service
    state, infra = fixture(2, 1)
    def invalid(ctx):
        rows, _, _ = service._fifo(ctx)
        for row in rows:
            row.update(start=0, end=100)
        return rows, "FEASIBLE", 1.0
    monkeypatch.setattr(service, "_cp_sat", invalid)
    plan = build_cp_sat_plan(state, infrastructure=infra)
    assert not plan.valid and not plan.resource_intervals
    assert "BLOCK_OVERLAP" in {v.type for v in plan.validation.violations}


def test_human_decision_server_validation():
    state, infra = fixture(1, 1)
    decision = dict(action="GRANT_ENTRY", train_id="SIM-0", resource_id="B0", snapshot_version=9, run_id="RUN-1", accepted=True)
    assert validate_human_decision(state, decision, infra).valid
    state["blocks"][0]["closed"] = True
    checked = validate_human_decision(state, decision, infra).to_dict()
    assert not checked["accepted"] and checked["reason_code"] == "BLOCK_CLOSED"


@pytest.mark.parametrize("change", [{"snapshot_version": 8}, {"run_id": "OLD"}])
def test_stale_snapshot_contract(change):
    state, infra = fixture(1, 1)
    decision = dict(action="HOLD_TRAIN", train_id="SIM-0", snapshot_version=9, run_id="RUN-1") | change
    assert validate_human_decision(state, decision, infra).to_dict()["reason_code"] == "STALE_SNAPSHOT"


def test_unknown_station_occupancy_not_free():
    state, infra = fixture(1, 2, dwell=60)
    state["station_tracks"][0].update(available=None, occupancy_source="UNAVAILABLE")
    plan = build_fifo_plan(state, infrastructure=infra)
    assert plan.valid and not plan.fully_validated and not plan.eligible_for_application
    assert "STATION_TRACK_OCCUPANCY" in plan.validation.unverified_scope
    decision = dict(action="SELECT_STATION_TRACK", train_id="SIM-0", resource_id="S-T1", snapshot_version=9, run_id="RUN-1")
    assert not validate_human_decision(state, decision, infra).valid


def speed_fixture():
    state, infra = fixture(1, 1)
    state["active_incidents"] = [dict(type="BLOCK_CLOSURE", incident_id="I", block_id="B0", at=iso(), duration_min=10)]
    plan = build_fifo_plan(state, infrastructure=infra)
    assert plan.fully_validated
    return state, infra, plan


def advice_for(distance=7, **kwargs):
    state, infra, plan = speed_fixture()
    return build_speed_advice(state, "SIM-0", plan, target_resource_id="B0",
        distance_to_control_point_km=distance, segment_speed_limit_kmh=80, infrastructure=infra, **kwargs)


def test_speed_advice_respects_speed_limit():
    assert 0 < advice_for().recommended_speed_kmh <= 80
    assert advice_for(distance=20).reason_code == "TARGET_UNREACHABLE"


def test_speed_advice_target_time():
    advice = advice_for()
    assert advice.target_arrival_time == iso(600)
    assert advice.recommended_speed_kmh == pytest.approx(42)
    assert 7 / advice.recommended_speed_kmh * 3600 == pytest.approx(600)


def test_full_stop_avoided_computed_not_hardcoded():
    assert advice_for().full_stop_avoided is True
    assert advice_for(distance=.1).full_stop_avoided is False
    assert advice_for(current_speed_kmh=42).full_stop_avoided is False


def test_energy_proxy_deterministic():
    a, b = advice_for(), advice_for()
    assert a.energy_proxy_basis == b.energy_proxy_basis
    assert a.energy_proxy_units_before == energy_proxy(**a.energy_proxy_basis["before_components"])
    assert a.energy_proxy_delta == pytest.approx(a.energy_proxy_units_after - a.energy_proxy_units_before)


def test_energy_proxy_not_labeled_kwh():
    assert not any(key in {"kwh", "kWh", "liters", "CO2", "tenge"} for key in advice_for().to_dict())


def test_missing_target_time_not_invented():
    state, infra = fixture(1, 1)
    advice = build_speed_advice(state, "SIM-0", None, target_resource_id="B0", distance_to_control_point_km=7,
                               segment_speed_limit_kmh=80, infrastructure=infra)
    assert advice.reason_code == "TARGET_TIME_UNKNOWN" and advice.full_stop_avoided is None


def test_outside_horizon_train_preserved():
    state, infra = fixture(2, 1)
    state["trains"][1]["planned_start"] = iso(4000)
    plan = build_cp_sat_plan(state, infrastructure=infra)
    assert plan.valid and plan.deferred_train_ids == ["SIM-1"]
    assert plan.train_plans[1].status == "outside_horizon"


def test_waiting_train_does_not_vanish_at_horizon():
    state, infra = fixture(1, 2)
    moving(state, 0, .5)
    state["blocks"][1]["closed"] = True
    for builder in (build_fifo_plan, build_cp_sat_plan):
        plan = builder(state, infrastructure=infra)
        assert plan.valid, plan.validation
        assert plan.resource_intervals[-1].end_time == plan.planning_horizon_end
        assert plan.train_plans[0].final_arrival_time is None


def test_minimum_travel_time_rejected_independently():
    state, infra = fixture(1, 1)
    plan = build_fifo_plan(state, infrastructure=infra)
    bad = tamper(plan, 0, traversal_end_time=iso(1))
    assert "MINIMUM_TRAVEL_TIME" in {v.type for v in validate_plan(state, bad, infra).violations}


def test_route_order_and_missing_current_occupancy_rejected():
    state, infra = fixture(1, 2)
    moving(state, 0, .5)
    plan = build_fifo_plan(state, infrastructure=infra).to_dict()
    plan["resource_intervals"] = plan["resource_intervals"][1:]
    codes = {v.type for v in validate_plan(state, plan, infra).violations}
    assert "ROUTE_ORDER" in codes and "RESOURCE_RELEASE" in codes


def test_unknown_signal_never_gives_fully_validated_plan():
    state, infra = fixture(1, 1)
    state["signals"][0].update(aspect=None, failed=None)
    plan = build_fifo_plan(state, infrastructure=infra)
    assert plan.valid and not plan.fully_validated
    assert "SIGNAL_STATE" in plan.validation.unverified_scope


def test_unexplained_red_signal_not_assumed_to_open():
    state, infra = fixture(1, 1)
    state["signals"][0]["aspect"] = "STOP"
    for builder in (build_fifo_plan, build_cp_sat_plan):
        plan = builder(state, infrastructure=infra)
        assert plan.valid and not plan.resource_intervals
        assert plan.train_plans[0].status == "deferred"


def test_existing_occupant_may_leave_closed_block():
    state, infra = fixture(1, 2)
    moving(state, 0, .5)
    state["blocks"][0]["closed"] = True
    plan = build_cp_sat_plan(state, infrastructure=infra)
    assert plan.valid and plan.resource_intervals[1].start_time == iso(50)


def test_human_cannot_skip_remaining_travel():
    state, infra = fixture(1, 2)
    moving(state, 0, .5)
    decision = dict(action="GRANT_ENTRY", train_id="SIM-0", resource_id="B1", snapshot_version=9, run_id="RUN-1")
    assert validate_human_decision(state, decision, infra).to_dict()["reason_code"] == "MINIMUM_TRAVEL_TIME"


def test_known_station_occupancy_uses_explicit_release():
    state, infra = fixture(1, 2, dwell=60)
    state["station_tracks"][0].update(occupied_train_ids=["OTHER-STATION-TRAIN"], available=False, release_time=iso(400))
    for builder in (build_fifo_plan, build_cp_sat_plan):
        plan = builder(state, infrastructure=infra)
        assert plan.valid, plan.validation
        assert plan.resource_intervals[1].start_time >= iso(400)
        assert plan.resource_intervals[0].end_time == plan.resource_intervals[1].start_time


def test_cp_sat_can_choose_available_station_track():
    state, infra = fixture(1, 2, dwell=60)
    infra["station_tracks"]["S-T2"] = dict(station_id="S", demo_capacity_trains=1)
    state["station_tracks"].append(dict(track_id="S-T2", station_id="S", capacity=1, occupied_train_ids=[], available=True, occupancy_source="SIMULATED"))
    state["station_tracks"][0]["available"] = False
    state["trains"][0]["station_stops"][0]["track_ids"] = ["S-T1", "S-T2"]
    plan = build_cp_sat_plan(state, infrastructure=infra)
    assert plan.valid and plan.train_plans[0].selected_station_tracks[0].track_id == "S-T2"


def test_stale_plan_speed_advice_rejected():
    state, infra, plan = speed_fixture()
    state["snapshot_version"] += 1
    advice = build_speed_advice(state, "SIM-0", plan, target_resource_id="B0", distance_to_control_point_km=7,
                               segment_speed_limit_kmh=80, infrastructure=infra)
    assert advice.reason_code == "PLAN_UNVERIFIED" and advice.full_stop_avoided is None


def test_fork_schedule_does_not_release_terminal_hold():
    from backend.planner.apply import prepare_fork_schedule
    state, infra = fixture(1, 2)
    moving(state, 0, .5)
    state["blocks"][1]["closed"] = True
    plan = build_fifo_plan(state, infrastructure=infra)
    result = prepare_fork_schedule(state, plan, infrastructure=infra)
    assert result["transitions"] == []
    assert result["terminal_holds"][0]["resource_id"] == "B0"


def test_fork_rejects_unverified_plan():
    from backend.planner.apply import prepare_fork_schedule
    state, infra = fixture(1, 2, dwell=60)
    state["station_tracks"][0].update(available=None, occupancy_source="UNAVAILABLE")
    plan = build_fifo_plan(state, infrastructure=infra)
    with pytest.raises(ValueError, match="FORK_PLAN_UNVERIFIED"):
        prepare_fork_schedule(state, plan, infrastructure=infra)


def test_existing_limit_only_profile_unchanged_without_plan():
    from backend.simulator import Simulator
    from backend.speed_profile.profile import build_speed_profile
    from backend.speed_profile.advisory import build_speed_profile_with_plan
    snapshot = Simulator("SCN-ALL").snapshot().to_dict()
    tid = snapshot["trains"][0]["train_id"]
    assert build_speed_profile_with_plan(snapshot, tid) == build_speed_profile(snapshot, tid)


def test_cp_sat_actual_budget_timeout_is_safe():
    state, infra = fixture(28, 5)
    plan = build_cp_sat_plan(state, config=PlanningConfig(time_limit_seconds=.000001), infrastructure=infra)
    assert plan.solver_status == "TIMEOUT"
    assert not plan.valid and not plan.eligible_for_application and not plan.resource_intervals


def test_all_28_trains_are_considered_with_small_variable_horizon():
    state, infra = fixture(28, 40)
    plan = build_fifo_plan(state, config=PlanningConfig(horizon_seconds=600), infrastructure=infra)
    assert plan.valid and len(plan.considered_train_ids) == 28
    assert all(r.route_index < 6 for r in plan.resource_intervals)
    assert len(plan.train_plans) == 28


def test_red_signal_is_not_explained_by_same_direction_other_block():
    state, infra = fixture(1, 2)
    moving(state, 0, .5)
    state["signals"][1]["aspect"] = "STOP"
    for builder in (build_fifo_plan, build_cp_sat_plan):
        plan = builder(state, infrastructure=infra)
        assert plan.valid
        assert all(r.resource_id != "B1" for r in plan.resource_intervals)


def test_human_cannot_use_locked_switch_route():
    state, infra = fixture(1, 1)
    state["switches"] = [dict(switch_id="SW", failed=False, locked=True, position="T2", available_routes=["S-T1", "S-T2"])]
    state["trains"][0].update(entry_switches=["SW"], required_tracks=["S-T1"])
    action = dict(action="GRANT_ENTRY", train_id="SIM-0", snapshot_version=9, run_id="RUN-1")
    assert validate_human_decision(state, action, infra).to_dict()["reason_code"] == "SWITCH_ROUTE_UNAVAILABLE"


@pytest.mark.parametrize("kind", ["BLOCK_CLOSURE", "SIGNAL_FAILURE"])
def test_future_incident_does_not_explain_current_unavailability(kind):
    state, infra = fixture(1, 1)
    event = dict(incident_id="FUTURE", type=kind, at=iso(900), duration_min=5)
    if kind == "BLOCK_CLOSURE":
        state["blocks"][0]["closed"] = True
        event["block_id"] = "B0"
    else:
        state["signals"][0].update(aspect="STOP", failed=True)
        event["signal_id"] = "SIG0"
    state["planned_incidents"] = [event]
    for builder in (build_fifo_plan, build_cp_sat_plan):
        plan = builder(state, infrastructure=infra)
        assert plan.valid and not plan.resource_intervals
