import io
import json
import unittest
from datetime import datetime, timezone

from src.storage import r2_bronze


class FakeS3Client:
    def __init__(self):
        self.objects = {}

    def put_object(self, *, Bucket, Key, Body, **_kwargs):
        self.objects[(Bucket, Key)] = Body if isinstance(Body, bytes) else Body.read()

    def head_object(self, *, Bucket, Key):
        if (Bucket, Key) not in self.objects:
            raise KeyError(Key)
        return {}

    def get_object(self, *, Bucket, Key):
        return {"Body": io.BytesIO(self.objects[(Bucket, Key)])}


class R2BronzeTests(unittest.TestCase):
    def test_writes_immutable_jsonl_manifest_and_reads_verified_payload(self):
        client = FakeS3Client()
        indexed_rows = r2_bronze.write_payload_batch(
            "nhatot_canho",
            [
                {
                    "list_id": "listing-1",
                    "payload_format": "json",
                    "payload": {"subject": "Phòng trọ"},
                    "source_url": None,
                    "scraped_at": "2026-10-10T10:00:00Z",
                }
            ],
            s3_client=client,
            bucket="bronze",
            now=datetime(2026, 10, 11, tzinfo=timezone.utc),
        )

        self.assertEqual(len(indexed_rows), 1)
        index_row = indexed_rows[0]
        self.assertIn("source=nhatot_canho/", index_row["object_key"])
        self.assertIn("ingest_year=2026/ingest_month=10/ingest_day=11/", index_row["object_key"])
        record = r2_bronze.read_payload_objects(
            indexed_rows, s3_client=client, bucket="bronze"
        )[0]
        self.assertEqual(record["source"], "nhatot_canho")
        self.assertEqual(record["list_id"], "listing-1")
        self.assertEqual(
            json.loads(record["payload"]),
            {"subject": "Phòng trọ"},
        )

    def test_rejects_modified_bronze_object(self):
        client = FakeS3Client()
        indexed_rows = r2_bronze.write_payload_batch(
            "phongtro123",
            [
                {
                    "list_id": "listing-2",
                    "payload_format": "html",
                    "payload": "<html>room</html>",
                    "source_url": "https://example.test/room",
                }
            ],
            s3_client=client,
            bucket="bronze",
        )
        object_key = indexed_rows[0]["object_key"]
        client.objects[("bronze", object_key)] += b" "

        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            r2_bronze.read_payload_objects(
                indexed_rows, s3_client=client, bucket="bronze"
            )

    def test_jsonl_reader_preserves_unicode_line_separator_characters(self):
        client = FakeS3Client()
        payload = {
            "subject": "line separator: \u2028 and paragraph separator: \u2029",
            "body": "next line separator: \u0085",
        }
        indexed_rows = r2_bronze.write_payload_batch(
            "nhatot_phongtro",
            [
                {
                    "list_id": "listing-unicode",
                    "payload_format": "json",
                    "payload": payload,
                    "source_url": None,
                }
            ],
            s3_client=client,
            bucket="bronze",
        )

        record = r2_bronze.read_payload_objects(
            indexed_rows, s3_client=client, bucket="bronze"
        )[0]

        self.assertEqual(json.loads(record["payload"]), payload)


if __name__ == "__main__":
    unittest.main()
