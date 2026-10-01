"""Build eight station-to-station rail polylines from OSM, with explicit fallback."""
from __future__ import annotations

import argparse
import csv
import heapq
import json
import math
import urllib.parse
import urllib.request
from pathlib import Path

from fetch_station_coords import ROOT, distance_km

OUT = ROOT / "data/kz_demo/map/route_geometry.json"
WEB = ROOT / "services/ai/web/assets/map/route_geometry.json"
OVERPASS = "https://overpass.kumi.systems/api/interpreter"


def rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def overpass_ways(a: list[float], b: list[float]) -> list[dict]:
    south, north = min(a[1], b[1]) - .16, max(a[1], b[1]) + .16
    west, east = min(a[0], b[0]) - .16, max(a[0], b[0]) + .16
    query = (f'[out:json][timeout:35];way["railway"="rail"]({south},{west},{north},{east})'
             '["service"!~"^(siding|yard|spur|crossover)$"];out geom;')
    request = urllib.request.Request(OVERPASS, data=urllib.parse.urlencode({"data": query}).encode(),
                                     headers={"User-Agent": "JibekJoly-stage1-map/1.0 (hackathon demo)",
                                              "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(request, timeout=45) as response:
        return json.load(response)["elements"]


def osm_path(ways: list[dict], a: list[float], b: list[float]) -> list[list[float]] | None:
    nodes: dict[int, list[float]] = {}
    edges: dict[int, list[tuple[int, float]]] = {}
    for way in ways:
        ids, geometry = way.get("nodes", []), way.get("geometry", [])
        if len(ids) != len(geometry):
            continue
        for node_id, point in zip(ids, geometry):
            nodes[node_id] = [point["lon"], point["lat"]]
        for left, right in zip(ids, ids[1:]):
            weight = distance_km(tuple(nodes[left]), tuple(nodes[right]))
            edges.setdefault(left, []).append((right, weight))
            edges.setdefault(right, []).append((left, weight))
    if not nodes:
        return None
    start = min(nodes, key=lambda key: distance_km(tuple(nodes[key]), tuple(a)))
    end = min(nodes, key=lambda key: distance_km(tuple(nodes[key]), tuple(b)))
    if max(distance_km(tuple(nodes[start]), tuple(a)), distance_km(tuple(nodes[end]), tuple(b))) > 5:
        return None
    queue = [(0.0, start)]
    costs = {start: 0.0}
    previous: dict[int, int] = {}
    while queue:
        cost, here = heapq.heappop(queue)
        if here == end:
            break
        if cost > costs[here]:
            continue
        for there, weight in edges.get(here, []):
            candidate = cost + weight
            if candidate < costs.get(there, math.inf):
                costs[there] = candidate
                previous[there] = here
                heapq.heappush(queue, (candidate, there))
    if end not in costs:
        return None
    path = [end]
    while path[-1] != start:
        path.append(previous[path[-1]])
    return [nodes[node_id] for node_id in reversed(path)]


def simplify(points: list[list[float]], tolerance_km: float = .02) -> list[list[float]]:
    if len(points) < 3:
        return points
    a, b = points[0], points[-1]
    lat_scale = math.cos(math.radians((a[1] + b[1]) / 2))
    ax, ay = a[0] * lat_scale, a[1]
    bx, by = b[0] * lat_scale, b[1]
    span = (bx - ax) ** 2 + (by - ay) ** 2
    def error(point: list[float]) -> float:
        px, py = point[0] * lat_scale, point[1]
        t = max(0, min(1, ((px - ax) * (bx - ax) + (py - ay) * (by - ay)) / span)) if span else 0
        return math.hypot(px - ax - t * (bx - ax), py - ay - t * (by - ay)) * 111.2
    index = max(range(1, len(points) - 1), key=lambda i: error(points[i]))
    if error(points[index]) <= tolerance_km:
        return [a, b]
    return simplify(points[:index + 1], tolerance_km)[:-1] + simplify(points[index:], tolerance_km)


def interpolate(points: list[list[float]], fraction: float) -> list[float]:
    lengths = [distance_km(tuple(a), tuple(b)) for a, b in zip(points, points[1:])]
    remaining = sum(lengths) * fraction
    for i, length in enumerate(lengths):
        if remaining <= length or i == len(lengths) - 1:
            ratio = remaining / length if length else 0
            return [points[i][0] + ratio * (points[i + 1][0] - points[i][0]),
                    points[i][1] + ratio * (points[i + 1][1] - points[i][1])]
        remaining -= length
    return points[-1]


def build(offline: bool = False) -> list[dict]:
    stations = {row["station_id"]: row for row in json.loads((ROOT / "data/kz_demo/map/station_coords.json").read_text(encoding="utf-8"))}
    source = json.loads((ROOT / "services/ai/demo/corridor.json").read_text(encoding="utf-8"))
    blocks = rows(ROOT / "data/kz_demo/KZ/blocks.csv")
    result = []
    for segment in rows(ROOT / "data/kz_demo/KZ/segments.csv"):
        segment_id = segment["segment_id"]
        fallback = [feature for feature in source["features"] if feature["properties"]["segment_id"] == segment_id]
        fallback.sort(key=lambda feature: feature["properties"]["start_km"])
        generalized = [fallback[0]["geometry"]["coordinates"][0]] + [feature["geometry"]["coordinates"][-1] for feature in fallback]
        a = stations[segment["from_station_id"]]
        b = stations[segment["to_station_id"]]
        line = None
        if not offline:
            try:
                line = osm_path(overpass_ways([a["lon"], a["lat"]], [b["lon"], b["lat"]]),
                                [a["lon"], a["lat"]], [b["lon"], b["lat"]])
            except (OSError, ValueError, KeyError, TimeoutError):
                pass
        quality = "osm_rail" if line else "generalized"
        line = simplify(line) if line else generalized
        segment_blocks = sorted((row for row in blocks if row["segment_id"] == segment_id), key=lambda row: int(row["block_order"]))
        total_demo = sum(float(row["demo_length_km"]) for row in segment_blocks)
        cumulative = 0.0
        boundaries = []
        for block in segment_blocks:
            start = cumulative / total_demo
            cumulative += float(block["demo_length_km"])
            end = cumulative / total_demo
            boundaries.append(dict(block_id=block["block_id"], start_fraction=start, end_fraction=end,
                                   start_coord=interpolate(line, start), end_coord=interpolate(line, end), source="MOCK"))
        length = round(sum(distance_km(tuple(x), tuple(y)) for x, y in zip(line, line[1:])), 3) if quality == "osm_rail" else None
        result.append(dict(segment_id=segment_id, from_station_id=segment["from_station_id"], to_station_id=segment["to_station_id"],
                           polyline=line, real_length_km=length, demo_distance_km=float(segment["demo_distance_km"]),
                           blocks=boundaries, geometry_quality=quality,
                           source="OpenStreetMap contributors" if quality == "osm_rail" else "existing generalized geometry"))
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    data = build(args.offline)
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    for path in (OUT, WEB):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    print(f"{len(data)} segments; {sum(row['geometry_quality'] == 'osm_rail' for row in data)} OSM rail")


if __name__ == "__main__":
    main()
