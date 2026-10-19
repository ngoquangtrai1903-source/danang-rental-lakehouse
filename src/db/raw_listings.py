# -*- coding: utf-8 -*-
"""Storage repository for immutable Bronze payloads and Silver listings."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

import pandas as pd
from sqlalchemy import text
from src.storage import r2_bronze

from .postgres import (
    connection_scope,
    read_dataframe,
    replace_dataframe,
)

LISTING_COLUMNS = [
    "source",
    "list_id",
    "posted_date",
    "price_vnd",
    "size_m2",
    "price_per_m2_vnd",
    "furnishing_status",
    "rooms",
    "category_name",
    "latitude",
    "longitude",
    "ward_name",
    "street_name",
    "street_number",
    "subject",
    "body",
    "url",
    "listing_type",
    "scraped_at",
]

SCRAPED_AT_COLUMN = "scraped_at"
PAYLOAD_COLUMNS = [
    "source",
    "list_id",
    "payload_format",
    "payload",
    "source_url",
    "scraped_at",
]
PAYLOAD_INDEX_COLUMNS = [
    "source",
    "list_id",
    "payload_format",
    "source_url",
    "scraped_at",
    "batch_id",
    "object_key",
    "record_index",
    "object_sha256",
    "manifest_key",
    "manifest_sha256",
]


def now_scraped_at() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _normalise_id(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _as_frame(rows: Iterable[dict] | pd.DataFrame) -> pd.DataFrame:
    return rows.copy() if isinstance(rows, pd.DataFrame) else pd.DataFrame(list(rows))


def get_existing_ids(source: str, conn=None) -> set[str]:
    """Return non-empty Silver listing IDs already stored for a source."""
    rows = read_dataframe(
        "SELECT list_id FROM silver.listings WHERE source = :source",
        {"source": source},
        connection=conn,
    )
    return {_normalise_id(value) for value in rows["list_id"] if _normalise_id(value)}


def get_existing_payload_ids(source: str, conn=None) -> set[str]:
    """Return indexed Bronze listing IDs for a source."""
    rows = read_dataframe(
        "SELECT list_id FROM ops.bronze_payload_index WHERE source = :source",
        {"source": source},
        connection=conn,
    )
    return {_normalise_id(value) for value in rows["list_id"] if _normalise_id(value)}


def fetch_all(conn=None) -> pd.DataFrame:
    """Load all parsed listings from Silver."""
    df = read_dataframe(
        "SELECT "
        + ", ".join(LISTING_COLUMNS)
        + " FROM silver.listings ORDER BY source, list_id",
        connection=conn,
    )
    if "list_id" in df.columns:
        df["list_id"] = df["list_id"].map(_normalise_id)
    return df


def fetch_all_payloads(conn=None) -> pd.DataFrame:
    """Read every indexed R2 payload for deterministic parser replay."""
    index = read_dataframe(
        "SELECT "
        + ", ".join(PAYLOAD_INDEX_COLUMNS)
        + " FROM ops.bronze_payload_index ORDER BY source, list_id",
        connection=conn,
    )
    if index.empty:
        return pd.DataFrame(columns=PAYLOAD_COLUMNS)

    rows = r2_bronze.read_payload_objects(index.to_dict("records"))
    payloads = pd.DataFrame.from_records(rows, columns=PAYLOAD_COLUMNS)
    if "list_id" in payloads.columns:
        payloads["list_id"] = payloads["list_id"].map(_normalise_id)
    return payloads


def insert_new(source: str, new_rows: Iterable[dict] | pd.DataFrame, conn=None) -> int:
    """Append parsed rows to Silver without replacing existing natural keys."""
    incoming = _as_frame(new_rows)
    if incoming.empty:
        print(f"💾 silver.listings[{source}]: không có dòng mới để ghi")
        return 0
    if "list_id" not in incoming.columns:
        raise ValueError("Missing required ID column: list_id")

    incoming["source"] = source
    incoming["list_id"] = incoming["list_id"].map(_normalise_id)
    incoming = incoming[incoming["list_id"] != ""].drop_duplicates(
        subset=["list_id"], keep="first"
    )
    if SCRAPED_AT_COLUMN not in incoming.columns:
        incoming[SCRAPED_AT_COLUMN] = now_scraped_at()
    else:
        incoming[SCRAPED_AT_COLUMN] = incoming[SCRAPED_AT_COLUMN].fillna(now_scraped_at())

    for column in LISTING_COLUMNS:
        if column not in incoming.columns:
            incoming[column] = None
    records = (
        incoming[LISTING_COLUMNS]
        .astype(object)
        .where(pd.notna(incoming[LISTING_COLUMNS]), None)
    )
    if records.empty:
        return 0

    columns_sql = ", ".join(LISTING_COLUMNS)
    values_sql = ", ".join(f":{column}" for column in LISTING_COLUMNS)
    statement = text(
        f"INSERT INTO silver.listings ({columns_sql}) VALUES ({values_sql}) "
        "ON CONFLICT (source, list_id) DO NOTHING"
    )
    with connection_scope(conn, transaction=True) as active_connection:
        result = active_connection.execute(statement, records.to_dict("records"))
        inserted = max(result.rowcount, 0)
    skipped = len(incoming) - inserted
    print(
        f"💾 silver.listings[{source}]: thêm {inserted} mới | "
        f"bỏ qua {skipped} trùng"
    )
    return inserted


def insert_payloads(
    source: str, new_payloads: Iterable[dict] | pd.DataFrame, conn=None
) -> int:
    """Persist new payload objects to R2 and register their index in PostgreSQL."""
    incoming = _as_frame(new_payloads)
    if incoming.empty:
        print(f"💾 Bronze[{source}]: không có payload mới để ghi")
        return 0
    if "list_id" not in incoming.columns:
        raise ValueError("Missing required ID column: list_id")
    if "payload_format" not in incoming.columns or "payload" not in incoming.columns:
        raise ValueError("Payload rows require payload_format and payload columns")

    incoming = incoming.copy()
    for column in ("source_url", "scraped_at"):
        if column not in incoming.columns:
            incoming[column] = None
    incoming["source"] = source
    incoming["list_id"] = incoming["list_id"].map(_normalise_id)
    incoming = incoming[incoming["list_id"] != ""].drop_duplicates(
        subset=["list_id"], keep="first"
    )
    if incoming.empty:
        return 0
    incoming["payload_format"] = incoming["payload_format"].astype(str).str.strip().str.lower()
    for _, row in incoming.iterrows():
        payload_format = row["payload_format"]
        if payload_format not in {"json", "html"}:
            raise ValueError(
                f"Unsupported payload format for {source}/{row['list_id']}: "
                f"{payload_format!r}"
            )
        if row["payload"] is None or (
            isinstance(row["payload"], float) and pd.isna(row["payload"])
        ):
            raise ValueError(f"Missing payload for {source}/{row['list_id']}")

    existing_ids = get_existing_payload_ids(source, conn=conn)
    fresh = incoming[~incoming["list_id"].isin(existing_ids)].copy()
    skipped = len(incoming) - len(fresh)
    if fresh.empty:
        print(
            f"💾 Bronze[{source}]: giữ {len(existing_ids)} cũ | "
            f"thêm 0 mới | bỏ qua {skipped} trùng"
        )
        return 0

    staged_rows = fresh[PAYLOAD_COLUMNS].to_dict("records")
    index_rows = r2_bronze.write_payload_batch(source, staged_rows)
    batch_id = index_rows[0]["batch_id"]
    batch_insert = text(
        """
        INSERT INTO ops.bronze_batches (
            batch_id, source, record_count, indexed_count,
            manifest_key, manifest_sha256, status
        ) VALUES (
            CAST(:batch_id AS UUID), :source, :record_count, 0,
            :manifest_key, :manifest_sha256, 'orphaned'
        )
        """
    )
    index_insert = text(
        """
        INSERT INTO ops.bronze_payload_index (
            source, list_id, payload_format, source_url, scraped_at, batch_id,
            object_key, record_index, object_sha256, manifest_key, manifest_sha256
        ) VALUES (
            :source, :list_id, :payload_format, :source_url, :scraped_at,
            CAST(:batch_id AS UUID),
            :object_key, :record_index, :object_sha256, :manifest_key, :manifest_sha256
        )
        ON CONFLICT (source, list_id) DO NOTHING
        """
    )
    with connection_scope(conn, transaction=True) as active_connection:
        active_connection.execute(
            batch_insert,
            {
                "batch_id": batch_id,
                "source": source,
                "record_count": len(index_rows),
                "manifest_key": index_rows[0]["manifest_key"],
                "manifest_sha256": index_rows[0]["manifest_sha256"],
            },
        )
        active_connection.execute(index_insert, index_rows)
        inserted_rows = active_connection.execute(
            text(
                "SELECT COUNT(*) FROM ops.bronze_payload_index "
                "WHERE batch_id = CAST(:batch_id AS UUID)"
            ),
            {"batch_id": batch_id},
        ).scalar_one()
        active_connection.execute(
            text(
                """
                UPDATE ops.bronze_batches
                SET indexed_count = :indexed_count,
                    status = :status
                WHERE batch_id = CAST(:batch_id AS UUID)
                """
            ),
            {
                "batch_id": batch_id,
                "indexed_count": inserted_rows,
                "status": "indexed" if inserted_rows else "orphaned",
            },
        )

    print(
        f"💾 Bronze[{source}]: giữ {len(existing_ids)} cũ | "
        f"thêm {inserted_rows} mới | bỏ qua {skipped + len(index_rows) - inserted_rows} trùng"
    )
    return inserted_rows


def replace_all_from_payloads(
    new_rows: Iterable[dict] | pd.DataFrame,
    *,
    expected_payload_ids: set[tuple[str, str]],
    expected_listing_ids: set[tuple[str, str]] | None = None,
    conn=None,
) -> int:
    """Atomically replace Silver listings after replaying the complete Bronze index."""
    incoming = _as_frame(new_rows)
    if incoming.empty:
        for column in ("source", "list_id"):
            if column not in incoming.columns:
                incoming[column] = pd.Series(dtype="object")
    if "source" not in incoming.columns or "list_id" not in incoming.columns:
        raise ValueError("Rebuilt listings require source and list_id columns")

    incoming["source"] = incoming["source"].map(
        lambda value: "" if value is None or pd.isna(value) else str(value).strip()
    )
    incoming["list_id"] = incoming["list_id"].map(_normalise_id)
    if (incoming["source"] == "").any() or (incoming["list_id"] == "").any():
        raise ValueError("Rebuilt listings contain an empty source or list_id")

    rebuilt_keys = set(zip(incoming["source"], incoming["list_id"]))
    if len(rebuilt_keys) != len(incoming):
        raise ValueError("Rebuilt listings contain duplicate (source, list_id) keys")
    expected_listing_ids = (
        expected_payload_ids
        if expected_listing_ids is None
        else expected_listing_ids
    )
    if rebuilt_keys != expected_listing_ids:
        missing = sorted(expected_listing_ids - rebuilt_keys)[:10]
        unexpected = sorted(rebuilt_keys - expected_listing_ids)[:10]
        raise ValueError(
            "Rebuilt listing keys do not match expected listing keys; "
            f"missing={missing}, unexpected={unexpected}"
        )

    for column in LISTING_COLUMNS:
        if column not in incoming.columns:
            incoming[column] = None
    frame = incoming[LISTING_COLUMNS].where(pd.notna(incoming[LISTING_COLUMNS]), None)

    with connection_scope(conn, transaction=True) as active_connection:
        stored_keys = active_connection.execute(
            text(
                "SELECT source, list_id FROM ops.bronze_payload_index "
                "ORDER BY source, list_id FOR SHARE"
            )
        ).fetchall()
        stored_payload_ids = {
            (str(row[0]).strip(), str(row[1]).strip()) for row in stored_keys
        }
        if stored_payload_ids != expected_payload_ids:
            raise RuntimeError(
                "Bronze payload index changed while replay was running; "
                "retry the replay before publishing Silver listings."
            )
        return replace_dataframe(
            "silver",
            "listings",
            frame,
            LISTING_COLUMNS,
            connection=active_connection,
        )
