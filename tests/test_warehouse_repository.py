import unittest
from unittest.mock import patch

import pandas as pd
from sqlalchemy import SmallInteger

from src.warehouse.repository import FEATURE_BIT_COLUMNS, replace_rental_room_current


class WarehouseRepositoryTests(unittest.TestCase):
    @patch("src.warehouse.repository.replace_dataframe")
    def test_persists_feature_flags_as_zero_one_and_null(self, replace_dataframe):
        row = {column: None for column in FEATURE_BIT_COLUMNS}
        row.update(
            {
                "has_balcony": True,
                "free_hours": False,
                "has_camera_security": None,
                "flooded_2022": True,
                "flooded_2025": False,
            }
        )

        replace_rental_room_current(pd.DataFrame([row]))

        frame = replace_dataframe.call_args.args[2]
        self.assertEqual(frame.loc[0, "has_balcony"], 1)
        self.assertEqual(frame.loc[0, "free_hours"], 0)
        self.assertIsNone(frame.loc[0, "has_camera_security"])
        self.assertTrue(frame.loc[0, "flooded_2022"])
        self.assertFalse(frame.loc[0, "flooded_2025"])

        dtype_overrides = replace_dataframe.call_args.kwargs["dtype_overrides"]
        self.assertEqual(set(dtype_overrides), set(FEATURE_BIT_COLUMNS))
        self.assertTrue(
            all(isinstance(dtype, SmallInteger) for dtype in dtype_overrides.values())
        )


if __name__ == "__main__":
    unittest.main()
