"""Transform the Lake's final listing table into the warehouse contract."""

from __future__ import annotations

import re
import unicodedata

import numpy as np
import pandas as pd
from sklearn.impute import KNNImputer
from sklearn.preprocessing import StandardScaler

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
SOURCE_COLUMNS = [
    column for column in RENTAL_ROOM_COLUMNS if column not in EXCLUDED_COLUMNS
]
SIZE_IMPUTED_FLAG = "size_imputed_flag"
WAREHOUSE_COLUMNS = SOURCE_COLUMNS + [SIZE_IMPUTED_FLAG]
FILTER_COLUMNS = ("price_vnd", "size_m2")
SIZE_MEDIAN_GROUP_COLUMNS = ("category_name", "rooms", "ward_name", "furnishing_status")
SIZE_KNN_CONFIG = {
    "Căn hộ/Chung cư": {
        "cols": ("rooms_num", "latitude", "longitude"),
        "k": 20,
    },
    "Phòng trọ": {
        "cols": (
            "latitude",
            "longitude",
            "has_balcony",
            "free_hours",
            "has_camera_security",
            "has_elevator",
            "has_mezzanine",
            "private_bathroom",
            "wifi",
            "has_parking",
            "has_window",
        ),
        "k": 40,
    },
}
RENTAL_ROOM_MAX_PRICE_VND = 20_000_000
MAX_SIZE_M2 = 120
MAX_ROOM_COUNT = 3
RENTAL_BODY_MIN_LENGTH = 100
APARTMENT_BODY_MIN_LENGTH = 200
DA_NANG_COORDINATE_BOUNDS = {
    "min_longitude": 107.3000,
    "min_latitude": 15.9167,
    "max_longitude": 108.3333,
    "max_latitude": 16.2333,
}
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


def _impute_size_with_knn(frame: pd.DataFrame) -> tuple[int, int]:
    """Impute zero sizes from real-size donors, independently per category."""
    imputed_count = 0
    rejected_without_donors = 0

    for category, config in SIZE_KNN_CONFIG.items():
        category_mask = frame["category_name"].eq(category)
        target_mask = category_mask & frame["size_m2"].eq(0)
        donor_mask = category_mask & frame["size_m2"].gt(0)
        target_rows = frame.loc[target_mask]
        donor_rows = frame.loc[donor_mask]
        if target_rows.empty:
            continue
        if donor_rows.empty:
            rejected_without_donors += len(target_rows)
            frame.drop(index=target_rows.index, inplace=True)
            continue

        features = list(config["cols"])
        donor_features = _size_knn_features(donor_rows, features)
        target_features = _size_knn_features(target_rows, features)
        for feature_frame in (donor_features, target_features):
            for column in feature_frame.columns:
                feature_frame[column] = pd.to_numeric(
                    feature_frame[column], errors="coerce"
                )
            feature_frame.replace([np.inf, -np.inf], np.nan, inplace=True)

        scaler = StandardScaler()
        donor_features_scaled = scaler.fit_transform(donor_features)
        target_features_scaled = scaler.transform(target_features)

        donor_values = np.column_stack(
            (donor_features_scaled, np.log(donor_rows["size_m2"].to_numpy()))
        )
        target_values = np.column_stack(
            (
                target_features_scaled,
                np.full(len(target_rows), np.nan),
            )
        )
        imputer = KNNImputer(
            n_neighbors=config["k"],
            weights="distance",
        )
        imputer.fit(donor_values)
        predicted_log_sizes = imputer.transform(target_values)[:, -1]
        predicted_sizes = np.exp(predicted_log_sizes)
        valid_predictions = np.isfinite(predicted_sizes) & (predicted_sizes > 0)
        valid_indices = target_rows.index[valid_predictions]
        frame.loc[valid_indices, "size_m2"] = predicted_sizes[valid_predictions]
        frame.loc[valid_indices, SIZE_IMPUTED_FLAG] = 1
        rejected_indices = target_rows.index[~valid_predictions]
        if len(rejected_indices):
            frame.drop(index=rejected_indices, inplace=True)
            rejected_without_donors += len(rejected_indices)
        imputed_count += int(valid_predictions.sum())

    return imputed_count, rejected_without_donors


