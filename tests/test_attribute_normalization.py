import unittest

import pandas as pd

from src.process.attribute_normalization import (
    normalize_furnishing_status,
    normalize_merged_attributes,
    normalize_ward_name,
)


class AttributeNormalizationTests(unittest.TestCase):
    def test_normalizes_furnishing_aliases_and_unknown_values(self):
        values = [
            "Nội thất đầy đủ",
            "Đầy đủ nội thất",
            "Không nội thất",
            "Nhà trống",
            "Cơ bản",
            "Không xác định",
            None,
            "NULL",
            "Nội thất cao cấp",
        ]

        self.assertEqual(
            [normalize_furnishing_status(value) for value in values],
            [
                "Đầy đủ nội thất",
                "Đầy đủ nội thất",
                "Không nội thất",
                "Không nội thất",
                "Nội thất cơ bản",
                "Không xác định",
                "Không xác định",
                "Không xác định",
                "Nội thất cao cấp",
            ],
        )

    def test_removes_only_phuong_prefix_from_ward_names(self):
        values = [
            "Phường Hòa Cường",
            "Hòa Cường",
            "Phường Ngũ Hành Sơn",
            "  phường   Hòa Xuân ",
            "Xã Bà Nà",
            "NULL",
            None,
        ]

        self.assertEqual(
            [normalize_ward_name(value) for value in values],
            ["Hòa Cường", "Hòa Cường", "Ngũ Hành Sơn", "Hòa Xuân", "Xã Bà Nà", None, None],
        )

    def test_normalizes_only_available_columns_and_preserves_input(self):
        frame = pd.DataFrame(
            {
                "ward_name": ["Phường Hòa Xuân"],
                "furnishing_status": ["Nhà trống"],
                "other": ["unchanged"],
            }
        )

        result = normalize_merged_attributes(frame)

        self.assertEqual(result.loc[0, "ward_name"], "Hòa Xuân")
        self.assertEqual(result.loc[0, "furnishing_status"], "Không nội thất")
        self.assertEqual(result.loc[0, "other"], "unchanged")
        self.assertEqual(frame.loc[0, "ward_name"], "Phường Hòa Xuân")


if __name__ == "__main__":
    unittest.main()
