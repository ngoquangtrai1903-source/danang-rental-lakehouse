"""Persistence for the consumer-facing Gold rental_room table."""

from __future__ import annotations

import pandas as pd
from sqlalchemy import SmallInteger

from src.db.final_repo import _bool_to_bit
from src.db.postgres import replace_dataframe
from src.warehouse.transform import WAREHOUSE_COLUMNS

FEATURE_BIT_COLUMNS = (
    "has_balcony",
    "free_hours",
    "has_camera_security",
    "has_elevator",
    "has_mezzanine",
    "private_bathroom",
    "wifi",
    "has_parking",
    "has_window",
)

def replace_rental_room_current(df: pd.DataFrame) -> int:
    """Atomically replace the Gold consumer table after existing transforms."""
    frame = df.copy()
    for column in FEATURE_BIT_COLUMNS:
        frame[column] = frame[column].map(_bool_to_bit)
    for column in ("flooded_2022", "flooded_2025"):
        frame[column] = frame[column].map(_bool_to_bit).map(
            lambda value: None if value is None else bool(value)
        )
    return replace_dataframe(
        "gold",
        "rental_room",
        frame,
        WAREHOUSE_COLUMNS,
        dtype_overrides={
            column: SmallInteger() for column in FEATURE_BIT_COLUMNS
        },
    )
