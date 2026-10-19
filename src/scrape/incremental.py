"""Shared append-only scrape helpers backed by R2 Bronze and PostgreSQL index."""

from __future__ import annotations

import sys
import base64
import json
from pathlib import Path
from typing import Iterable

import pandas as pd

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.db.raw_listings import (
    SCRAPED_AT_COLUMN,
    get_existing_ids as db_get_existing_ids,
    get_existing_payload_ids as db_get_existing_payload_ids,
    insert_payloads,
    insert_new,
    now_scraped_at,
)

__all__ = [
    "SCRAPED_AT_COLUMN",
    "now_scraped_at",
    "load_existing_ids",
    "load_existing_payload_ids",
    "save_incremental",
    "save_payloads",
    "encode_html_payload",
    "decode_html_payload",
]


def load_existing_ids(source: str, id_col: str = "list_id") -> set[str]:
    """Return non-empty listing IDs already stored for a source."""
    if id_col != "list_id":
        raise ValueError("Only list_id is supported for listing storage")
    return db_get_existing_ids(source)


def load_existing_payload_ids(source: str, id_col: str = "list_id") -> set[str]:
    """Return listing IDs already represented in the Bronze index."""
    if id_col != "list_id":
        raise ValueError("Only list_id is supported for listing storage")
    return db_get_existing_payload_ids(source)


def save_incremental(
    source: str,
    new_rows: Iterable[dict] | pd.DataFrame,
    id_col: str = "list_id",
) -> int:
    """Append new listing rows without replacing old records."""
    if id_col != "list_id":
        raise ValueError("Only list_id is supported for listing storage")
    return insert_new(source, new_rows)


def save_payloads(
    source: str,
    new_payloads: Iterable[dict] | pd.DataFrame,
) -> int:
    """Append raw payloads for new source/list_id pairs."""
    return insert_payloads(source, new_payloads)


def encode_html_payload(html: str, fallback: dict) -> str:
    """Keep parser fallback values alongside HTML in the existing payload column."""
    context = json.dumps(fallback, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )
    encoded_context = base64.urlsafe_b64encode(context).decode("ascii")
    return f"<!--PIPELINE_CONTEXT:{encoded_context}-->\n{html}"


def decode_html_payload(payload: str) -> tuple[str, dict]:
    """Extract parser context while returning the original fetched HTML body."""
    prefix = "<!--PIPELINE_CONTEXT:"
    if not payload.startswith(prefix):
        return payload, {}
    marker_end = payload.find("-->\n")
    if marker_end < 0:
        raise ValueError("Malformed HTML payload context header")
    encoded_context = payload[len(prefix):marker_end]
    context = json.loads(base64.urlsafe_b64decode(encoded_context).decode("utf-8"))
    if not isinstance(context, dict):
        raise ValueError("HTML payload context must be a JSON object")
    return payload[marker_end + len("-->\n"):], context
