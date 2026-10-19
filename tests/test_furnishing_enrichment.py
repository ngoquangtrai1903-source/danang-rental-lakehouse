import unittest

import pandas as pd

from src.process.merge_datasets import enrich_nhatot_furnishing_status


class FurnishingEnrichmentTests(unittest.TestCase):
    def test_enriches_historical_unknown_nhatot_rows_only(self):
        source = pd.DataFrame(
            {
                "source": [
                    "nhatot_canho",
                    "nhatot_phongtro",
                    "nhatot_canho",
                    "phongtro123",
                ],
                "furnishing_status": [
                    "Không xác định",
                    None,
                    "Nội thất cơ bản",
                    "Không xác định",
                ],
                "subject": [
                    "Căn hộ full nội thất",
                    "Phòng trọ nhà trống",
                    "Căn hộ full nội thất",
                    "Phòng trọ không nội thất",
                ],
                "body": ["", "", "", ""],
                "other": [1, 2, 3, 4],
            }
        )

        enriched, updated_count = enrich_nhatot_furnishing_status(source)

        self.assertEqual(updated_count, 2)
        self.assertEqual(
            enriched["furnishing_status"].tolist(),
            [
                "Đầy đủ nội thất",
                "Không nội thất",
                "Nội thất cơ bản",
                "Không xác định",
            ],
        )
        self.assertEqual(enriched["other"].tolist(), [1, 2, 3, 4])
        self.assertEqual(source.loc[0, "furnishing_status"], "Không xác định")

    def test_keeps_unknown_when_listing_text_has_no_evidence(self):
        source = pd.DataFrame(
            {
                "source": ["nhatot_phongtro"],
                "furnishing_status": ["Không xác định"],
                "subject": ["Phòng trọ gần trường"],
                "body": ["Liên hệ để xem phòng."],
            }
        )

        enriched, updated_count = enrich_nhatot_furnishing_status(source)

        self.assertEqual(updated_count, 0)
        self.assertEqual(enriched.loc[0, "furnishing_status"], "Không xác định")

    def test_returns_unchanged_copy_when_required_columns_are_missing(self):
        source = pd.DataFrame({"source": ["nhatot_canho"]})

        enriched, updated_count = enrich_nhatot_furnishing_status(source)

        self.assertEqual(updated_count, 0)
        self.assertTrue(enriched.equals(source))
        self.assertIsNot(enriched, source)


if __name__ == "__main__":
    unittest.main()