def _size_knn_features(rows: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    features = rows[[column for column in columns if column != "rooms_num"]].copy()
    if "rooms_num" in columns:
        features["rooms_num"] = pd.to_numeric(
            rows["rooms"].map(_normalize_room_count),
            errors="coerce",
        )
    return features.loc[:, columns]


def _impute_size_with_group_median(frame: pd.DataFrame) -> tuple[int, int]:
    """Impute zero sizes from positive-size medians in matching listing groups."""
    donor_sizes = frame["size_m2"].where(frame["size_m2"].gt(0))
    group_medians = (
        frame.assign(_donor_size_m2=donor_sizes)
        .groupby(list(SIZE_MEDIAN_GROUP_COLUMNS), dropna=False)["_donor_size_m2"]
        .transform("median")
    )
    target_mask = frame["size_m2"].eq(0)
    imputable_mask = target_mask & group_medians.notna()
    rejected_mask = target_mask & group_medians.isna()

    frame.loc[imputable_mask, "size_m2"] = group_medians.loc[imputable_mask]
    frame.loc[imputable_mask, SIZE_IMPUTED_FLAG] = 1
    frame.drop(index=frame.index[rejected_mask], inplace=True)
    return int(imputable_mask.sum()), int(rejected_mask.sum())


def transform_lake_final(
    df: pd.DataFrame,
    *,
    impute_size_knn: bool = False,
    impute_size_median: bool = False,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Apply warehouse category, location, room-count, and measurement rules."""
    if impute_size_knn and impute_size_median:
        raise ValueError("Choose only one size imputation mode: KNN or median.")

    missing = [
        column
        for column in SOURCE_COLUMNS + ["body"]
        if column not in df.columns
    ]
    if missing:
        raise KeyError(
            "Lake final source is missing required warehouse columns: "
            + ", ".join(missing)
        )

    frame = df[SOURCE_COLUMNS].copy().reset_index(drop=True)
    frame[SIZE_IMPUTED_FLAG] = 0
    body_text = df["body"].astype("string").str.strip().reset_index(drop=True)

    for column in FILTER_COLUMNS:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame["size_m2"] = frame["size_m2"].astype(float)

    invalid_price = (
        frame["price_vnd"].isna()
        | ~np.isfinite(frame["price_vnd"])
        | frame["price_vnd"].le(0)
    )
    zero_size_rejected = frame["size_m2"].eq(0) if not (
        impute_size_knn or impute_size_median
    ) else pd.Series(False, index=frame.index)
    invalid_size = (
        frame["size_m2"].isna()
        | ~np.isfinite(frame["size_m2"])
        | frame["size_m2"].lt(0)
        | zero_size_rejected
    )
    rejected_mask = invalid_price | invalid_size
    rejected_measurement_rows = int(rejected_mask.sum())
    frame = frame.loc[~rejected_mask].copy()

    normalized_categories = frame["category_name"].map(_normalize_category)
    rejected_category_mask = ~normalized_categories.isin(ALLOWED_CATEGORIES)
    rejected_category_rows = int(rejected_category_mask.sum())
    frame = frame.loc[~rejected_category_mask].copy()
    frame["category_name"] = normalized_categories.loc[~rejected_category_mask]

    frame_body_lengths = body_text.loc[frame.index].str.len()
    short_rental_body = (
        frame["category_name"].eq("Phòng trọ")
        & (
            body_text.loc[frame.index].isna()
            | frame_body_lengths.lt(RENTAL_BODY_MIN_LENGTH)
        )
    )
    short_apartment_body = (
        frame["category_name"].eq("Căn hộ/Chung cư")
        & (
            body_text.loc[frame.index].isna()
            | frame_body_lengths.lt(APARTMENT_BODY_MIN_LENGTH)
        )
    )
    rejected_rental_short_body_rows = int(short_rental_body.sum())
    rejected_apartment_short_body_rows = int(short_apartment_body.sum())
    frame = frame.loc[~(short_rental_body | short_apartment_body)].copy()

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

    outside_bounds = (
        ~frame["longitude"].between(
            DA_NANG_COORDINATE_BOUNDS["min_longitude"],
            DA_NANG_COORDINATE_BOUNDS["max_longitude"],
            inclusive="both",
        )
        | ~frame["latitude"].between(
            DA_NANG_COORDINATE_BOUNDS["min_latitude"],
            DA_NANG_COORDINATE_BOUNDS["max_latitude"],
            inclusive="both",
        )
    )
    rejected_outside_coordinate_bounds = int(outside_bounds.sum())
    frame = frame.loc[~outside_bounds].copy()

    expensive_rental_rooms = (
        frame["category_name"].eq("Phòng trọ")
        & frame["price_vnd"].gt(RENTAL_ROOM_MAX_PRICE_VND)
    )
    rejected_rental_room_over_price_limit = int(expensive_rental_rooms.sum())
    frame = frame.loc[~expensive_rental_rooms].copy()

    rental_room_mask = frame["category_name"].eq("Phòng trọ")
    normalized_rooms = frame["rooms"].map(_normalize_room_count)
    normalized_rooms.loc[rental_room_mask] = "1"

    unknown_apartment_rooms = (
        frame["category_name"].eq("Căn hộ/Chung cư")
        & normalized_rooms.eq(UNKNOWN_ROOM_LABEL)
    )
    known_apartment_rooms = pd.to_numeric(
        normalized_rooms.loc[
            frame["category_name"].eq("Căn hộ/Chung cư")
            & normalized_rooms.ne(UNKNOWN_ROOM_LABEL)
        ],
        errors="coerce",
    ).dropna()
    room_count_modes = known_apartment_rooms.mode()
    rooms_imputed_with_mode = 0
    if not room_count_modes.empty:
        mode_room_count = str(int(room_count_modes.iloc[0]))
        rooms_imputed_with_mode = int(unknown_apartment_rooms.sum())
        normalized_rooms.loc[unknown_apartment_rooms] = mode_room_count

    rejected_room_mask = normalized_rooms.isna() | normalized_rooms.eq(
        UNKNOWN_ROOM_LABEL
    )
    rejected_room_rows = int(rejected_room_mask.sum())
    frame = frame.loc[~rejected_room_mask].copy()
    frame["rooms"] = normalized_rooms.loc[~rejected_room_mask]

    room_counts = pd.to_numeric(frame["rooms"], errors="coerce")
    over_room_limit = room_counts.gt(MAX_ROOM_COUNT)
    rejected_rooms_over_limit = int(over_room_limit.sum())
    frame = frame.loc[~over_room_limit].copy()

    sizes_imputed_by_group_median = 0
    sizes_imputed_with_knn = 0
    rejected_size_without_knn_donors = 0
    rejected_size_without_group_median = 0
    if impute_size_knn:
        (
            sizes_imputed_with_knn,
            rejected_size_without_knn_donors,
        ) = _impute_size_with_knn(frame)
        rejected_measurement_rows += rejected_size_without_knn_donors
    elif impute_size_median:
        (
            sizes_imputed_by_group_median,
            rejected_size_without_group_median,
        ) = _impute_size_with_group_median(frame)
        rejected_measurement_rows += rejected_size_without_group_median

    if impute_size_knn or impute_size_median:
        imputed_mask = frame[SIZE_IMPUTED_FLAG].eq(1)
        frame.loc[imputed_mask, "price_per_m2_vnd"] = (
            frame.loc[imputed_mask, "price_vnd"]
            / frame.loc[imputed_mask, "size_m2"]
        ).round()

    size_at_or_above_limit = frame["size_m2"].ge(MAX_SIZE_M2)
    rejected_size_at_or_above_limit = int(size_at_or_above_limit.sum())
    frame = frame.loc[~size_at_or_above_limit].copy()

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

    stats = {
        "source_rows": len(df),
        "rejected_rental_body_length_under_100": rejected_rental_short_body_rows,
        "rejected_apartment_body_length_under_200": rejected_apartment_short_body_rows,
        "rejected_invalid_or_non_positive_price_size": rejected_measurement_rows,
        "rejected_unsupported_category": rejected_category_rows,
        "rejected_unsupported_or_null_ward": rejected_ward_rows,
        "rejected_missing_or_invalid_coordinates": rejected_coordinate_rows,
        "rejected_outside_coordinate_bounds": rejected_outside_coordinate_bounds,
        "rejected_rental_room_over_price_limit": rejected_rental_room_over_price_limit,
        "rejected_size_at_or_above_120": rejected_size_at_or_above_limit,
        "size_m2_imputed_by_group_median": sizes_imputed_by_group_median,
        "size_m2_imputed_with_knn": sizes_imputed_with_knn,
        "rejected_size_without_knn_donors": rejected_size_without_knn_donors,
        "rejected_size_without_group_median": rejected_size_without_group_median,
        "rejected_invalid_rooms": rejected_room_rows,
        "rooms_imputed_with_mode": rooms_imputed_with_mode,
        "rejected_rooms_over_limit": rejected_rooms_over_limit,
        "loaded_rows": len(frame),
    }
    return frame, stats
