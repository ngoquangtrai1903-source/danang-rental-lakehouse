# -*- coding: utf-8 -*-
"""
Geocode ward_name/street_name/street_number -> latitude/longitude bằng ArcGIS.
Đọc silver.merged, ghi silver.geocoded + silver.geocode_report (PostgreSQL).

CHỈ geocode những dòng ĐANG NULL latitude/longitude.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import pandas as pd
from geopy.exc import GeocoderServiceError, GeocoderTimedOut, GeocoderUnavailable
from geopy.geocoders import ArcGIS

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.db import processed_repo

DA_NANG_BBOX = (15.85, 107.85, 16.30, 108.35)


def in_da_nang_bbox(lat, lng):
    if lat is None or lng is None or pd.isna(lat) or pd.isna(lng):
        return False
    min_lat, min_lng, max_lat, max_lng = DA_NANG_BBOX
    return min_lat <= lat <= max_lat and min_lng <= lng <= max_lng


def safe_str(v):
    """Chuẩn hoá giá trị: None/NaN/'nan' -> chuỗi rỗng."""
    if v is None:
        return ""
    if isinstance(v, float) and pd.isna(v):
        return ""
    s = str(v).strip()
    if s.lower() in ("", "nan", "none", "null"):
        return ""
    return s


def build_address(row, city="Đà Nẵng", country="Việt Nam"):
    street_number = safe_str(row.get("street_number"))
    street_name = safe_str(row.get("street_name"))
    ward_name = safe_str(row.get("ward_name"))

    street_full = " ".join(p for p in [street_number, street_name] if p)
    parts = [p for p in [street_full, ward_name, city, country] if p]

    if not street_full and not ward_name:
        return ","
    return ", ".join(parts)


def geocode_row(geolocator, address, retries=3):
    for attempt in range(retries):
        try:
            location = geolocator.geocode(address, timeout=10)
            if location:
                score = None
                if isinstance(location.raw, dict):
                    score = location.raw.get("score")
                return location.latitude, location.longitude, location.address, score
            return None, None, None, None
        except (GeocoderTimedOut, GeocoderServiceError, GeocoderUnavailable) as e:
            print(f"  ⚠️ Lỗi geocode (lần {attempt + 1}): {e}")
            time.sleep(2)
        except Exception as e:
            print(f"  ⚠️ Lỗi không xác định (lần {attempt + 1}): {e}")
            time.sleep(2)
    return None, None, None, None


def main():
    parser = argparse.ArgumentParser(
        description="Geocode ward_name/street_name/street_number -> lat/lng bằng ArcGIS (PostgreSQL)"
    )
    parser.add_argument("--city", default="Đà Nẵng", help="Tên thành phố ghép vào địa chỉ")
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Số giây nghỉ giữa các request ArcGIS",
    )
    parser.add_argument(
        "--save-every",
        type=int,
        default=30,
        help="Checkpoint ghi DB sau mỗi N dòng geocode",
    )
    parser.add_argument(
        "--score-threshold",
        type=float,
        default=70.0,
        help="Ngưỡng arcgis_score để cảnh báo (mặc định 70/100)",
    )
    args, _unknown = parser.parse_known_args()

    print("📥 Đang đọc silver.merged...")
    df = processed_repo.fetch_merged()
    if df.empty:
        raise SystemExit("❌ silver.merged trống. Chạy bước merge trước.")

    # Seed geocoded from merged (full rebuild baseline), then fill null coords
    for col in ("ward_name", "street_name", "street_number", "list_id", "source"):
        if col not in df.columns:
            df[col] = None

    for col in ("latitude", "longitude"):
        if col not in df.columns:
            df[col] = None
        df[col] = df[col].apply(lambda v: v if safe_str(v) else None)
        df[col] = pd.to_numeric(df[col], errors="coerce")

    processed_repo.rebuild_geocoded(df)

    todo_mask = df["latitude"].isna() | df["longitude"].isna()
    todo_indices = df[todo_mask].index.tolist()
    print(f"🚀 Tổng {len(df)} dòng, cần geocode {len(todo_indices)} dòng đang thiếu toạ độ.\n")

    geolocator = ArcGIS(timeout=10)
    report_rows: list[dict] = []
    address_cache = {}
    n_success, n_fail, n_skip, n_out_of_bbox = 0, 0, 0, 0
    pending_coord_updates: list[tuple] = []

    for count, idx in enumerate(todo_indices, 1):
        row = df.loc[idx]
        address = build_address(row, city=args.city)
        list_id = row.get("list_id", "")
        source = row.get("source", "")

        if not address or address == ",":
            n_skip += 1
            continue

        print(f"📍 [{count}/{len(todo_indices)}] #{list_id} - {address}")

        if address in address_cache:
            lat, lng, matched_address, score = address_cache[address]
        else:
            lat, lng, matched_address, score = geocode_row(geolocator, address)
            address_cache[address] = (lat, lng, matched_address, score)
            time.sleep(args.delay)

        if lat is not None and in_da_nang_bbox(lat, lng):
            df.at[idx, "latitude"] = lat
            df.at[idx, "longitude"] = lng
            pending_coord_updates.append((lat, lng, source, str(list_id)))
            score_str = f"{score:.0f}" if score is not None else "?"
            print(f"  ✅ {lat:.6f}, {lng:.6f}  (score={score_str})  -> khớp: {matched_address}")
            n_success += 1
            status = "success"
            if score is not None and score < args.score_threshold:
                print(f"  ⚠️ score {score:.0f} < {args.score_threshold} — nên kiểm tra thủ công")
        elif lat is not None:
            print(
                f"  ⚠️ Toạ độ trả về nằm NGOÀI Đà Nẵng ({lat}, {lng}) -> bỏ qua, "
                f"không ghi vào latitude/longitude"
            )
            n_out_of_bbox += 1
            status = "out_of_bbox"
        else:
            print("  ❌ Không tìm được toạ độ.")
            n_fail += 1
            status = "not_found"

        report_rows.append(
            {
                "list_id": list_id,
                "source_address_query": address,
                "matched_address": matched_address,
                "latitude": lat,
                "longitude": lng,
                "arcgis_score": score,
                "status": status,
            }
        )

        if count % args.save_every == 0:
            if pending_coord_updates:
                processed_repo.update_geocode_coords(pending_coord_updates)
                pending_coord_updates = []
            processed_repo.insert_geocode_report(report_rows, replace=True)
            print(f"  💾 Đã checkpoint DB sau {count} dòng")

    if pending_coord_updates:
        processed_repo.update_geocode_coords(pending_coord_updates)
    processed_repo.rebuild_geocoded(df)
    processed_repo.insert_geocode_report(report_rows, replace=True)

    print("\n📊 THỐNG KÊ:")
    print(f"   ✅ Thành công: {n_success}")
    print(f"   ❌ Thất bại: {n_fail}")
    print(f"   ⏭️  Bỏ qua (địa chỉ rỗng): {n_skip}")
    print(f"   🚫 Nằm ngoài Đà Nẵng: {n_out_of_bbox}")
    print("\n📁 Đã ghi: silver.geocoded, silver.geocode_report")


if __name__ == "__main__":
    main()
