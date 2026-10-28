import unittest

import pandas as pd

from src.process.merge_datasets import deduplicate_listings


class MergeDatasetDeduplicationTests(unittest.TestCase):
    def test_deduplicates_by_normalized_body_only(self):
        source = pd.DataFrame(
            [
                {
                    "source": "site-a",
                    "list_id": "listing-1",
                    "subject": "Subject A",
                    "body": "Gần trường\n  đại học",
                },
                {
                    "source": "site-b",
                    "list_id": "listing-2",
                    "subject": "Different subject",
                    "body": "Gần trường đại học",
                },
                {
                    "source": "site-b",
                    "list_id": "listing-3",
                    "subject": "Subject A",
                    "body": "Nội dung tin khác",
                },
            ]
        )

        result = deduplicate_listings(source)

        self.assertEqual(result["list_id"].tolist(), ["listing-1", "listing-3"])
        self.assertEqual(result.iloc[0]["subject"], "Subject A")
        self.assertEqual(result.iloc[0]["body"], "Gần trường\n  đại học")

    def test_keeps_rows_with_missing_or_empty_text(self):
        source = pd.DataFrame(
            [
                {"body": "Shared body"},
                {"body": "Shared body"},
                {"body": ""},
                {"body": ""},
                {"body": "  "},
                {"body": None},
            ]
        )

        result = deduplicate_listings(source)

        self.assertEqual(len(result), 5)

    def test_does_not_require_subject_column(self):
        source = pd.DataFrame({"body": ["Shared body", "Shared body"]})

        result = deduplicate_listings(source)

        self.assertEqual(len(result), 1)

    def test_requires_body_column(self):
        with self.assertRaisesRegex(ValueError, "missing columns: body"):
            deduplicate_listings(pd.DataFrame({"subject": ["Listing"]}))


if __name__ == "__main__":
    unittest.main()
