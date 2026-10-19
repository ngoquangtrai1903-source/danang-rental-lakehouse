"""Append-only JSONL storage for Bronze payloads on Cloudflare R2."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Iterable

import boto3
from botocore.config import Config
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SOURCE_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")
_MAX_RECORDS_PER_PART = 500
BRONZE_SCHEMA_VERSION = 1


def _load_environment() -> None:
    env_file = PROJECT_ROOT / ".env"
    if env_file.exists():
        load_dotenv(env_file)
    else:
        load_dotenv()


@lru_cache(maxsize=1)
def get_s3_client():
    _load_environment()
    endpoint = os.getenv("R2_ENDPOINT_URL", "").strip()
    access_key = os.getenv("R2_ACCESS_KEY_ID", "").strip()
    secret_key = os.getenv("R2_SECRET_ACCESS_KEY", "").strip()
    if not all((endpoint, access_key, secret_key)):
        raise RuntimeError(
            "R2_ENDPOINT_URL, R2_ACCESS_KEY_ID, and R2_SECRET_ACCESS_KEY "
            "must be configured in .env."
        )
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=os.getenv("R2_REGION", "auto"),
        config=Config(
            signature_version="s3v4",
            retries={"max_attempts": 5, "mode": "standard"},
        ),
    )


def get_bucket_name() -> str:
    _load_environment()
    bucket = os.getenv("R2_BUCKET_NAME", "").strip()
    if not bucket:
        raise RuntimeError("R2_BUCKET_NAME is not configured in .env.")
    return bucket


def _utc_datetime(value: object) -> datetime:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return datetime.now(timezone.utc)
    if str(value).strip().casefold() in {"", "nan", "nat", "none"}:
        return datetime.now(timezone.utc)
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _optional_text(value: object) -> str | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    value_text = str(value).strip()
    if value_text.casefold() in {"", "nan", "none", "nat"}:
        return None
    return value_text


def _serialize_record(source: str, row: dict, batch_id: str) -> dict:
    if not _SOURCE_PATTERN.fullmatch(source):
        raise ValueError(f"Invalid source identifier for R2 key: {source!r}")
    list_id = str(row.get("list_id", "")).strip()
    if not list_id:
        raise ValueError("Payload row is missing list_id")

    payload_format = str(row.get("payload_format", "")).strip().lower()
    if payload_format not in {"json", "html"}:
        raise ValueError(
            f"Unsupported payload format for {source}/{list_id}: {payload_format!r}"
        )
    payload = row.get("payload")
    if payload is None:
        raise ValueError(f"Missing payload for {source}/{list_id}")
    if payload_format == "json" and not isinstance(payload, str):
        payload = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if not isinstance(payload, str):
        raise TypeError(f"{payload_format} payload must be text for {source}/{list_id}")
    if payload_format == "json":
        parsed_payload = json.loads(payload)
        if not isinstance(parsed_payload, dict):
            raise ValueError(f"JSON payload for {source}/{list_id} must be an object")

    return {
        "source": source,
        "list_id": list_id,
        "payload_format": payload_format,
        "payload": payload,
        "source_url": _optional_text(row.get("source_url")),
        "scraped_at": _utc_datetime(row.get("scraped_at")).isoformat(),
        "batch_id": batch_id,
        "schema_version": BRONZE_SCHEMA_VERSION,
    }


def write_payload_batch(
    source: str,
    payloads: Iterable[dict],
    *,
    s3_client=None,
    bucket: str | None = None,
    now: datetime | None = None,
) -> list[dict]:
    """Upload immutable JSONL objects and a complete manifest for a source batch."""
    rows = list(payloads)
    if not rows:
        return []

    client = s3_client or get_s3_client()
    bucket_name = bucket or get_bucket_name()
    ingestion_time = _utc_datetime(now)
    batch_id = str(uuid.uuid4())
    prefix = (
        f"bronze/listings/source={source}/"
        f"ingest_year={ingestion_time:%Y}/"
        f"ingest_month={ingestion_time:%m}/"
        f"ingest_day={ingestion_time:%d}/batch_id={batch_id}"
    )

    indexed_rows: list[dict] = []
    objects: list[dict] = []
    for part_number, start in enumerate(range(0, len(rows), _MAX_RECORDS_PER_PART)):
        part_rows = [
            _serialize_record(source, row, batch_id)
            for row in rows[start : start + _MAX_RECORDS_PER_PART]
        ]
        body = (
            "\n".join(
                json.dumps(record, ensure_ascii=False, separators=(",", ":"))
                for record in part_rows
            )
            + "\n"
        ).encode("utf-8")
        object_key = f"{prefix}/part-{part_number:05d}.jsonl"
        checksum = hashlib.sha256(body).hexdigest()
        client.put_object(
            Bucket=bucket_name,
            Key=object_key,
            Body=body,
            ContentType="application/x-ndjson",
            Metadata={"sha256": checksum, "schema-version": str(BRONZE_SCHEMA_VERSION)},
        )
        client.head_object(Bucket=bucket_name, Key=object_key)
        objects.append(
            {
                "object_key": object_key,
                "record_count": len(part_rows),
                "sha256": checksum,
                "size_bytes": len(body),
            }
        )
        for record_index, record in enumerate(part_rows):
            indexed_rows.append(
                {
                    "source": source,
                    "list_id": record["list_id"],
                    "payload_format": record["payload_format"],
                    "source_url": record["source_url"],
                    "scraped_at": _utc_datetime(record["scraped_at"]),
                    "batch_id": batch_id,
                    "object_key": object_key,
                    "record_index": record_index,
                    "object_sha256": checksum,
                }
            )

    manifest = {
        "batch_id": batch_id,
        "source": source,
        "published_at": ingestion_time.isoformat(),
        "schema_version": BRONZE_SCHEMA_VERSION,
        "record_count": len(indexed_rows),
        "objects": objects,
    }
    manifest_key = f"{prefix}/manifest.json"
    manifest_body = json.dumps(
        manifest, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    client.put_object(
        Bucket=bucket_name,
        Key=manifest_key,
        Body=manifest_body,
        ContentType="application/json",
        Metadata={"sha256": hashlib.sha256(manifest_body).hexdigest()},
    )
    client.head_object(Bucket=bucket_name, Key=manifest_key)
    for index_row in indexed_rows:
        index_row["manifest_key"] = manifest_key
        index_row["manifest_sha256"] = hashlib.sha256(manifest_body).hexdigest()
    return indexed_rows


def read_payload_objects(
    index_rows: list[dict], *, s3_client=None, bucket: str | None = None
) -> list[dict]:
    """Read indexed records from R2, verifying their key and envelope metadata."""
    if not index_rows:
        return []

    client = s3_client or get_s3_client()
    bucket_name = bucket or get_bucket_name()
    by_key: dict[str, list[dict]] = {}
    for row in index_rows:
        by_key.setdefault(row["object_key"], []).append(row)

    results: list[dict] = []
    checked_manifests: dict[str, dict] = {}
    for object_key, rows in by_key.items():
        manifest_key = rows[0]["manifest_key"]
        if manifest_key not in checked_manifests:
            manifest_response = client.get_object(Bucket=bucket_name, Key=manifest_key)
            manifest_bytes = manifest_response["Body"].read()
            actual_manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
            if actual_manifest_sha != rows[0]["manifest_sha256"]:
                raise ValueError(f"Bronze manifest checksum mismatch: {manifest_key}")
            checked_manifests[manifest_key] = json.loads(manifest_bytes.decode("utf-8"))

        manifest = checked_manifests[manifest_key]
        expected_source = str(rows[0]["source"]).strip()
        expected_batch = str(rows[0]["batch_id"]).strip()
        if (
            str(manifest.get("source", "")).strip() != expected_source
            or str(manifest.get("batch_id", "")).strip() != expected_batch
            or manifest.get("schema_version") != BRONZE_SCHEMA_VERSION
        ):
            raise ValueError(f"Bronze manifest metadata mismatch: {manifest_key}")
        manifest_objects = {
            item["object_key"]: item for item in manifest.get("objects", [])
        }
        if sum(
            int(item["record_count"])
            for item in manifest_objects.values()
        ) != int(manifest.get("record_count", -1)):
            raise ValueError(f"Bronze manifest record count mismatch: {manifest_key}")
        manifest_object = manifest_objects.get(object_key)
        if manifest_object is None:
            raise ValueError(
                f"Bronze manifest {manifest_key!r} does not list {object_key!r}"
            )
        response = client.get_object(Bucket=bucket_name, Key=object_key)
        object_bytes = response["Body"].read()
        actual_object_sha = hashlib.sha256(object_bytes).hexdigest()
        expected_object_sha = manifest_object["sha256"]
        if actual_object_sha != expected_object_sha:
            raise ValueError(f"Bronze object checksum mismatch: {object_key}")
        records = [
            json.loads(line)
            for line in object_bytes.decode("utf-8").split("\n")
            if line.strip()
        ]
        if len(records) != int(manifest_object["record_count"]):
            raise ValueError(f"Bronze object record count mismatch: {object_key}")
        for index_row in rows:
            if index_row["manifest_key"] != manifest_key:
                raise ValueError(
                    f"Mixed manifest references for Bronze object {object_key!r}"
                )
            if index_row["manifest_sha256"] != rows[0]["manifest_sha256"]:
                raise ValueError(
                    f"Mixed manifest checksums for Bronze object {object_key!r}"
                )
            if index_row["object_sha256"] != actual_object_sha:
                raise ValueError(f"Bronze ledger checksum mismatch: {object_key}")
            record_index = int(index_row["record_index"])
            if record_index < 0 or record_index >= len(records):
                raise ValueError(
                    f"Bronze index points outside object {object_key!r}: "
                    f"record_index={record_index}"
                )
            record = records[record_index]
            expected_key = (
                str(index_row["source"]).strip(),
                str(index_row["list_id"]).strip(),
            )
            actual_key = (
                str(record.get("source", "")).strip(),
                str(record.get("list_id", "")).strip(),
            )
            if actual_key != expected_key:
                raise ValueError(
                    f"Bronze object key mismatch at {object_key!r}: "
                    f"expected={expected_key}, actual={actual_key}"
                )
            if (
                str(record.get("batch_id", "")).strip()
                != str(index_row["batch_id"]).strip()
                or str(record.get("payload_format", "")).strip().lower()
                != str(index_row["payload_format"]).strip().lower()
            ):
                raise ValueError(
                    f"Bronze envelope metadata mismatch at {object_key!r}, "
                    f"record_index={record_index}"
                )
            if record.get("schema_version") != BRONZE_SCHEMA_VERSION:
                raise ValueError(
                    f"Unsupported Bronze schema version for {expected_key}: "
                    f"{record.get('schema_version')!r}"
                )
            results.append(
                {
                    "source": expected_key[0],
                    "list_id": expected_key[1],
                    "payload_format": record["payload_format"],
                    "payload": record["payload"],
                    "source_url": record.get("source_url"),
                    "scraped_at": record["scraped_at"],
                }
            )
    return results
