import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.process.flood_state import process_flood_state


class ProcessFloodStateTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.geojson_2022_path = Path(self.temp_dir.name) / "flood_2022.geojson"
        self.geojson_2025_path = Path(self.temp_dir.name) / "flood_2025.geojson"
        self._write_geojson(
            self.geojson_2022_path,
            flood_centers=(108.12, 108.16),
            dry_centers=(108.10, 108.14),
        )
        self._write_geojson(
            self.geojson_2025_path,
            flood_centers=(108.14, 108.16),
            dry_centers=(108.10, 108.12),
        )

    @staticmethod
    def _write_geojson(path, flood_centers, dry_centers):
        features = []
        for is_flood, centers in ((1, flood_centers), (0, dry_centers)):
            for center in centers:
                features.append(
                    {
                        "type": "Feature",
                        "properties": {"is_flood": is_flood},
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [
                                [
                                    [center, 16.00],
                                    [center + 0.005, 16.00],
                                    [center + 0.005, 16.01],
                                    [center, 16.01],
                                    [center, 16.00],
                                ]
                            ],
                        },
                    }
                )
        collection = {"type": "FeatureCollection", "features": features}
        path.write_text(json.dumps(collection), encoding="utf-8")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_assigns_safe_single_year_both_years_and_unknown_labels(self):
        frame = pd.DataFrame(
            {
                "latitude": [16.005, 16.005, 16.005, 16.005, 16.005, None, 16.005],
                "longitude": [108.102, 108.122, 108.142, 108.162, 108.182, 108.102, float("inf")],
            }
        )

        result = process_flood_state(
            frame,
            self.geojson_2022_path,
            self.geojson_2025_path,
            verbose=False,
        )

        self.assertEqual(result["flooded_2022"].tolist(), [False, True, False, True, None, None, None])
        self.assertEqual(result["flooded_2025"].tolist(), [False, False, True, True, None, None, None])
        self.assertEqual(result["flood_risk_label"].tolist(), [0, 1, 1, 2, None, None, None])
        self.assertNotIn("flood_risk_label", frame.columns)

    def test_rejects_invalid_is_flood_labels(self):
        data = json.loads(self.geojson_2022_path.read_text(encoding="utf-8"))
        data["features"][0]["properties"]["is_flood"] = 2
        self.geojson_2022_path.write_text(json.dumps(data), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "is_flood"):
            process_flood_state(
                pd.DataFrame({"latitude": [16.005], "longitude": [108.105]}),
                self.geojson_2022_path,
                self.geojson_2025_path,
                verbose=False,
            )

    def test_flood_only_maps_treat_points_outside_flood_polygons_as_dry(self):
        self._write_geojson(
            self.geojson_2022_path,
            flood_centers=(108.12, 108.16),
            dry_centers=(),
        )
        self._write_geojson(
            self.geojson_2025_path,
            flood_centers=(108.14, 108.16),
            dry_centers=(),
        )
        frame = pd.DataFrame(
            {
                "latitude": [16.005, 16.005, 16.005, 16.005, None],
                "longitude": [108.122, 108.142, 108.162, 108.182, 108.122],
            }
        )

        result = process_flood_state(
            frame,
            self.geojson_2022_path,
            self.geojson_2025_path,
            verbose=False,
        )

        self.assertEqual(
            result["flooded_2022"].tolist(),
            [True, False, True, False, None],
        )
        self.assertEqual(
            result["flooded_2025"].tolist(),
            [False, True, True, False, None],
        )
        self.assertEqual(result["flood_risk_label"].tolist(), [1, 1, 2, 0, None])

    def test_repairs_invalid_polygon_geometry_before_classification(self):
        self._write_geojson(
            self.geojson_2022_path,
            flood_centers=(108.10,),
            dry_centers=(),
        )
        invalid_flood_geometry = {
            "type": "Polygon",
            "coordinates": [
                [
                    [108.14, 16.00],
                    [108.15, 16.01],
                    [108.14, 16.01],
                    [108.15, 16.00],
                    [108.14, 16.00],
                ]
            ],
        }
        collection = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {"is_flood": 1},
                    "geometry": invalid_flood_geometry,
                }
            ],
        }
        self.geojson_2025_path.write_text(json.dumps(collection), encoding="utf-8")
        frame = pd.DataFrame(
            {
                "latitude": [16.002, 16.008, 16.02],
                "longitude": [108.148, 108.148, 108.142],
            }
        )

        result = process_flood_state(
            frame,
            self.geojson_2022_path,
            self.geojson_2025_path,
            verbose=False,
        )

        self.assertEqual(result["flooded_2025"].tolist(), [True, True, False])
        self.assertEqual(result["flood_risk_label"].tolist(), [1, 1, 0])


if __name__ == "__main__":
    unittest.main()
