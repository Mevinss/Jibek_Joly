"""Bounded analytical delay propagation, not an alternative dispatch planner."""
from dataclasses import dataclass, field
import json
import math
from pathlib import Path

from backend.evaluation.models import JsonContract
from backend.planner.context import timestamp


@dataclass(frozen=True)
class ConnectionEdge(JsonContract):
    from_train_id: str
    to_train_id: str
    station_id: str
    minimum_transfer_min: float
    scheduled_arrival_from: str
    scheduled_departure_to: str
    connection_type: str = "CONNECTION_WAIT"
    passenger_weight_proxy: float | None = None
    resource_id: str | None = None

    def __post_init__(self):
        if not math.isfinite(self.minimum_transfer_min) or self.minimum_transfer_min < 0:
            raise ValueError("minimum_transfer_min must be finite and nonnegative")
        if self.slack_min < 0:
            raise ValueError("baseline connection is infeasible; supply a feasible baseline schedule")
        if self.passenger_weight_proxy is not None and (not math.isfinite(self.passenger_weight_proxy) or self.passenger_weight_proxy < 0):
            raise ValueError("invalid passenger proxy")

    @property
    def slack_min(self):
        return (timestamp(self.scheduled_departure_to) - timestamp(self.scheduled_arrival_from)).total_seconds() / 60 - self.minimum_transfer_min


@dataclass
class ConnectionGraph(JsonContract):
    edges: list[ConnectionEdge]
    source_type: str = "SYNTHETIC_DEMO"
    description: str = "Assumes each listed connection waits. No passenger counts; no operational claim."


@dataclass
class CascadingDelayResult(JsonContract):
    root_train_id: str
    root_delay_min: float
    affected_trains: list[dict]
    network_added_delay_min: float
    chain: list[dict]
    max_depth: int
    horizon_min: float
    cycle_detected: bool = False
    truncated: bool = False
    source_type: str = "SYNTHETIC_DEMO"
    method: str = "BOUNDED_SCHEDULE_SLACK_PROPAGATION"
    initial_snapshot_hash: str | None = None
    assumptions: list[str] = field(default_factory=lambda: [
        "Delay at a dependency consumes its baseline slack; excess delays its successor.",
        "At joins take the largest required delay, never sum the same train twice.",
        "Network total includes root once. This is an analytical estimate, not a completed run."])


def load_demo_graph():
    data = json.loads((Path(__file__).parent / "fixtures/kz_connections.json").read_text(encoding="utf-8"))
    return ConnectionGraph([ConnectionEdge(**e) for e in data["edges"]], data["source_type"], data["description"])


def resource_dependencies(snapshot, plan, *, infrastructure=None):
    """Capacity-one reservation successors only; independently validate the plan."""
    from backend.validator.resources import validate_plan
    checked = validate_plan(snapshot, plan, infrastructure)
    if not checked.valid:
        raise ValueError("INVALID_OR_STALE_PLAN")
    data = plan.to_dict() if hasattr(plan, "to_dict") else plan
    resources = {("block", b["block_id"]): b["capacity"] for b in snapshot["blocks"]}
    resources.update({("station_track", t.get("track_id", t.get("station_track_id"))): t.get("capacity", 1) for t in snapshot["station_tracks"]})
    groups, edges = {}, []
    for row in data["resource_intervals"]:
        key = row["resource_type"], row["resource_id"]
        if resources.get(key) == 1:
            groups.setdefault(key, []).append(row)
    headway = data["config"]["headway_seconds"] / 60
    for (kind, rid), rows in sorted(groups.items()):
        rows.sort(key=lambda r: (timestamp(r["start_time"]), r["train_id"]))
        for a, b in zip(rows, rows[1:]):
            if a["train_id"] != b["train_id"]:
                edges.append(ConnectionEdge(a["train_id"], b["train_id"], "RESOURCE_DEPENDENCY",
                    headway, a["end_time"], b["start_time"], "BLOCK_RELEASE" if kind == "block" else "TRACK_RELEASE", resource_id=rid))
    return edges


