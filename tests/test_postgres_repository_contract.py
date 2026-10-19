import unittest
from contextlib import contextmanager
from unittest.mock import patch

import pandas as pd
from sqlalchemy import Boolean, SmallInteger

from src.db import postgres, processed_repo


class RecordingConnection:
    def __init__(self):
        self.statements = []

    def in_transaction(self):
        return True

    def execute(self, statement, parameters=None):
        self.statements.append((str(statement), parameters))


class PostgresRepositoryContractTests(unittest.TestCase):
    def test_empty_replace_report_still_clears_existing_rows(self):
        connection = RecordingConnection()

        @contextmanager
        def connection_scope(_connection=None, *, transaction=False):
            yield connection

        with patch.object(
            processed_repo, "connection_scope", side_effect=connection_scope
        ):
            inserted = processed_repo.insert_geocode_report([], replace=True)

        self.assertEqual(inserted, 0)
        self.assertEqual(len(connection.statements), 1)
        self.assertIn("TRUNCATE TABLE silver.geocode_report", connection.statements[0][0])

    def test_spatial_repository_converts_sql_bit_values_to_postgres_boolean(self):
        frame = pd.DataFrame(
            [
                {
                    "flooded_2022": 1,
                    "flooded_2025": 0,
                }
            ]
        )

        with patch.object(processed_repo, "_rebuild", return_value=1) as rebuild:
            count = processed_repo.rebuild_spatial(frame)

        self.assertEqual(count, 1)
        rebuilt_frame = rebuild.call_args.args[2]
        self.assertTrue(bool(rebuilt_frame.loc[0, "flooded_2022"]))
        self.assertFalse(bool(rebuilt_frame.loc[0, "flooded_2025"]))

    def test_replace_uses_explicit_types_for_nullable_flood_columns(self):
        frame = pd.DataFrame(
            {
                "flooded_2022": [None, None],
                "flooded_2025": [None, None],
                "flood_risk_label": [None, None],
            }
        )
        connection = RecordingConnection()

        @contextmanager
        def connection_scope(_connection=None, *, transaction=False):
            yield connection

        with (
            patch.object(postgres, "connection_scope", side_effect=connection_scope),
            patch.object(pd.DataFrame, "to_sql") as to_sql,
        ):
            postgres.replace_dataframe(
                "silver",
                "spatial",
                frame,
                list(frame.columns),
                connection=connection,
            )

        sql_types = to_sql.call_args.kwargs["dtype"]
        self.assertIsInstance(sql_types["flooded_2022"], Boolean)
        self.assertIsInstance(sql_types["flooded_2025"], Boolean)
        self.assertIsInstance(sql_types["flood_risk_label"], SmallInteger)


if __name__ == "__main__":
    unittest.main()
