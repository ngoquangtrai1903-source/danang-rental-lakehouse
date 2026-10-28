"""Infer furnishing status from listing text when structured data is unknown."""

from __future__ import annotations

import re

import pandas as pd

FURNISHING_NEGATIVE_PATTERNS = [
    "không có nội thất",
    "không nội thất",
    "nhà trống",
    "phòng trống",
    "chưa có nội thất",
    "không có sẵn nội thất",
    "không trang bị nội thất",
]

FURNISHING_LUXURY_PATTERNS = [
    "nội thất cao cấp",
    "nội thất sang trọng",
    "trang bị nội thất cao cấp",
    "full nội thất cao cấp",
    "tiện nghi cao cấp",
]

FURNISHING_FULL_PATTERNS = [
    "đầy đủ nội thất",
    "đầy đủ tiện nghi",
    "full nội thất",
    "full tiện nghi",
    "nội thất đầy đủ",
    "tiện nghi đầy đủ",
    "full nt",
    "fullnoithat",
    "nội thất full",
    "nội thất và tiện nghi đầy đủ",
    "tiện nghi và nội thất đầy đủ",
    "trang bị đầy đủ nội thất",
    "đầy đủ tiện nghi và nội thất",
    "đầy đủ",
    "Nội thất chỉnh chu",
]

FURNISHING_BASIC_PATTERNS = [
    "nội thất cơ bản",
    "cơ bản nội thất",
    "nội thất tối thiểu",
]

FURNISHING_LIST_LABELS = [
    r"nội thất(?:\s*đã)?\s*có",
    r"nội thất\s*gồm",
    r"trang bị(?:\s*gồm)?",
    r"tiện nghi(?:\s*đã)?\s*có",
    r"bao gồm nội thất",
]

FURNITURE_ITEM_KEYWORDS = [
    "điều hòa",
    "điều hoà",
    "máy lạnh",
    "bình nóng lạnh",
    "nóng lạnh",
    "tủ lạnh",
    "máy giặt",
    "giường",
    "tủ quần áo",
    "tủ đồ",
    "bàn ghế",
    "bàn học",
    "wifi",
    "gác lửng",
    "sàn lửng",
    "sân phơi",
    "kệ bếp",
    "bếp nấu ăn",
    "bếp",
    "nệm",
    "quạt trần",
    "quạt",
    "tivi",
    " tv ",
    "kệ tủ",
    "giường ngủ",
    "tủ bếp",
    "rèm cửa",
    "bình nước nóng",
]

UNKNOWN_FURNISHING_VALUES = {
    "",
    "không xác định",
    "không nội thất",
    "nhà trống",
    "unknown",
    "null",
    "none",
}


def is_unknown_furnishing_status(value: object) -> bool:
    """Return whether an API furnishing value needs text-based fallback."""
    return (
        value is None
        or bool(pd.isna(value))
        or str(value).strip().casefold() in UNKNOWN_FURNISHING_VALUES
    )


def infer_furnishing_status(subject_text: str = "", body_text: str = "") -> str | None:
    """Apply the existing furnishing text rules to subject and body."""
    combined_norm = re.sub(
        r"\s+",
        " ",
        f"{body_text or ''} {subject_text or ''}".lower(),
    )

    for pattern in FURNISHING_NEGATIVE_PATTERNS:
        if pattern in combined_norm:
            return "Không nội thất"

    for pattern in FURNISHING_LUXURY_PATTERNS:
        if pattern in combined_norm:
            return "Nội thất cao cấp"

    for pattern in FURNISHING_FULL_PATTERNS:
        if pattern in combined_norm:
            return "Đầy đủ nội thất"

    for pattern in FURNISHING_BASIC_PATTERNS:
        if pattern in combined_norm:
            return "Cơ bản"

    list_text = None
    for label_pattern in FURNISHING_LIST_LABELS:
        match = re.search(label_pattern + r"\s*[:\-]?\s*(.+)", combined_norm)
        if match:
            list_text = match.group(1)[:300]
            break

    scan_text = list_text if list_text else combined_norm
    matched_items = {
        keyword for keyword in FURNITURE_ITEM_KEYWORDS if keyword in scan_text
    }
    if len(matched_items) >= 8:
        return "Nội thất cao cấp"
    if len(matched_items) >= 5:
        return "Đầy đủ nội thất"
    if len(matched_items) >= 2:
        return "Cơ bản"
    return None
