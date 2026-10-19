# -*- coding: utf-8 -*-
"""Rebuild Silver listings by replaying every indexed Bronze payload."""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from bs4 import BeautifulSoup

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.db import raw_listings
from src.scrape.incremental import decode_html_payload
from src.scrape.scrape_nhatot_canho import process_ad_data as parse_nhatot_canho
from src.scrape.scrape_nhatot_phongtro import process_ad_data as parse_nhatot_phongtro
from src.scrape.scrape_phongtro123 import parse_detail_page as parse_phongtro123
from src.scrape.scrape_phongtro_vn import parse_detail_page as parse_phongtro_vn

JSON_PARSERS = {
    "nhatot_canho": parse_nhatot_canho,
    "nhatot_phongtro": parse_nhatot_phongtro,
}
HTML_PARSERS = {
    "phongtro123": parse_phongtro123,
    "phongtro_vn": parse_phongtro_vn,
}

EXCLUDED_LISTING_PHRASES = (
    "sleepbox",
    "sleep box",
    "sleep pod",
    "sleeping pod",
    "capsule hotel",
    "capsule room",
    "capsule bed",
    "phòng capsule",
    "phòng ngủ capsule",
    "hộp ngủ",
    "hộp ngủ capsule",
    "ký túc xá",
    "kí túc xá",
    "ktx",
    "dorm",
    "dorm room",
    "dormitory",
    "dormitory room",
    "student dorm",
    "student dormitory",
    "student housing",
    "student residence",
    "khu ký túc xá",
    "ký túc xá sinh viên",
    "khu lưu trú sinh viên",
    "nhà nguyên căn",
    "nguyên căn",
    "nhà phố",
    "nhà mặt phố",
    "nhà riêng",
    "nhà liền kề",
    "townhouse",
    "town house",
    "whole house",
    "entire house",
    "private house",
    "whole home",
    "entire home",
    "standalone house",
)


def _normalise_listing_text(value: object) -> str:
    text = unicodedata.normalize(
        "NFKD", "" if value is None else str(value).casefold()
    )
    without_diacritics = "".join(
        character for character in text if not unicodedata.combining(character)
    )
    return re.sub(r"[^a-z0-9]+", " ", without_diacritics).strip()


_NORMALISED_EXCLUDED_PHRASES = tuple(
    _normalise_listing_text(phrase) for phrase in EXCLUDED_LISTING_PHRASES
)


def should_exclude_listing(record: dict) -> bool:
    """Return whether listing text identifies a non-room rental property type."""
    subject = _normalise_listing_text(record.get("subject"))
    body = _normalise_listing_text(record.get("body"))
    searchable_text = f" {subject} {body} "
    return any(
        f" {phrase} " in searchable_text
        for phrase in _NORMALISED_EXCLUDED_PHRASES
    )


def _scraped_at_text(value: object) -> str:
    if pd.isna(value):
        raise ValueError("Payload row is missing scraped_at")
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        return value.isoformat(timespec="seconds") + "Z"
    return str(value)


def _parse_payload(row: pd.Series) -> dict:
    source = str(row["source"]).strip()
    list_id = str(row["list_id"]).strip()
    payload_format = str(row["payload_format"]).strip().lower()
    payload = row["payload"]
    source_url = row["source_url"]

    if payload_format == "json":
        parser = JSON_PARSERS.get(source)
        if parser is None:
            raise ValueError(f"No JSON parser registered for source {source!r}")
        raw_record = json.loads(payload)
        if not isinstance(raw_record, dict):
            raise ValueError(f"JSON payload for {source}/{list_id} is not an object")
        record = parser(raw_record)
    elif payload_format == "html":
        parser = HTML_PARSERS.get(source)
        if parser is None:
            raise ValueError(f"No HTML parser registered for source {source!r}")
        html, fallback = decode_html_payload(payload)
        if pd.isna(source_url) or not str(source_url).strip():
            raise ValueError(f"HTML payload for {source}/{list_id} has no source_url")
        soup = BeautifulSoup(html, "html.parser")
        if source == "phongtro123":
            record = parser(
                soup,
                str(source_url),
                fallback_subject=fallback.get("subject"),
            )
        else:
            record = parser(soup, str(source_url), fallback=fallback)
    else:
        raise ValueError(
            f"Unsupported payload format {payload_format!r} for {source}/{list_id}"
        )

    parsed_id = str(record.get("list_id", "")).strip()
    if parsed_id != list_id:
        raise ValueError(
            f"Parser returned list_id {parsed_id!r} for payload key "
            f"{source}/{list_id}"
        )
    record["source"] = source
    record["scraped_at"] = _scraped_at_text(row["scraped_at"])
    return record


def rebuild_raw_listings() -> int:
    """Parse every Bronze payload, then atomically replace Silver listings."""
    payloads = raw_listings.fetch_all_payloads()
    if payloads.empty:
        raise RuntimeError(
            "R2 Bronze payload index is empty; refusing to replace Silver listings."
        )

    expected_payload_ids = {
        (str(row.source).strip(), str(row.list_id).strip())
        for row in payloads.itertuples(index=False)
    }
    rebuilt_records = []
    excluded_payload_ids = set()
    for row_number, (_, row) in enumerate(payloads.iterrows(), start=1):
        try:
            record = _parse_payload(row)
            if should_exclude_listing(record):
                excluded_payload_ids.add(
                    (str(record["source"]).strip(), str(record["list_id"]).strip())
                )
            else:
                rebuilt_records.append(record)
        except Exception as exc:
            raise RuntimeError(
                f"Failed to replay payload {row_number}/{len(payloads)} "
                f"({row['source']}/{row['list_id']}): {exc}"
            ) from exc

    if excluded_payload_ids:
        print(
            f"🚫 Đã loại {len(excluded_payload_ids)} tin không thuộc loại phòng trọ "
            "khỏi silver.listings (payload vẫn được giữ trong R2 Bronze)."
        )

    inserted = raw_listings.replace_all_from_payloads(
        rebuilt_records,
        expected_payload_ids=expected_payload_ids,
        expected_listing_ids=expected_payload_ids - excluded_payload_ids,
    )
    print(
        f"✅ Đã replay {len(payloads)} payload và thay thế silver.listings "
        f"trong transaction ({inserted} dòng)."
    )
    return inserted


if __name__ == "__main__":
    rebuild_raw_listings()
