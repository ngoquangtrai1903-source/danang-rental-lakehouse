# -*- coding: utf-8 -*-
"""Repository for the Silver rental_room table in PostgreSQL."""

from __future__ import annotations

import pandas as pd

from .postgres import read_dataframe, replace_dataframe

RENTAL_ROOM_COLUMNS = [
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
    "dist_to_cbd",
    "dist_to_beach",
    "nearest_beach_code",
    "dist_to_airport",
    "dist_to_nearest_uni",
    "nearest_uni_code",
    "flooded_2022",
    "flooded_2025",
    "flood_risk_label",
    "has_balcony",
    "free_hours",
    "has_camera_security",
    "has_elevator",
    "has_mezzanine",
    "private_bathroom",
    "wifi",
    "has_parking",
    "has_window",
]


def _bool_to_bit(value):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (bool, int)):
        return 1 if value else 0
    text_value = str(value).strip().lower()
    if text_value in {"1", "true", "yes"}:
        return 1
    if text_value in {"0", "false", "no"}:
        return 0
    return 1 if bool(value) else 0


def fetch_rental_room(conn=None) -> pd.DataFrame:
    return read_dataframe(
        "SELECT " + ", ".join(RENTAL_ROOM_COLUMNS) + " FROM silver.rental_room",
        connection=conn,
    )


def rebuild_rental_room(df: pd.DataFrame, conn=None) -> int:
    frame = df.copy()
    for column in RENTAL_ROOM_COLUMNS:
        if column not in frame.columns:
            frame[column] = None

    bool_columns = [
        "has_balcony",
        "free_hours",
        "has_camera_security",
        "has_elevator",
        "has_mezzanine",
        "private_bathroom",
        "wifi",
        "has_parking",
        "has_window",
        "flooded_2022",
        "flooded_2025",
    ]
    for column in bool_columns:
        frame[column] = frame[column].map(_bool_to_bit).map(
            lambda value: None if value is None else bool(value)
        )

    count = replace_dataframe(
        "silver",
        "rental_room",
        frame,
        RENTAL_ROOM_COLUMNS,
        connection=conn,
    )
    print(f"💾 silver.rental_room: ghi {count} dòng")
    return count
