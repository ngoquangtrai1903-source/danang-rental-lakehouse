"""Transform the Lake's final listing table into the warehouse contract."""

from __future__ import annotations

import re
import unicodedata

import numpy as np
import pandas as pd

from src.db.final_repo import RENTAL_ROOM_COLUMNS

EXCLUDED_COLUMNS = {
    "body",
    "subject",
    "url",
    "listing_type",
    "scraped_at",
    "street_number",
    "street_name",
}
WAREHOUSE_COLUMNS = [
    column for column in RENTAL_ROOM_COLUMNS if column not in EXCLUDED_COLUMNS
]
FILTER_COLUMNS = ("price_vnd", "size_m2")
CATEGORY_ALIASES = {
    "can ho": "Căn hộ/Chung cư",
    "can ho/chung cu": "Căn hộ/Chung cư",
    "phong tro": "Phòng trọ",
}
ALLOWED_CATEGORIES = frozenset({"Phòng trọ", "Căn hộ/Chung cư"})
NULL_TEXT_VALUES = frozenset({"", "null", "none", "nan"})
UNKNOWN_ROOM_LABEL = "Không xác định"
ROOM_COUNT_PATTERN = re.compile(r"(\d+)(?:\.0+)?\s*(?:pn)?", flags=re.IGNORECASE)
ALLOWED_WARDS = (
    "Ngũ Hành Sơn",
    "Hòa Cường",
    "Hòa Xuân",
    "Liên Chiểu",
    "Thanh Khê",
    "Cẩm Lệ",
    "Hải Vân",
    "Hòa Khánh",
    "Hải Châu",
    "Sơn Trà",
    "An Khê",
    "An Hải",
)
WARD_PREFIX = re.compile(r"^phường\s+", flags=re.IGNORECASE)


def _category_key(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    without_diacritics = "".join(
        char for char in decomposed if not unicodedata.combining(char)
    )
    compact_separators = re.sub(r"\s*[/]\s*", "/", without_diacritics)
    return " ".join(compact_separators.split())


WARD_ALIASES = {_category_key(ward): ward for ward in ALLOWED_WARDS}


def _normalize_category(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = unicodedata.normalize("NFC", " ".join(str(value).split()))
    if text.casefold() in NULL_TEXT_VALUES:
        return None
    return CATEGORY_ALIASES.get(_category_key(text))


def _normalize_room_count(value: object) -> str | None:
    if value is None or pd.isna(value):
        return UNKNOWN_ROOM_LABEL

    text = " ".join(str(value).split())
    if text.casefold() in NULL_TEXT_VALUES or text.casefold() == "không xác định":
        return UNKNOWN_ROOM_LABEL

    match = ROOM_COUNT_PATTERN.fullmatch(text)
    if match is None:
        return None
    return str(int(match.group(1)))


def _normalize_ward(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = unicodedata.normalize("NFC", " ".join(str(value).split()))
    if text.casefold() in NULL_TEXT_VALUES:
        return None
    text = WARD_PREFIX.sub("", text, count=1).strip()
    return WARD_ALIASES.get(_category_key(text))


def transform_lake_final(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    """Apply warehouse category, location, room-count, and measurement rules."""
    missing = [column for column in WAREHOUSE_COLUMNS if column not in df.columns]
    if missing:
        raise KeyError(
            "Lake final source is missing required warehouse columns: "
            + ", ".join(missing)
        )

    frame = df[WAREHOUSE_COLUMNS].copy()
    for column in FILTER_COLUMNS:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    measurements = frame[list(FILTER_COLUMNS)]
    invalid_measurement = measurements.isna().any(axis=1) | ~np.isfinite(
        measurements
    ).all(axis=1)
    zero_measurement = measurements.eq(0).any(axis=1)
    rejected_mask = invalid_measurement | zero_measurement
    rejected_measurement_rows = int(rejected_mask.sum())
    frame = frame.loc[~rejected_mask].copy()

    normalized_categories = frame["category_name"].map(_normalize_category)
    rejected_category_mask = ~normalized_categories.isin(ALLOWED_CATEGORIES)
    rejected_category_rows = int(rejected_category_mask.sum())
    frame = frame.loc[~rejected_category_mask].copy()
    frame["category_name"] = normalized_categories.loc[~rejected_category_mask]

    normalized_wards = frame["ward_name"].map(_normalize_ward)
    rejected_ward_mask = normalized_wards.isna()
    rejected_ward_rows = int(rejected_ward_mask.sum())
    frame = frame.loc[~rejected_ward_mask].copy()
    frame["ward_name"] = normalized_wards.loc[~rejected_ward_mask]

    for column in ("latitude", "longitude"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    coordinates = frame[["latitude", "longitude"]]
    invalid_coordinates = coordinates.isna().any(axis=1) | ~np.isfinite(
        coordinates
    ).all(axis=1)
    rejected_coordinate_rows = int(invalid_coordinates.sum())
    frame = frame.loc[~invalid_coordinates].copy()

    rental_room_mask = frame["category_name"].eq("Phòng trọ")
    normalized_rooms = frame["rooms"].map(_normalize_room_count)
    normalized_rooms.loc[rental_room_mask] = "1"
    rejected_room_mask = normalized_rooms.isna()
    rejected_room_rows = int(rejected_room_mask.sum())
    frame = frame.loc[~rejected_room_mask].copy()
    frame["rooms"] = normalized_rooms.loc[~rejected_room_mask]

    invalid_key = (
        frame["source"].isna()
        | frame["list_id"].isna()
        | frame["source"].astype("string").str.strip().eq("")
        | frame["list_id"].astype("string").str.strip().eq("")
    )
    if invalid_key.any():
        raise ValueError(
            f"Warehouse load contains {int(invalid_key.sum())} rows without "
            "source/list_id natural key."
        )

    duplicate_key = frame.duplicated(subset=["source", "list_id"], keep=False)
    if duplicate_key.any():
        examples = (
            frame.loc[duplicate_key, ["source", "list_id"]]
            .head(5)
            .to_dict("records")
        )
        raise ValueError(
            "Warehouse input has duplicate (source, list_id) keys; "
            f"examples: {examples}"
        )

    stats = {
        "source_rows": len(df),
        "rejected_invalid_or_zero_price_size": rejected_measurement_rows,
        "rejected_unsupported_category": rejected_category_rows,
        "rejected_unsupported_or_null_ward": rejected_ward_rows,
        "rejected_missing_or_invalid_coordinates": rejected_coordinate_rows,
        "rejected_invalid_rooms": rejected_room_rows,
        "loaded_rows": len(frame),
    }
    return frame, stats
