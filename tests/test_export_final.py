import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from src.process.export_final import export_final_csv


class ExportFinalCsvTests(unittest.TestCase):
    def test_exports_fetched_final_rows_as_utf8_csv_without_index(self):
        frame = pd.DataFrame(
            {
                "list_id": ["123"],
                "ward_name": ["Hòa Cường"],
                "flood_risk_label": [1],
            }
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "nested" / "rental_room.csv"
            with patch(
                "src.process.export_final.final_repo.fetch_rental_room",
                return_value=frame,
            ) as fetch:
                row_count = export_final_csv(output_path)

            self.assertEqual(row_count, 1)
            fetch.assert_called_once_with()
            raw_content = output_path.read_bytes()
            self.assertTrue(raw_content.startswith(b"\xef\xbb\xbf"))
            with output_path.open(encoding="utf-8-sig", newline="") as csv_file:
                rows = list(csv.DictReader(csv_file))

        self.assertEqual(
            rows,
            [{"list_id": "123", "ward_name": "Hòa Cường", "flood_risk_label": "1"}],
        )


if __name__ == "__main__":
    unittest.main()
