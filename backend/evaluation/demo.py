"""Reproducible scoped examples: actual engine runs on a synthetic short route.

Not a 28-train network evaluation. Stations are excluded because these journeys
terminate at BOR after all three KOK–BOR blocks; no station dwell is modelled
and no unknown station occupancy is made 'free'.
"""
from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path

from backend.analytics.service import build_analytics, quality_index
from backend.analytics.what_if import what_if
from backend.connections.service import cascade_delay, load_demo_graph, analyze_connection
from backend.eta.service import get_train_eta, get_station_arrivals
from backend.planner.context import timestamp
from backend.planner.models import PlanningConfig
from backend.planner.service import build_fifo_plan
from backend.simulator.engine import Simulator
from backend.simulator.state_contract import canonical_from_backend_snapshot
from .service import compare_policies


def short_route_demo(count=3):
    snapshot = canonical_from_backend_snapshot(Simulator().snapshot().to_dict(), run_id="PERSON3-SHORT-DEMO")
    snapshot["seed"] = 20261001
    snapshot["dataset_version"] = "person3-short-route-synthetic-v1:" + snapshot["dataset_version"]
    snapshot["trains"] = deepcopy(snapshot["trains"][:count])
    snapshot["station_tracks"] = []
    snapshot["active_incidents"] = []
    snapshot["planned_incidents"] = []
    for train in snapshot["trains"]:
        for key in ("route", "block_seconds", "entry_signals", "entry_switches", "required_tracks"):
            train[key] = train[key][:3]
        train["block_seconds"] = [60, 60, 60]
        train["planned_start"] = snapshot["virtual_time"]
        train["scheduled_final_arrival"] = (timestamp(snapshot["virtual_time"]) + timedelta(seconds=180)).isoformat()
        train["scheduled_arrival"] = train["scheduled_final_arrival"]
        train["next_station_id"] = train["destination_station_id"] = "BOR"
        train["station_stops"] = []
        train["speed_kmh"] = None
    return snapshot


def export_examples():
    snapshot = short_route_demo()
    config = PlanningConfig(horizon_seconds=600, time_limit_seconds=1, category_weights={"intercity": 3, "regional": 2, "freight": 1})
    compare = compare_policies(snapshot, config=config)
    plan = build_fifo_plan(snapshot, config=config)
    graph = load_demo_graph()
    cascade = cascade_delay(graph, "SIM-DEMO-A", 5)
    examples = dict(compare=compare.to_dict(), station_arrivals=get_station_arrivals(snapshot, "BOR", plan).to_dict(),
        train_eta=get_train_eta(snapshot, snapshot["trains"][0]["train_id"], "BOR", plan).to_dict(),
        cascade=cascade.to_dict(), quality_index=quality_index(compare.fifo).to_dict(),
        what_if=what_if(snapshot, "EXTRA_DELAY", snapshot["trains"][0]["train_id"], 2, config=config).to_dict(),
        analytics=build_analytics(compare.fifo), connection_decision=analyze_connection(graph, 0, 5),
        initial_snapshot=snapshot)
    target = Path(__file__).resolve().parents[2] / "docs/examples"
    target.mkdir(exist_ok=True)
    for name, value in examples.items():
        (target / f"person3_{name}.json").write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return compare


if __name__ == "__main__":
    result = export_examples()
    print(result.status)
    print({"fifo_status": result.fifo.status, "cp_sat_status": result.cp_sat.status,
           "fifo_reason": result.fifo.termination_reason, "cp_sat_reason": result.cp_sat.termination_reason})
