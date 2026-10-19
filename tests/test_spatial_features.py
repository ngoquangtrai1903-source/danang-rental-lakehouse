import unittest
from unittest.mock import patch

import pandas as pd

from src.process.spatial_features import BEACHES, process_spatial_features


class SpatialFeaturesTests(unittest.TestCase):
    @patch("src.process.spatial_features.processed_repo.rebuild_spatial")
    def test_uses_closest_beach_and_stores_its_code(self, rebuild_spatial):
        df = pd.DataFrame(
            [
                {
                    "latitude": BEACHES["TienSa"][0],
                    "longitude": BEACHES["TienSa"][1],
                },
                {
                    "latitude": BEACHES["NonNuoc"][0],
                    "longitude": BEACHES["NonNuoc"][1],
                },
            ]
        )

        result = process_spatial_features(df, verbose=False)

        self.assertEqual(result["nearest_beach_code"].tolist(), ["TienSa", "NonNuoc"])
        self.assertEqual(result["dist_to_beach"].tolist(), [0.0, 0.0])
        rebuild_spatial.assert_called_once()

    @patch("src.process.spatial_features.processed_repo.rebuild_spatial")
    def test_missing_or_invalid_coordinates_have_no_nearest_beach(
        self, rebuild_spatial
    ):
        df = pd.DataFrame(
            [
                {"latitude": None, "longitude": None},
                {"latitude": 0, "longitude": 0},
            ]
        )

        result = process_spatial_features(df, verbose=False)

        self.assertTrue(result["dist_to_beach"].isna().all())
        self.assertTrue(result["nearest_beach_code"].isna().all())
        rebuild_spatial.assert_called_once()


if __name__ == "__main__":
    unittest.main()
