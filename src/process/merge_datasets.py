# -*- coding: utf-8 -*-
"""
Merge & Deduplication Script
Gộp dữ liệu từ silver.listings (PostgreSQL) và dedup theo nội dung tin đăng.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.db import processed_repo, raw_listings
from src.process.attribute_normalization import normalize_merged_attributes
from src.process.rebuild_raw_listings import rebuild_raw_listings
from src.scrape.furnishing_fallback import (
    infer_furnishing_status,
    is_unknown_furnishing_status,
)

NHATOT_SOURCES = {"nhatot_canho", "nhatot_phongtro"}


def _normalize_listing_text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return " ".join(str(value).split()).casefold()


def deduplicate_listings(df: pd.DataFrame) -> pd.DataFrame:
    """Keep the first listing for each non-empty normalized body."""
    required_columns = {"body"}
    missing_columns = required_columns.difference(df.columns)
    if missing_columns:
        raise ValueError(
            "Cannot deduplicate listings by body; missing columns: "
            + ", ".join(sorted(missing_columns))
        )

    normalized_body = df["body"].map(_normalize_listing_text)
    complete_keys = normalized_body.ne("")
    duplicate_rows = complete_keys & normalized_body.duplicated(keep="first")
    return df.iloc[~duplicate_rows.to_numpy()].copy()


def enrich_nhatot_furnishing_status(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Infer unknown Nhà Tốt furnishing values from stored listing text."""
    required_columns = {"source", "furnishing_status", "subject", "body"}
    if not required_columns.issubset(df.columns):
        return df.copy(), 0

    enriched = df.copy()
    column_positions = {
        column: enriched.columns.get_loc(column)
        for column in required_columns
    }
    updated_count = 0

    for row_position in range(len(enriched)):
        source = enriched.iat[row_position, column_positions["source"]]
        furnishing_status = enriched.iat[
            row_position, column_positions["furnishing_status"]
        ]
        if (
            str(source).strip().casefold() not in NHATOT_SOURCES
            or not is_unknown_furnishing_status(furnishing_status)
        ):
            continue

        subject = enriched.iat[row_position, column_positions["subject"]]
        body = enriched.iat[row_position, column_positions["body"]]
        inferred_status = infer_furnishing_status(
            "" if pd.isna(subject) else str(subject),
            "" if pd.isna(body) else str(body),
        )
        if inferred_status is not None:
            enriched.iat[
                row_position, column_positions["furnishing_status"]
            ] = inferred_status
            updated_count += 1

    return enriched, updated_count


def merge_datasets() -> pd.DataFrame | None:
    """
    Replay toàn bộ Bronze payload vào silver.listings, sau đó merge như hiện tại.
    """
    print("🔁 Đang dựng lại silver.listings từ toàn bộ payload Bronze...")
    rebuild_raw_listings()

    print("📥 Đang đọc silver.listings từ PostgreSQL...")
    merged_df = raw_listings.fetch_all()
    if merged_df is None or merged_df.empty:
        print("❌ Không có dữ liệu trong silver.listings. Hãy scrape hoặc migrate trước.")
        return None

    print(f"   ✅ Đọc được {len(merged_df)} dòng")
    if "source" in merged_df.columns:
        print(merged_df["source"].value_counts().to_string())

    merged_df, inferred_count = enrich_nhatot_furnishing_status(merged_df)
    print(
        "\n🪑 Đã suy luận furnishing_status từ subject/body cho "
        f"{inferred_count} bản ghi Nhà Tốt cũ/mới."
    )

    print("\n🧹 Đang chuẩn hóa tình trạng nội thất và tên phường...")
    original_attributes = {
        column: merged_df[column].copy()
        for column in ("furnishing_status", "ward_name")
        if column in merged_df.columns
    }
    merged_df = normalize_merged_attributes(merged_df)
    for column in ("furnishing_status", "ward_name"):
        if column in original_attributes:
            original_values = original_attributes[column].fillna("<NULL>")
            normalized_values = merged_df[column].fillna("<NULL>")
            changed_count = int((original_values != normalized_values).sum())
            print(f"   ✅ {column}: chuẩn hóa {changed_count} dòng")

    # print("\n🔍 Đang lọc dữ liệu...")
    # original_count = len(merged_df)
    #
    # price = pd.to_numeric(merged_df["price_vnd"], errors="coerce")
    # size = pd.to_numeric(merged_df["size_m2"], errors="coerce")
    # condition = (size != 0) & (price > 0) & (price <= max_price_vnd)
    # merged_df = merged_df[condition].copy()
    #
    # filtered_count = len(merged_df)
    # print(f"   ✅ Đã lọc {original_count - filtered_count} dòng không hợp lệ")
    # print(f"   ✅ Còn lại {filtered_count} dòng")

    print("\n🔄 Đang deduplicate...")
    original_count = len(merged_df)
    merged_df = deduplicate_listings(merged_df)
    dedup_count = len(merged_df)
    print(f"   ✅ Đã loại bỏ {original_count - dedup_count} dòng trùng lặp")
    print(f"   ✅ Còn lại {dedup_count} dòng duy nhất")

    processed_repo.rebuild_merged(merged_df)
    print(f"\n✅ Đã lưu silver.merged")
    print(f"📊 Tổng số dòng cuối cùng: {len(merged_df)}")
    return merged_df


if __name__ == "__main__":
    merge_datasets()
