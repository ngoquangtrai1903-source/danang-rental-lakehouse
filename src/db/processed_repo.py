# -*- coding: utf-8 -*-
"""Repository for Silver processing tables in PostgreSQL."""

from __future__ import annotations

from typing import Iterable, Sequence

import pandas as pd
from sqlalchemy import text

from .postgres import (
    append_dataframe,
    connection_scope,
    read_dataframe,
    replace_dataframe,
)

MERGED_COLUMNS = [
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

SPATIAL_COLUMNS = MERGED_COLUMNS + [
    "dist_to_cbd",
    "dist_to_beach",
    "nearest_beach_code",
    "dist_to_airport",
    "dist_to_nearest_uni",
    "nearest_uni_code",
    "flooded_2022",
    "flooded_2025",
    "flood_risk_label",
]

REPORT_COLUMNS = [
    "list_id",
    "source_address_query",
    "matched_address",
    "latitude",
    "longitude",
    "arcgis_score",
    "status",
]


def _rebuild(
    schema: str,
    table: str,
    df: pd.DataFrame,
    columns: Sequence[str],
    conn=None,
) -> int:
    frame = df.copy()
    for column in columns:
        if column not in frame.columns:
            frame[column] = None
    return replace_dataframe(schema, table, frame, columns, connection=conn)


def fetch_merged(conn=None) -> pd.DataFrame:
    return read_dataframe(
        "SELECT " + ", ".join(MERGED_COLUMNS) + " FROM silver.merged",
        connection=conn,
    )


def rebuild_merged(df: pd.DataFrame, conn=None) -> int:
    count = _rebuild("silver", "merged", df, MERGED_COLUMNS, conn)
    print(f"💾 silver.merged: ghi {count} dòng")
    return count


def fetch_geocoded(conn=None) -> pd.DataFrame:
    return read_dataframe(
        "SELECT " + ", ".join(MERGED_COLUMNS) + " FROM silver.geocoded",
        connection=conn,
    )


def rebuild_geocoded(df: pd.DataFrame, conn=None) -> int:
    count = _rebuild("silver", "geocoded", df, MERGED_COLUMNS, conn)
    print(f"💾 silver.geocoded: ghi {count} dòng")
    return count


def update_geocode_coords(updates: Iterable[tuple], conn=None) -> int:
    """Update coordinates using (latitude, longitude, source, list_id) values."""
    rows = list(updates)
    if not rows:
        return 0
    parameters = [
        {
            "latitude": row[0],
            "longitude": row[1],
            "source": row[2],
            "list_id": row[3],
        }
        for row in rows
    ]
    statement = text(
        """
        UPDATE silver.geocoded
        SET latitude = :latitude, longitude = :longitude
        WHERE source = :source AND list_id = :list_id
        """
    )
    with connection_scope(conn, transaction=True) as active_connection:
        active_connection.execute(statement, parameters)
    return len(rows)


def clear_geocode_report(conn=None) -> None:
    with connection_scope(conn, transaction=True) as active_connection:
        active_connection.execute(text("TRUNCATE TABLE silver.geocode_report"))


def insert_geocode_report(
    rows: Iterable[dict] | pd.DataFrame,
    conn=None,
    *,
    replace: bool = False,
) -> int:
    frame = rows.copy() if isinstance(rows, pd.DataFrame) else pd.DataFrame(list(rows))
    if frame.empty:
        if replace:
            with connection_scope(conn, transaction=True) as active_connection:
                active_connection.execute(text("TRUNCATE TABLE silver.geocode_report"))
        return 0
    for column in REPORT_COLUMNS:
        if column not in frame.columns:
            frame[column] = None

    with connection_scope(conn, transaction=True) as active_connection:
        if replace:
            active_connection.execute(text("TRUNCATE TABLE silver.geocode_report"))
        count = append_dataframe(
            "silver",
            "geocode_report",
            frame,
            REPORT_COLUMNS,
            connection=active_connection,
        )
    print(f"💾 silver.geocode_report: ghi {count} dòng")
    return count


def fetch_spatial(conn=None) -> pd.DataFrame:
    return read_dataframe(
        "SELECT " + ", ".join(SPATIAL_COLUMNS) + " FROM silver.spatial",
        connection=conn,
    )


def rebuild_spatial(df: pd.DataFrame, conn=None) -> int:
    frame = df.copy()
    for column in ("flooded_2022", "flooded_2025"):
        if column in frame.columns:
            frame[column] = frame[column].map(
                lambda value: None
                if value is None or pd.isna(value)
                else bool(value)
            )
    count = _rebuild("silver", "spatial", frame, SPATIAL_COLUMNS, conn)
    print(f"💾 silver.spatial: ghi {count} dòng")
    return count
