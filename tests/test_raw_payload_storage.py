import unittest
from contextlib import contextmanager
from unittest.mock import patch

import pandas as pd

from src.db import raw_listings
from src.process import rebuild_raw_listings
from src.scrape.incremental import decode_html_payload, encode_html_payload


class FakeResult:
    def __init__(self, *, rows=(), count=0, rowcount=1):
        self.rows = rows
        self.count = count
        self.rowcount = rowcount

    def fetchall(self):
        return self.rows

    def scalar_one(self):
        return self.count


class FakeConnection:
    def __init__(self, *, rows=(), count=0):
        self.rows = rows
        self.count = count
        self.executed = []

    def in_transaction(self):
        return True

    def execute(self, statement, parameters=None):
        sql = str(statement)
        self.executed.append((sql, parameters))
        if "SELECT source, list_id FROM ops.bronze_payload_index" in sql:
            return FakeResult(rows=self.rows)
        if "SELECT COUNT(*) FROM ops.bronze_payload_index" in sql:
            return FakeResult(count=self.count)
        return FakeResult()


def fake_connection_scope(connection):
    @contextmanager
    def scope(supplied_connection=None, *, transaction=False):
        yield supplied_connection or connection

    return scope


class RawPayloadStorageTests(unittest.TestCase):
    def test_inserts_new_json_payloads_and_normalizes_rows(
        self,
    ):
        connection = FakeConnection(count=1)
        indexed = [
            {
                "source": "nhatot_canho",
                "list_id": "123",
                "payload_format": "json",
                "source_url": None,
                "scraped_at": "2026-10-10T10:00:00Z",
                "batch_id": "batch-id",
                "object_key": "part.jsonl",
                "record_index": 0,
                "object_sha256": "a" * 64,
                "manifest_key": "manifest.json",
                "manifest_sha256": "b" * 64,
            }
        ]

        with (
            patch.object(raw_listings, "get_existing_payload_ids", return_value=set()),
            patch.object(
                raw_listings.r2_bronze,
                "write_payload_batch",
                return_value=indexed,
            ) as write_payloads,
            patch.object(
                raw_listings,
                "connection_scope",
                side_effect=fake_connection_scope(connection),
            ),
            patch("builtins.print"),
        ):
            inserted = raw_listings.insert_payloads(
                "nhatot_canho",
                [
                    {
                        "list_id": " 123 ",
                        "payload_format": "JSON",
                        "payload": {"title": "Phòng trọ"},
                        "source_url": None,
                        "scraped_at": "2026-10-10T10:00:00Z",
                    },
                    {
                        "list_id": "123",
                        "payload_format": "json",
                        "payload": {"title": "duplicate"},
                    },
                    {
                        "list_id": "",
                        "payload_format": "json",
                        "payload": {"title": "missing ID"},
                    },
                ],
            )

        self.assertEqual(inserted, 1)
        write_payloads.assert_called_once()
        staged = write_payloads.call_args.args[1]
        self.assertEqual(len(staged), 1)
        self.assertEqual(staged[0]["list_id"], "123")
        self.assertEqual(staged[0]["payload_format"], "json")
        self.assertEqual(staged[0]["payload"], {"title": "Phòng trọ"})
        self.assertEqual(
            sum("INSERT INTO ops.bronze_payload_index" in sql for sql, _ in connection.executed),
            1,
        )

    def test_does_not_replace_existing_payload(
        self,
    ):
        with (
            patch.object(
                raw_listings, "get_existing_payload_ids", return_value={"known-id"}
            ),
            patch.object(raw_listings.r2_bronze, "write_payload_batch") as write_payloads,
            patch("builtins.print"),
        ):
            inserted = raw_listings.insert_payloads(
                "phongtro123",
                [
                    {
                        "list_id": "known-id",
                        "payload_format": "html",
                        "payload": "<html>new version</html>",
                    }
                ],
            )

        self.assertEqual(inserted, 0)
        write_payloads.assert_not_called()

    def test_rejects_unsupported_payload_format(self):
        with self.assertRaisesRegex(ValueError, "Unsupported payload format"):
            raw_listings.insert_payloads(
                "source",
                [
                    {
                        "list_id": "1",
                        "payload_format": "xml",
                        "payload": "<listing />",
                    }
                ],
            )

    def test_html_payload_round_trip_preserves_fallback_and_document(self):
        original_html = "<html><body><h1>Cho thuê phòng</h1></body></html>"
        fallback = {
            "subject": "Phòng gần trường",
            "card_price_vnd": 2500000,
            "card_size_m2": 20,
            "card_address": "Đà Nẵng",
        }

        stored_payload = encode_html_payload(original_html, fallback)
        html, decoded_fallback = decode_html_payload(stored_payload)

        self.assertEqual(html, original_html)
        self.assertEqual(decoded_fallback, fallback)

    @patch.object(raw_listings, "replace_all_from_payloads", return_value=1)
    @patch.object(raw_listings, "fetch_all_payloads")
    @patch.object(rebuild_raw_listings, "_parse_payload")
    def test_rebuild_parses_every_payload_before_replacing(
        self, parse_payload, fetch_payloads, replace_all
    ):
        payloads = pd.DataFrame(
            [
                {"source": "source_a", "list_id": "1"},
                {"source": "source_b", "list_id": "2"},
            ]
        )
        fetch_payloads.return_value = payloads
        parse_payload.side_effect = [
            {"source": "source_a", "list_id": "1"},
            {"source": "source_b", "list_id": "2"},
        ]

        with patch("builtins.print"):
            count = rebuild_raw_listings.rebuild_raw_listings()

        self.assertEqual(count, 1)
        self.assertEqual(parse_payload.call_count, 2)
        replace_all.assert_called_once_with(
            [
                {"source": "source_a", "list_id": "1"},
                {"source": "source_b", "list_id": "2"},
            ],
            expected_payload_ids={("source_a", "1"), ("source_b", "2")},
            expected_listing_ids={("source_a", "1"), ("source_b", "2")},
        )

    def test_excludes_nontraditional_rental_types_from_listing_rebuild(self):
        excluded_titles = [
            "Sleepbox Đà Nẵng",
            "Phòng dạng sleep-box",
            "Cho thuê hộp ngủ giá rẻ",
            "KÝ TÚC XÁ sinh viên",
            "KTX gần trường đại học",
            "Dormitory room for students",
            "Cho thuê nguyên căn tại trung tâm",
            "Nhà phố 2 tầng cho thuê",
            "Townhouse in Da Nang",
            "Whole house for rent",
        ]
        for subject in excluded_titles:
            with self.subTest(subject=subject):
                self.assertTrue(
                    rebuild_raw_listings.should_exclude_listing(
                        {"subject": subject, "body": ""}
                    )
                )

    def test_keeps_room_listings_without_excluded_phrases(self):
        self.assertFalse(
            rebuild_raw_listings.should_exclude_listing(
                {
                    "subject": "Cho thuê phòng trọ gần biển",
                    "body": "Phòng riêng, có cửa sổ và máy lạnh.",
                }
            )
        )

    @patch.object(raw_listings, "replace_all_from_payloads", return_value=1)
    @patch.object(raw_listings, "fetch_all_payloads")
    @patch.object(rebuild_raw_listings, "_parse_payload")
    def test_filtered_payloads_remain_in_payload_coverage_only(
        self, parse_payload, fetch_payloads, replace_all
    ):
        fetch_payloads.return_value = pd.DataFrame(
            [
                {"source": "source_a", "list_id": "room"},
                {"source": "source_a", "list_id": "sleepbox"},
            ]
        )
        parse_payload.side_effect = [
            {
                "source": "source_a",
                "list_id": "room",
                "subject": "Cho thuê phòng trọ",
                "body": "",
            },
            {
                "source": "source_a",
                "list_id": "sleepbox",
                "subject": "Sleepbox",
                "body": "",
            },
        ]

        with patch("builtins.print"):
            rebuild_raw_listings.rebuild_raw_listings()

        replace_all.assert_called_once_with(
            [
                {
                    "source": "source_a",
                    "list_id": "room",
                    "subject": "Cho thuê phòng trọ",
                    "body": "",
                }
            ],
            expected_payload_ids={
                ("source_a", "room"),
                ("source_a", "sleepbox"),
            },
            expected_listing_ids={("source_a", "room")},
        )

    @patch.object(raw_listings, "replace_all_from_payloads")
    @patch.object(raw_listings, "fetch_all_payloads")
    @patch.object(rebuild_raw_listings, "_parse_payload", side_effect=ValueError("bad"))
    def test_failed_parse_does_not_replace_raw_listings(
        self, _parse_payload, fetch_payloads, replace_all
    ):
        fetch_payloads.return_value = pd.DataFrame(
            [{"source": "source_a", "list_id": "1"}]
        )

        with self.assertRaisesRegex(RuntimeError, "Failed to replay payload"):
            rebuild_raw_listings.rebuild_raw_listings()

        replace_all.assert_not_called()

    def test_replaces_listings_after_payload_consistency_check(
        self,
    ):
        connection = FakeConnection(rows=[("source_a", "1")])

        with (
            patch.object(
                raw_listings,
                "connection_scope",
                side_effect=fake_connection_scope(connection),
            ),
            patch.object(raw_listings, "replace_dataframe", return_value=1) as replace,
        ):
            count = raw_listings.replace_all_from_payloads(
                [{"source": "source_a", "list_id": "1"}],
                expected_payload_ids={("source_a", "1")},
            )

        self.assertEqual(count, 1)
        replace.assert_called_once()

    def test_replacement_discards_legacy_rows_without_payload(
        self,
    ):
        connection = FakeConnection(rows=[("source_a", "1")])

        with (
            patch.object(
                raw_listings,
                "connection_scope",
                side_effect=fake_connection_scope(connection),
            ),
            patch.object(raw_listings, "replace_dataframe", return_value=1) as replace,
        ):
            count = raw_listings.replace_all_from_payloads(
                [{"source": "source_a", "list_id": "1"}],
                expected_payload_ids={("source_a", "1")},
            )
        self.assertEqual(count, 1)
        replace.assert_called_once()


if __name__ == "__main__":
    unittest.main()
