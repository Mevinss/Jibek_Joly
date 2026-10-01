"""Fetch OSM station coordinates once; retain sourced approximate coordinates if offline."""
from __future__ import annotations

import argparse
import json
import math
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/kz_demo/map/station_coords.json"
WEB = ROOT / "services/ai/web/assets/map/station_coords.json"
OVERPASS = "https://overpass.kumi.systems/api/interpreter"
ANCHORS = {
    "KOK": (69.424, 53.304), "BOR": (70.191, 52.936),
    "AKK": (70.962, 51.993), "AST": (71.434, 51.184),
    "KAR": (73.095, 49.892), "AKD": (72.860, 48.266),
    "SAR": (73.596, 46.117), "SHU": (73.751, 43.594),
    "ALM": (76.912, 43.347),
}
ALIASES = {
    "KOK": ("көкшетау", "кокшетау", "kokshetau"),
    "BOR": ("курорт-бурабай", "курорт бурабай", "kurort-burabay", "burabay"),
    "AKK": ("ақкөл", "акколь", "akkol"),
    "AST": ("астана-1", "астана 1", "astana-1"),
    "KAR": ("қарағанды", "караганда", "karaganda"),
    "AKD": ("ақадыр", "акадыр", "akadir"),
    "SAR": ("сарышаған", "сарышаган", "saryshagan"),
    "SHU": ("шу", "shu", "chu"),
    "ALM": ("алматы-2", "алматы 2", "almaty-2"),
}


def distance_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lat2 = math.radians(a[1]), math.radians(b[1])
    dlat, dlon = lat2 - lat1, math.radians(b[0] - a[0])
    q = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371.0088 * 2 * math.asin(min(1, math.sqrt(q)))


def query_station(lon: float, lat: float) -> list[dict]:
    query = f'[out:json][timeout:35];nwr(around:15000,{lat},{lon})["railway"~"^(station|halt)$"];out center tags;'
    request = urllib.request.Request(
        OVERPASS,
        data=urllib.parse.urlencode({"data": query}).encode(),
        headers={"User-Agent": "JibekJoly-stage1-map/1.0 (hackathon demo)", "Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(request, timeout=50) as response:
        return json.load(response)["elements"]


def choose(station_id: str, elements: list[dict], anchor: tuple[float, float]) -> tuple[dict | None, int]:
    aliases = ALIASES[station_id]
    found = []
    for element in elements:
        tags = element.get("tags", {})
        names = [str(value).casefold().replace("ё", "е") for key, value in tags.items() if key == "name" or key.startswith("name:")]
        if not any(any(alias in name for alias in aliases) for name in names):
            continue
        center = element.get("center", element)
        if "lon" not in center or "lat" not in center:
            continue
        coord = (center["lon"], center["lat"])
        if distance_km(anchor, coord) <= 15:
            found.append((element, coord))
    unique = {(entry[0]["type"], entry[0]["id"]): entry for entry in found}
    return (next(iter(unique.values())) if len(unique) == 1 else None), len(unique)


def build(offline: bool = False, delay: float = 2.0) -> list[dict]:
    fallback = {row["id"]: row for row in json.loads((ROOT / "services/ai/demo/corridor.json").read_text(encoding="utf-8"))["stations"]}
    rows = []
    for station_id, anchor in ANCHORS.items():
        station = fallback[station_id]
        chosen, count = None, 0
        if not offline:
            try:
                chosen, count = choose(station_id, query_station(*anchor), anchor)
            except (OSError, ValueError, KeyError, TimeoutError):
                pass
            time.sleep(delay)
        if chosen:
            element, coord = chosen
            rows.append(dict(station_id=station_id, lon=coord[0], lat=coord[1], osm_id=f'{element["type"]}/{element["id"]}',
                             osm_name=element.get("tags", {}).get("name"), distance_to_anchor_km=round(distance_km(anchor, coord), 3),
                             confidence="name_and_radius", approximate=False, source="OpenStreetMap/Overpass"))
        else:
            coord = station["coordinates"]
            rows.append(dict(station_id=station_id, lon=coord[0], lat=coord[1], osm_id=None, osm_name=None,
                             distance_to_anchor_km=round(distance_km(anchor, coord), 3),
                             confidence="ambiguous" if count > 1 else "unverified", approximate=True,
                             source="existing Railwayz.info-derived generalized geometry"))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--delay", type=float, default=2.0)
    args = parser.parse_args()
    rows = build(args.offline, args.delay)
    text = json.dumps(rows, ensure_ascii=False, indent=2) + "\n"
    for path in (OUT, WEB):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    print(f"{len(rows)} stations; {sum(row['approximate'] for row in rows)} approximate")


if __name__ == "__main__":
    main()