def cascade_delay(graph: ConnectionGraph, root_train_id, root_delay_min, *, virtual_time=None, max_depth=4, horizon_min=60):
    if type(max_depth) is not int or not 1 <= max_depth <= 10:
        raise ValueError("max_depth must be in [1, 10]")
    if not math.isfinite(horizon_min) or not 0 < horizon_min <= 120:
        raise ValueError("horizon_min must be in (0, 120]")
    if not math.isfinite(root_delay_min) or root_delay_min < 0:
        raise ValueError("root_delay_min must be finite and nonnegative")
    edges = sorted(graph.edges, key=lambda e: (timestamp(e.scheduled_departure_to), e.from_train_id, e.to_train_id, e.connection_type))
    if virtual_time is None:
        outgoing = [timestamp(e.scheduled_arrival_from) for e in edges if e.from_train_id == root_train_id]
        start = min(outgoing) if outgoing else None
    else:
        start = timestamp(virtual_time)
    delays, paths, depths, causes = {root_train_id: root_delay_min}, {root_train_id: (root_train_id,)}, {root_train_id: 0}, {}
    cycles, truncated = False, False
    # Synchronous bounded relaxations: O(max_depth * edge_count), no path explosion.
    for _ in range(max_depth):
        new_delays, new_paths, new_depths, new_causes = dict(delays), dict(paths), dict(depths), dict(causes)
        changed = False
        for edge in edges:
            if edge.from_train_id not in delays:
                continue
            if edge.to_train_id in paths[edge.from_train_id]:
                cycles = True
                continue
            depth = depths[edge.from_train_id] + 1
            departure = timestamp(edge.scheduled_departure_to)
            if depth > max_depth or (start and not 0 <= (departure - start).total_seconds() / 60 <= horizon_min):
                truncated = True
                continue
            needed = max(0, delays[edge.from_train_id] - edge.slack_min)
            if needed > new_delays.get(edge.to_train_id, 0):
                new_delays[edge.to_train_id] = needed
                new_paths[edge.to_train_id] = paths[edge.from_train_id] + (edge.to_train_id,)
                new_depths[edge.to_train_id] = depth
                new_causes[edge.to_train_id] = dict(from_train_id=edge.from_train_id, to_train_id=edge.to_train_id,
                    station_id=edge.station_id, resource_id=edge.resource_id, cause=edge.connection_type,
                    slack_min=edge.slack_min, added_delay_min=needed, depth=depth)
                changed = True
        delays, paths, depths, causes = new_delays, new_paths, new_depths, new_causes
        if not changed:
            break
    if any(depths.get(e.from_train_id) == max_depth and e.to_train_id not in paths[e.from_train_id]
           and delays[e.from_train_id] > e.slack_min for e in edges if e.from_train_id in depths):
        truncated = True
    affected = [dict(train_id=tid, added_delay_min=delay, cause=causes[tid]["cause"], depth=depths[tid])
                for tid, delay in sorted(delays.items()) if tid != root_train_id]
    chain = sorted(causes.values(), key=lambda c: (c["depth"], c["to_train_id"]))
    return CascadingDelayResult(root_train_id, root_delay_min, affected, sum(delays.values()), chain,
        max_depth, horizon_min, cycles, truncated, graph.source_type)


def analyze_connection(graph, edge_index, incoming_delay_min, **cascade_config):
    edge = graph.edges[edge_index]
    wait = max(0, incoming_delay_min - edge.slack_min)
    waiting = cascade_delay(graph, edge.from_train_id, incoming_delay_min, **cascade_config)
    leaving_graph = ConnectionGraph([e for i, e in enumerate(graph.edges) if i != edge_index], graph.source_type, graph.description)
    leaving = cascade_delay(leaving_graph, edge.from_train_id, incoming_delay_min, **cascade_config)
    def option(result, direct, protected):
        return dict(direct_wait_min=direct, protected_connection=protected,
            downstream_train_count=len(result.affected_trains), network_added_delay_min=result.network_added_delay_min,
            cascade=result.to_dict())
    return dict(source_type=graph.source_type, method="ANALYTICAL_WHAT_IF", passenger_count=None,
        wait=option(waiting, wait, True), depart_on_time=option(leaving, 0, wait == 0))


def cascade_from_snapshot(snapshot, graph, root_train_id, root_delay_min, *, plan=None, infrastructure=None, **config):
    """Bind an explicitly supplied graph to this snapshot; never load demo fixtures."""
    from backend.evaluation.service import digest
    ids = {t["train_id"] for t in snapshot["trains"]}
    if root_train_id not in ids or any({e.from_train_id, e.to_train_id} - ids for e in graph.edges):
        raise ValueError("CONNECTION_TRAINS_NOT_IN_SNAPSHOT")
    edges = list(graph.edges)
    if plan is not None:
        edges += resource_dependencies(snapshot, plan, infrastructure=infrastructure)
    result = cascade_delay(ConnectionGraph(edges, graph.source_type, graph.description), root_train_id, root_delay_min,
        virtual_time=snapshot["virtual_time"], **config)
    result.initial_snapshot_hash = digest(snapshot)
    return result
