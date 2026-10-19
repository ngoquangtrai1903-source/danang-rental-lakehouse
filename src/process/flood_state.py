# -*- coding: utf-8 -*-
"""Enrich silver.spatial with flood observations from 2022 and 2025."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import pandas as pd
from shapely import make_valid
from shapely.geometry import Point, shape
from shapely.ops import unary_union
from shapely.prepared import prep

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.db import processed_repo

DEFAULT_GEOJSON_PATH = PROJECT_ROOT / "notebooks" / "danang_flood_2022.geojson"
DEFAULT_GEOJSON_2025_PATH = PROJECT_ROOT / "notebooks" / "danang_flood_2025.geojson"


def _polygonal_parts(geometry):
    if geometry.geom_type == "Polygon":
        return [geometry]
    if geometry.geom_type == "MultiPolygon":
        return list(geometry.geoms)
    if geometry.geom_type == "GeometryCollection":
        return [
            polygon
            for part in geometry.geoms
            for polygon in _polygonal_parts(part)
        ]
    return []


def _non_polygonal_component_count(geometry):
    if geometry.geom_type == "GeometryCollection":
        return sum(
            _non_polygonal_component_count(part)
            for part in geometry.geoms
        )
    if geometry.geom_type == "MultiPolygon":
        return 0
    if geometry.geom_type == "Polygon":
        return 0
    return 1


def _load_flood_geometries(geojson_path: Path):
    if not geojson_path.is_file():
        raise FileNotFoundError(f"Không tìm thấy flood GeoJSON: {geojson_path}")

    with geojson_path.open(encoding="utf-8") as geojson_file:
        collection = json.load(geojson_file)

    if not isinstance(collection, dict) or collection.get("type") != "FeatureCollection":
        raise ValueError("Flood GeoJSON phải có type='FeatureCollection'.")

    features = collection.get("features")
    if not isinstance(features, list) or not features:
        raise ValueError("Flood GeoJSON không có feature polygon nào.")

    coverage_polygons = []
    flood_polygons = []
    has_explicit_dry_polygons = False
    repaired_count = 0
    discarded_non_polygon_count = 0
    for index, feature in enumerate(features):
        if not isinstance(feature, dict):
            raise ValueError(f"Feature {index} không phải GeoJSON object.")
        properties = feature.get("properties") or {}
        is_flood = properties.get("is_flood")
        if type(is_flood) not in (int, bool) or is_flood not in (0, 1):
            raise ValueError(
                f"Feature {index} có properties.is_flood không hợp lệ; "
                "chỉ chấp nhận 0 hoặc 1."
            )

        geometry_data = feature.get("geometry")
        if not geometry_data:
            raise ValueError(f"Feature {index} thiếu geometry.")
        geometry = shape(geometry_data)
        if geometry.geom_type not in {"Polygon", "MultiPolygon"}:
            raise ValueError(
                f"Feature {index} có geometry {geometry.geom_type}; "
                "chỉ chấp nhận Polygon hoặc MultiPolygon."
            )

        if geometry.is_empty:
            raise ValueError(f"Feature {index} có polygon rỗng.")
        if not geometry.is_valid:
            geometry = make_valid(geometry)
            repaired_count += 1
            if geometry.is_empty or not geometry.is_valid:
                raise ValueError(
                    f"Không thể sửa polygon không hợp lệ tại feature {index} "
                    f"trong {geojson_path}."
                )

        polygon_parts = _polygonal_parts(geometry)
        if not polygon_parts:
            raise ValueError(
                f"Feature {index} không còn thành phần polygon sau khi kiểm tra "
                f"geometry trong {geojson_path}."
            )
        discarded_non_polygon_count += _non_polygonal_component_count(geometry)

        coverage_polygons.extend(polygon_parts)
        if is_flood == 1:
            flood_polygons.extend(polygon_parts)
        else:
            has_explicit_dry_polygons = True

    # Flood-only exports contain no representation of observed dry areas.
    # In that format, points outside the flood extent are treated as dry.
    coverage = (
        prep(unary_union(coverage_polygons))
        if has_explicit_dry_polygons
        else None
    )
    flood_extent = prep(unary_union(flood_polygons)) if flood_polygons else None
    return coverage, flood_extent, repaired_count, discarded_non_polygon_count


def process_flood_state(
    df: pd.DataFrame,
    geojson_2022_path: Path = DEFAULT_GEOJSON_PATH,
    geojson_2025_path: Path = DEFAULT_GEOJSON_2025_PATH,
    *,
    verbose: bool = True,
) -> pd.DataFrame:
    """Add per-year flood states and a three-class risk label.

    Label 0 means dry in both years, 1 means flooded in exactly one year,
    and 2 means flooded in both years. Flood-only maps treat points outside
    flood polygons as dry; maps with explicit dry polygons preserve unknowns
    outside the represented coverage.
    """
    for column in ("latitude", "longitude"):
        if column not in df.columns:
            raise KeyError(f"Dataset đầu vào thiếu cột bắt buộc: '{column}'")

    coverage_2022, flood_extent_2022, repaired_2022, discarded_2022 = (
        _load_flood_geometries(Path(geojson_2022_path))
    )
    coverage_2025, flood_extent_2025, repaired_2025, discarded_2025 = (
        _load_flood_geometries(Path(geojson_2025_path))
    )
    if verbose:
        for year, repaired, discarded in (
            (2022, repaired_2022, discarded_2022),
            (2025, repaired_2025, discarded_2025),
        ):
            if repaired:
                print(f"⚠️  GeoJSON {year}: đã tự sửa {repaired} geometry không hợp lệ.")
            if discarded:
                print(
                    f"⚠️  GeoJSON {year}: đã bỏ {discarded} thành phần không phải "
                    "polygon sau khi sửa geometry."
                )
    latitudes = pd.to_numeric(df["latitude"], errors="coerce")
    longitudes = pd.to_numeric(df["longitude"], errors="coerce")

    statuses_2022 = []
    statuses_2025 = []
    risk_labels = []
    for latitude, longitude in zip(latitudes, longitudes):
        if pd.isna(latitude) or pd.isna(longitude):
            statuses_2022.append(None)
            statuses_2025.append(None)
            risk_labels.append(None)
            continue

        latitude_value = float(latitude)
        longitude_value = float(longitude)
        if not math.isfinite(latitude_value) or not math.isfinite(longitude_value):
            statuses_2022.append(None)
            statuses_2025.append(None)
            risk_labels.append(None)
            continue

        point = Point(longitude_value, latitude_value)
        year_statuses = []
        for coverage, flood_extent in (
            (coverage_2022, flood_extent_2022),
            (coverage_2025, flood_extent_2025),
        ):
            if flood_extent is not None and flood_extent.covers(point):
                year_statuses.append(True)
            elif coverage is None or coverage.covers(point):
                year_statuses.append(False)
            else:
                year_statuses.append(None)

        status_2022, status_2025 = year_statuses
        statuses_2022.append(status_2022)
        statuses_2025.append(status_2025)
        if status_2022 is None or status_2025 is None:
            risk_labels.append(None)
        else:
            risk_labels.append(int(status_2022) + int(status_2025))

    result = df.copy()
    result["flooded_2022"] = pd.Series(statuses_2022, index=df.index, dtype="object")
    result["flooded_2025"] = pd.Series(statuses_2025, index=df.index, dtype="object")
    result["flood_risk_label"] = pd.Series(risk_labels, index=df.index, dtype="object")

    if verbose:
        label_counts = {
            label: sum(value == label for value in risk_labels)
            for label in (0, 1, 2)
        }
        unknown_count = sum(value is None for value in risk_labels)
        print(
            "📊 flood_risk_label: "
            f"0 an toàn={label_counts[0]}, "
            f"1 ngập một năm={label_counts[1]}, "
            f"2 ngập cả hai năm={label_counts[2]}, "
            f"chưa xác định/ngoài vùng phủ={unknown_count}."
        )

    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Gắn trạng thái ngập 2022/2025 và flood_risk_label vào silver.spatial."
    )
    parser.add_argument(
        "--geojson-2022",
        type=Path,
        default=DEFAULT_GEOJSON_PATH,
        help="Đường dẫn GeoJSON vùng ngập năm 2022.",
    )
    parser.add_argument(
        "--geojson-2025",
        type=Path,
        default=DEFAULT_GEOJSON_2025_PATH,
        help="Đường dẫn GeoJSON vùng ngập năm 2025.",
    )
    args = parser.parse_args()

    print("📥 Đang đọc silver.spatial...")
    df = processed_repo.fetch_spatial()
    if df.empty:
        raise SystemExit("❌ silver.spatial trống. Chạy bước spatial trước.")

    enriched = process_flood_state(df, args.geojson_2022, args.geojson_2025)
    processed_repo.rebuild_spatial(enriched)
    print("✅ Đã lưu flooded_2022, flooded_2025 và flood_risk_label vào silver.spatial.")


if __name__ == "__main__":
    main()
