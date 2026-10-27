import unittest

import pandas as pd

from src.process.merge_datasets import deduplicate_listings


class MergeDatasetDeduplicationTests(unittest.TestCase):
    def test_deduplicates_across_sources_after_collapsing_whitespace(self):
        source = pd.DataFrame(
            [
                {
                    "source": "site-a",
                    "list_id": "listing-1",
                    "subject": "CHO THUÊ   PHÒNG ĐẸP",
                    "body": "Gần trường\n  đại học",
                },
                {
                    "source": "site-b",
                    "list_id": "listing-2",
                    "subject": "  cho thuê phòng đẹp ",
                    "body": "Gần trường đại học",
                },
                {
                    "source": "site-b",
                    "list_id": "listing-3",
                    "subject": "Phòng cho thuê khác",
                    "body": "Gần trường đại học",
                },
            ]
        )

        result = deduplicate_listings(source)

        self.assertEqual(result["list_id"].tolist(), ["listing-1", "listing-3"])
        self.assertEqual(result.iloc[0]["subject"], "CHO THUÊ   PHÒNG ĐẸP")
        self.assertEqual(result.iloc[0]["body"], "Gần trường\n  đại học")

    def test_keeps_rows_with_missing_or_empty_text(self):
        source = pd.DataFrame(
            [
                {"subject": None, "body": "Shared body"},
                {"subject": None, "body": "Shared body"},
                {"subject": "Shared subject", "body": ""},
                {"subject": "Shared subject", "body": ""},
                {"subject": "  ", "body": "Shared body"},
            ]
        )

        result = deduplicate_listings(source)

        self.assertEqual(len(result), len(source))

    def test_requires_subject_and_body_columns(self):
        with self.assertRaisesRegex(ValueError, "missing columns: body"):
            deduplicate_listings(pd.DataFrame({"subject": ["Listing"]}))


if __name__ == "__main__":
    unittest.main()
