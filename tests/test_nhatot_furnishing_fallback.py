import unittest

from src.scrape.furnishing_fallback import (
    infer_furnishing_status,
    is_unknown_furnishing_status,
)
from src.scrape.scrape_nhatot_canho import process_ad_data as process_apartment_ad
from src.scrape.scrape_nhatot_phongtro import process_ad_data as process_room_ad


class NhatotFurnishingFallbackTests(unittest.TestCase):
    def test_no_furniture_status_is_eligible_for_text_fallback(self):
        self.assertTrue(is_unknown_furnishing_status("Không nội thất"))
        self.assertFalse(is_unknown_furnishing_status("Nội thất cơ bản"))

    def test_text_rules_prioritize_negative_then_full_and_basic_status(self):
        self.assertEqual(
            infer_furnishing_status(
                subject_text="Đầy đủ nội thất",
                body_text="Nhà trống, không có nội thất",
            ),
            "Không nội thất",
        )
        self.assertEqual(
            infer_furnishing_status(subject_text="Căn hộ full nội thất"),
            "Đầy đủ nội thất",
        )
        self.assertEqual(
            infer_furnishing_status(body_text="Trang bị nội thất cơ bản"),
            "Cơ bản",
        )

    def test_item_list_requires_conservative_item_count(self):
        self.assertIsNone(
            infer_furnishing_status(
                body_text="Nội thất đã có: máy lạnh"
            )
        )
        self.assertEqual(
            infer_furnishing_status(
                body_text=(
                    "Nội thất đã có: máy lạnh, tủ lạnh, máy giặt, "
                    "giường, tủ quần áo"
                )
            ),
            "Đầy đủ nội thất",
        )

    def test_apartment_scraper_uses_text_only_when_api_status_is_unknown(self):
        inferred = process_apartment_ad(
            {
                "feature_params": {
                    "seo_structure": {
                        "items": [{"id": "furnishing_sell", "value": "Không xác định"}]
                    }
                },
                "subject": "Căn hộ full nội thất",
                "body": "",
            }
        )
        api_value = process_apartment_ad(
            {
                "feature_params": {
                    "seo_structure": {
                        "items": [{"id": "furnishing_sell", "value": "Nội thất cơ bản"}]
                    }
                },
                "subject": "Căn hộ full nội thất",
                "body": "",
            }
        )
        no_furniture = process_apartment_ad(
            {
                "feature_params": {
                    "seo_structure": {
                        "items": [{"id": "furnishing_sell", "value": "Không nội thất"}]
                    }
                },
                "subject": "Căn hộ full nội thất",
                "body": "",
            }
        )

        self.assertEqual(inferred["furnishing_status"], "Đầy đủ nội thất")
        self.assertEqual(no_furniture["furnishing_status"], "Đầy đủ nội thất")
        self.assertEqual(inferred["subject"], "Căn hộ full nội thất")
        self.assertEqual(inferred["body"], "")
        self.assertEqual(api_value["furnishing_status"], "Nội thất cơ bản")
        self.assertEqual(api_value["subject"], "Căn hộ full nội thất")

    def test_room_scraper_uses_text_only_when_api_status_is_unknown(self):
        inferred = process_room_ad(
            {
                "params": [
                    {"id": "furnishing_rent", "value": "Không xác định"}
                ],
                "subject": "Phòng trọ nhà trống",
                "body": "",
            }
        )
        api_value = process_room_ad(
            {
                "params": [
                    {"id": "furnishing_rent", "value": "Đầy đủ nội thất"}
                ],
                "subject": "Phòng trọ không nội thất",
                "body": "",
            }
        )
        no_furniture = process_room_ad(
            {
                "params": [
                    {"id": "furnishing_rent", "value": "Không nội thất"}
                ],
                "subject": "Phòng trọ full nội thất",
                "body": "",
            }
        )

        self.assertEqual(inferred["furnishing_status"], "Không nội thất")
        self.assertEqual(no_furniture["furnishing_status"], "Đầy đủ nội thất")
        self.assertEqual(api_value["furnishing_status"], "Đầy đủ nội thất")
        self.assertEqual(inferred["subject"], "Phòng trọ nhà trống")

    def test_unknown_api_status_is_preserved_without_text_evidence(self):
        apartment = process_apartment_ad(
            {
                "feature_params": {
                    "seo_structure": {
                        "items": [{"id": "furnishing_sell", "value": "Không xác định"}]
                    }
                },
                "subject": "Căn hộ cho thuê gần trung tâm",
                "body": "Liên hệ để xem phòng.",
            }
        )
        room = process_room_ad(
            {
                "params": [
                    {"id": "furnishing_rent", "value": "Không xác định"}
                ],
                "subject": "Phòng trọ gần trường đại học",
                "body": "Diện tích rộng, có cửa sổ.",
            }
        )

        self.assertEqual(apartment["furnishing_status"], "Không xác định")
        self.assertEqual(room["furnishing_status"], "Không xác định")


if __name__ == "__main__":
    unittest.main()
