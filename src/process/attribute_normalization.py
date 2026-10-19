"""Canonicalize categorical attributes shared across scraped sources."""

from __future__ import annotations

import re
import unicodedata

import pandas as pd


def _normalize_whitespace(value: str) -> str:
    return " ".join(value.split())


def _comparison_key(value: str) -> str:
    return unicodedata.normalize("NFC", _normalize_whitespace(value)).casefold()


_FURNISHING_ALIASES = {
    _comparison_key("nội thất đầy đủ"): "Đầy đủ nội thất",
    _comparison_key("đầy đủ nội thất"): "Đầy đủ nội thất",
    _comparison_key("không nội thất"): "Không nội thất",
    _comparison_key("nhà trống"): "Không nội thất",
    _comparison_key("cơ bản"): "Nội thất cơ bản",
    _comparison_key("nội thất cơ bản"): "Nội thất cơ bản",
    _comparison_key("nội thất cao cấp"): "Nội thất cao cấp",
    _comparison_key("không xác định"): "Không xác định",
}
_NULL_VALUES = {"", "null", "none", "nan"}
_WARD_PREFIX = re.compile(r"^phường\s+", flags=re.IGNORECASE)


def normalize_furnishing_status(value: object) -> str:
    """Map known furnishing aliases to canonical labels."""
    if value is None or pd.isna(value):
        return "Không xác định"

    normalized = unicodedata.normalize("NFC", _normalize_whitespace(str(value)))
    if _comparison_key(normalized) in _NULL_VALUES:
        return "Không xác định"

    alias = _FURNISHING_ALIASES.get(_comparison_key(normalized))
    if alias is not None:
        return alias
    return normalized


def normalize_ward_name(value: object) -> str | None:
    """Remove source-specific 'Phường' prefix without merging ward identities."""
    if value is None or pd.isna(value):
        return None

    normalized = unicodedata.normalize("NFC", _normalize_whitespace(str(value)))
    if _comparison_key(normalized) in _NULL_VALUES:
        return None

    normalized = _WARD_PREFIX.sub("", normalized, count=1).strip()
    if not normalized:
        return None
    return normalized


def normalize_merged_attributes(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with canonical furnishing and ward labels."""
    normalized = df.copy()
    if "furnishing_status" in normalized.columns:
        normalized["furnishing_status"] = normalized["furnishing_status"].map(
            normalize_furnishing_status
        )
    if "ward_name" in normalized.columns:
        normalized["ward_name"] = normalized["ward_name"].map(normalize_ward_name)
    return normalized
