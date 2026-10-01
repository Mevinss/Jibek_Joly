"""Stage-one static map and mock fixture checks."""
import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from build_frontend_mock import build  # noqa: E402


class MapDataTests(unittest.TestCase):
    def test_nine_stations_have_sourced_or_approximate_coordinates(self):
        rows = json.loads((ROOT / "data/kz_demo/map/station_coords.json").read_text(encoding="utf-8"))
        self.assertEqual(len(rows), 9)
        self.assertEqual(len({row["station_id"] for row in rows}), 9)
        for row in rows:
            self.assertTrue(-180 <= row["lon"] <= 180 and -90 <= row["lat"] <= 90)
            self.assertTrue(row["approximate"] or row["osm_id"])

    def test_eight_routes_are_continuous_and_block_boundaries_ordered(self):
        routes = json.loads((ROOT / "data/kz_demo/map/route_geometry.json").read_text(encoding="utf-8"))
        self.assertEqual(len(routes), 8)
        for route in routes:
            self.assertGreaterEqual(len(route["polyline"]), 2)
            self.assertEqual(route["geometry_quality"] in {"osm_rail", "generalized"}, True)
            self.assertAlmostEqual(route["blocks"][0]["start_fraction"], 0)
            self.assertAlmostEqual(route["blocks"][-1]["end_fraction"], 1)
            for left, right in zip(route["blocks"], route["blocks"][1:]):
                self.assertAlmostEqual(left["end_fraction"], right["start_fraction"])
                self.assertEqual(left["end_coord"], right["start_coord"])

    def test_mock_build_is_deterministic(self):
        encoded = [json.dumps(build(), ensure_ascii=False, sort_keys=True).encode("utf-8") for _ in range(2)]
        self.assertEqual(hashlib.sha256(encoded[0]).digest(), hashlib.sha256(encoded[1]).digest())

    def test_every_mock_record_marks_source(self):
        data = build()
        self.assertEqual(data["source"], "MOCK")
        for key in ("stations", "segments", "blocks", "station_tracks", "switches", "signals",
                    "train_parameters", "incidents", "scenarios"):
            self.assertTrue(all(row["source"] == "MOCK" for row in data[key]), key)
        for profiles in data["profiles"].values():
            self.assertEqual(len(profiles), 28)
            for train in profiles:
                self.assertEqual(train["source"], "MOCK")
                self.assertTrue(all(stop["source"] == "MOCK" for stop in train["stops"]))

    def test_named_incidents_only_delay_affected_services(self):
        data = build()
        first = data["profiles"]["SCN-01"]
        affected = [train for train in first if any(stop["delay_min"] for stop in train["stops"])]
        self.assertEqual([train["train_id"] for train in affected], ["SIM-KOK_AST-F03"])
        self.assertEqual(max(stop["delay_min"] for stop in affected[0]["stops"]), 22)
        signal = data["profiles"]["SCN-02"]
        self.assertTrue(any("INC-02" in stop["cause_ids"] for train in signal for stop in train["stops"]))


if __name__ == "__main__":
    unittest.main()
