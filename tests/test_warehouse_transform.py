import unittest

import pandas as pd

from src.warehouse.transform import (
    EXCLUDED_COLUMNS,
    WAREHOUSE_COLUMNS,
    transform_lake_final,
)


def make_warehouse_source(**overrides):
    row = {column: None for column in WAREHOUSE_COLUMNS}
    row.update(
        {
            "source": "source-a",
            "list_id": "listing-1",
            "price_vnd": 2_000_000,
            "size_m2": 20,
            "category_name": "Phòng trọ",
            "ward_name": "Hải Châu",
            "latitude": 16.05,
            "longitude": 108.2,
            "rooms": "2 PN",
            "subject": "subject to exclude",
            "body": "body to exclude",
            "url": "https://example.invalid/listing",
            "listing_type": "type to exclude",
            "scraped_at": "2026-10-09",
            "street_number": "1",
            "street_name": "Street to exclude",
        }
    )
    row.update(overrides)
    return row


class WarehouseTransformTests(unittest.TestCase):
    def test_preserves_nearest_beach_code(self):
        source = pd.DataFrame(
            [
                make_warehouse_source(
                    nearest_beach_code="TienSa",
                    dist_to_beach=0.0,
                )
            ]
        )

        transformed, _stats = transform_lake_final(source)

        self.assertEqual(transformed.iloc[0]["nearest_beach_code"], "TienSa")

    def test_filters_invalid_measurements_and_categories_and_drops_excluded_columns(self):
        source = pd.DataFrame(
            [
                make_warehouse_source(),
                make_warehouse_source(list_id="null-price", price_vnd=None),
                make_warehouse_source(list_id="zero-price", price_vnd=0),
                make_warehouse_source(list_id="null-size", size_m2=None),
                make_warehouse_source(list_id="zero-size", size_m2=0),
                make_warehouse_source(
                    list_id="apartment-alias", category_name="Căn hộ"
                ),
                make_warehouse_source(
                    list_id="unsupported", category_name="Nhà nguyên căn"
                ),
                make_warehouse_source(list_id="null-category", category_name=None),
            ]
        )
        for column in EXCLUDED_COLUMNS:
            source[column] = "must not be loaded"

        transformed, stats = transform_lake_final(source)

        self.assertEqual(
            transformed["list_id"].tolist(),
            ["listing-1", "apartment-alias"],
        )
        self.assertEqual(
            transformed["category_name"].tolist(),
            ["Phòng trọ", "Căn hộ/Chung cư"],
        )
        self.assertFalse(EXCLUDED_COLUMNS.intersection(transformed.columns))
        self.assertEqual(
            stats,
            {
                "source_rows": 8,
                "rejected_invalid_or_zero_price_size": 4,
                "rejected_unsupported_category": 2,
                "rejected_unsupported_or_null_ward": 0,
                "rejected_missing_or_invalid_coordinates": 0,
                "rejected_invalid_rooms": 0,
                "loaded_rows": 2,
            },
        )

    def test_normalizes_room_counts_and_keeps_unknown_marker(self):
        source = pd.DataFrame(
            [
                make_warehouse_source(
                    list_id="apartment-rooms",
                    category_name="  CĂN HỘ / CHUNG CƯ ",
                    rooms="2 PN",
                ),
                make_warehouse_source(
                    list_id="numeric-rooms",
                    category_name="phòng   trọ",
                    rooms=1,
                ),
                make_warehouse_source(
                    list_id="unknown-rooms",
                    rooms="không xác định",
                ),
                make_warehouse_source(
                    list_id="null-rooms",
                    rooms=None,
                ),
                make_warehouse_source(
                    list_id="rental-room-unknown-count",
                    rooms="nhiều hơn 10 PN",
                ),
                make_warehouse_source(
                    list_id="apartment-null-rooms",
                    category_name="Căn hộ",
                    rooms=None,
                ),
                make_warehouse_source(
                    list_id="more-than-ten-rooms",
                    category_name="Căn hộ/Chung cư",
                    rooms="nhiều hơn 10 PN",
                ),
            ]
        )

        transformed, stats = transform_lake_final(source)

        self.assertEqual(
            transformed["list_id"].tolist(),
            [
                "apartment-rooms",
                "numeric-rooms",
                "unknown-rooms",
                "null-rooms",
                "rental-room-unknown-count",
                "apartment-null-rooms",
            ],
        )
        self.assertEqual(
            transformed["category_name"].tolist(),
            [
                "Căn hộ/Chung cư",
                "Phòng trọ",
                "Phòng trọ",
                "Phòng trọ",
                "Phòng trọ",
                "Căn hộ/Chung cư",
            ],
        )
        self.assertEqual(
            transformed["rooms"].tolist(),
            ["2", "1", "1", "1", "1", "Không xác định"],
        )
        self.assertEqual(stats["rejected_invalid_rooms"], 1)
        self.assertEqual(stats["loaded_rows"], 6)

    def test_keeps_only_allowed_canonical_wards_and_requires_coordinates(self):
        source = pd.DataFrame(
            [
                make_warehouse_source(
                    list_id="canonical",
                    ward_name="Ngũ Hành Sơn",
                ),
                make_warehouse_source(
                    list_id="prefixed",
                    ward_name=" Phường   HÒA CƯỜNG ",
                ),
                make_warehouse_source(
                    list_id="unlisted-ward",
                    ward_name="Điện Bàn Đông",
                ),
                make_warehouse_source(list_id="null-ward", ward_name=None),
                make_warehouse_source(list_id="text-null-ward", ward_name="NULL"),
                make_warehouse_source(list_id="null-latitude", latitude=None),
                make_warehouse_source(list_id="null-longitude", longitude=None),
                make_warehouse_source(list_id="invalid-coordinate", latitude="unknown"),
                make_warehouse_source(list_id="infinite-coordinate", longitude=float("inf")),
            ]
        )

        transformed, stats = transform_lake_final(source)

        self.assertEqual(transformed["list_id"].tolist(), ["canonical", "prefixed"])
        self.assertEqual(
            transformed["ward_name"].tolist(),
            ["Ngũ Hành Sơn", "Hòa Cường"],
        )
        self.assertEqual(stats["rejected_unsupported_or_null_ward"], 3)
        self.assertEqual(stats["rejected_missing_or_invalid_coordinates"], 4)
        self.assertEqual(stats["loaded_rows"], 2)

    def test_rejects_missing_natural_keys_and_duplicate_keys(self):
        missing_key = pd.DataFrame([make_warehouse_source(source=None)])
        with self.assertRaisesRegex(ValueError, "source/list_id"):
            transform_lake_final(missing_key)

        duplicate_keys = pd.DataFrame(
            [make_warehouse_source(), make_warehouse_source()]
        )
        with self.assertRaisesRegex(ValueError, "duplicate"):
            transform_lake_final(duplicate_keys)

    def test_requires_complete_warehouse_source_columns(self):
        source = pd.DataFrame([make_warehouse_source()]).drop(columns=["size_m2"])
        with self.assertRaisesRegex(KeyError, "size_m2"):
            transform_lake_final(source)


if __name__ == "__main__":
    unittest.main()
