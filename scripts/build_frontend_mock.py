"""Build deterministic, visibly synthetic station-board data for the stage-one UI."""
from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "services/ai/web/assets/mock/dataset.json"


def table(path: str) -> list[dict]:
    with (ROOT / path).open(encoding="utf-8-sig", newline="") as stream:
        return [{**row, "source": "MOCK"} for row in csv.DictReader(stream)]


def records(path: str) -> list[dict]:
    return [{**row, "source": "MOCK"} for row in json.loads((ROOT / path).read_text(encoding="utf-8"))]


def when(value: str) -> datetime:
    return datetime.fromisoformat(value)


def overlap_minutes(start: datetime, end: datetime, incident: dict) -> float:
    active_start = when(incident["at"])
    active_end = active_start + timedelta(minutes=incident["duration_min"])
    return max(0, (min(end, active_end) - max(start, active_start)).total_seconds() / 60)


def affected_segment(incident: dict, left: str, right: str) -> bool:
    pair = {left, right}
    if incident["type"] == "SIGNAL_FAILURE":
        return pair == {"BOR", "AKK"}
    if incident["type"] == "BLOCK_CLOSURE":
        return pair == {"KAR", "AKD"}
    if incident["type"] == "SWITCH_FAILURE":
        return right == "AST" or left == "AST"
    return False


def timeline(stops: list[dict], incidents: list[dict], train_id: str) -> list[dict]:
    delay = 0.0
    causes: set[str] = set()
    result = []
    previous = None
    for stop in stops:
        arrival = when(stop["scheduled_arrival"]) if stop["scheduled_arrival"] else None
        departure = when(stop["scheduled_departure"]) if stop["scheduled_departure"] else None
        if previous and arrival:
            previous_departure = when(previous["scheduled_departure"])
            for incident in incidents:
                if affected_segment(incident, previous["station_id"], stop["station_id"]):
                    held = overlap_minutes(previous_departure + timedelta(minutes=delay), arrival + timedelta(minutes=delay), incident)
                    delay += held
                    if held:
                        causes.add(incident["incident_id"])
        for incident in incidents:
            if incident["type"] == "TRAIN_DELAY" and incident.get("train_id") == train_id:
                event_at = arrival or departure
                if event_at and event_at >= when(incident["at"]) and not any(row.get("applied_incident") == incident["incident_id"] for row in result):
                    delay += incident["duration_min"]
                    causes.add(incident["incident_id"])
                    applied = incident["incident_id"]
                    break
        else:
            applied = None
        result.append(dict(station_id=stop["station_id"], stop_order=int(stop["stop_order"]),
                           scheduled_arrival=stop["scheduled_arrival"] or None,
                           scheduled_departure=stop["scheduled_departure"] or None,
                           expected_arrival=(arrival + timedelta(minutes=delay)).isoformat() if arrival else None,
                           expected_departure=(departure + timedelta(minutes=delay)).isoformat() if departure else None,
                           delay_min=round(delay, 3), cause_ids=sorted(causes), applied_incident=applied, source="MOCK"))
        previous = stop
    return result


def build() -> dict:
    stations = table("data/kz_demo/KZ/stations.csv")
    segments = table("data/kz_demo/KZ/segments.csv")
    blocks = table("data/kz_demo/KZ/blocks.csv")
    tracks = table("data/kz_demo/KZ/station_tracks.csv")
    switches = table("data/kz_demo/mock/switches.csv")
    signals = table("data/kz_demo/mock/signals.csv")
    parameters = table("data/kz_demo/mock/train_parameters.csv")
    trains = table("data/kz_demo/KZ/train_services.csv")
    stops = table("data/kz_demo/KZ/run_stops.csv")
    incidents = records("data/kz_demo/scenarios/incidents.json")
    scenarios = records("data/kz_demo/scenarios/scenarios.json")
    by_train: dict[str, list[dict]] = {}
    for stop in stops:
        by_train.setdefault(stop["train_id"], []).append(stop)
    for rows in by_train.values():
        rows.sort(key=lambda row: int(row["stop_order"]))
    profiles = {}
    for scenario in scenarios:
        active = [row for row in incidents if row["incident_id"] in scenario["incident_ids"]]
        profiles[scenario["scenario_id"]] = [dict(train_id=train["train_id"], scenario_seed=scenario["seed"], category=train["category"],
            direction=train["direction"], origin_station_id=train["origin_station_id"],
            destination_station_id=train["destination_station_id"], stops=timeline(by_train[train["train_id"]], active, train["train_id"]),
            source="MOCK") for train in trains]
    return dict(source="MOCK", schedule_source="SYNTHETIC_SCHEDULE", timezone="+05:00",
                stations=stations, segments=segments, blocks=blocks, station_tracks=tracks,
                switches=switches, signals=signals, train_parameters=parameters,
                incidents=incidents, scenarios=scenarios, profiles=profiles)


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(build(), ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
