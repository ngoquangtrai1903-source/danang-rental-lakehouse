# -*- coding: utf-8 -*-
"""
Main Pipeline Orchestrator
Điều khiển pipeline dữ liệu từ cào đến Gold (R2 + PostgreSQL/PostGIS).

Các bước:
1. SCRAPE  → R2 Bronze (chỉ payload mới)
2. REPLAY  → silver.listings (parse lại toàn bộ payload trước MERGE)
3. MERGE   → silver.merged
4. GEOCODE → silver.geocoded (+ geocode_report)
5. SPATIAL → silver.spatial
6. FLOOD   → silver.spatial (flood_risk_label)
7. TEXT    → silver.rental_room
8. GOLD    → gold.rental_room
9. EXPORT  → data/final/rental_room.csv

Sử dụng:
    python main.py --step all
    python main.py --step all --skip-scrape
    python main.py --step scrape|merge|geocode|spatial|flood|text
"""

import argparse
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent
SRC_DIR = BASE_DIR / "src"


def step_scrape(args):
    """Bước 1: Cào và lưu payload mới vào R2 Bronze."""
    print("\n" + "=" * 60)
    print("BƯỚC 1: CÀO DỮ LIỆU TỪ CÁC NGUỒN → R2 BRONZE")
    print("=" * 60 + "\n")

    print("📥 Cào Nhà Tốt (Căn hộ)...")
    subprocess.run(
        [sys.executable, str(SRC_DIR / "scrape" / "scrape_nhatot_canho.py")],
        check=True,
    )

    print("\n📥 Cào Nhà Tốt (Phòng trọ)...")
    subprocess.run(
        [sys.executable, str(SRC_DIR / "scrape" / "scrape_nhatot_phongtro.py")],
        check=True,
    )

    print("\n📥 Cào Phongtro123.com...")
    subprocess.run(
        [sys.executable, str(SRC_DIR / "scrape" / "scrape_phongtro123.py")],
        check=True,
    )

    print("\n📥 Cào Phongtro.vn...")
    subprocess.run(
        [sys.executable, str(SRC_DIR / "scrape" / "scrape_phongtro_vn.py")],
        check=True,
    )

    print("\n✅ Hoàn tất bước cào dữ liệu!")


def step_merge(args):
    print("\n" + "=" * 60)
    print("BƯỚC 2: REPLAY PAYLOADS → silver.listings → silver.merged")
    print("=" * 60 + "\n")

    subprocess.run(
        [sys.executable, str(SRC_DIR / "process" / "merge_datasets.py")],
        check=True,
    )
    print("\n✅ Hoàn tất bước merge!")


def step_geocode(args):
    print("\n" + "=" * 60)
    print("BƯỚC 3: GEOCODE → silver.geocoded")
    print("=" * 60 + "\n")

    subprocess.run(
        [sys.executable, str(SRC_DIR / "process" / "geocode_with_arcgis.py")],
        check=True,
    )
    print("\n✅ Hoàn tất bước geocode!")


def step_spatial(args):
    print("\n" + "=" * 60)
    print("BƯỚC 4: SPATIAL FEATURES → silver.spatial")
    print("=" * 60 + "\n")

    subprocess.run(
        [sys.executable, str(SRC_DIR / "process" / "spatial_features.py")],
        check=True,
    )
    print("\n✅ Hoàn tất bước spatial features!")


def step_flood(args):
    print("\n" + "=" * 60)
    print("BƯỚC 5: PHÂN LOẠI RỦI RO LŨ 2022/2025 → silver.spatial")
    print("=" * 60 + "\n")

    subprocess.run(
        [
            sys.executable,
            str(SRC_DIR / "process" / "flood_state.py"),
            "--geojson-2022",
            str(args.flood_geojson_2022),
            "--geojson-2025",
            str(args.flood_geojson_2025),
        ],
        check=True,
    )
    print("\n✅ Hoàn tất bước flood features!")


def step_text(args):
    print("\n" + "=" * 60)
    print("BƯỚC 6: TEXT FEATURES → silver.rental_room")
    print("=" * 60 + "\n")

    subprocess.run(
        [sys.executable, str(SRC_DIR / "process" / "text_features.py")],
        check=True,
    )
    print("\n✅ Hoàn tất bước text features!")


def step_export(args):
    print("\n" + "=" * 60)
    print("BƯỚC 7: XUẤT silver.rental_room → data/final/rental_room.csv")
    print("=" * 60 + "\n")

    subprocess.run(
        [sys.executable, str(SRC_DIR / "process" / "export_final.py")],
        check=True,
    )


def step_warehouse(args):
    print("\n" + "=" * 60)
    print("BƯỚC 8: BUILD GOLD → gold.rental_room")
    print("=" * 60 + "\n")

    subprocess.run(
        [sys.executable, str(SRC_DIR / "warehouse" / "load_final.py")],
        check=True,
    )


def step_all(args):
    print("\n" + "=" * 60)
    print("CHẠY TOÀN BỘ PIPELINE (scrape → text)")
    print("=" * 60 + "\n")

    if args.skip_scrape:
        print("⏭️  Bỏ qua bước cào dữ liệu (--skip-scrape)")
    else:
        step_scrape(args)

    step_merge(args)
    step_geocode(args)
    step_spatial(args)
    step_flood(args)
    step_text(args)
    step_warehouse(args)
    step_export(args)

    print("\n" + "=" * 60)
    print("🎉 PIPELINE HOÀN TẤT!")
    print("=" * 60 + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="Pipeline điều khiển quy trình dữ liệu (R2 + PostgreSQL)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ví dụ:
  python scripts/init_db.py
  python main.py --step all
  python main.py --step all --skip-scrape
  python main.py --step scrape
  python main.py --step merge
  python main.py --step geocode
  python main.py --step spatial
  python main.py --step flood
  python main.py --step text
  python main.py --step export
  python main.py --step warehouse
        """,
    )

    parser.add_argument(
        "--step",
        choices=[
            "all",
            "scrape",
            "merge",
            "geocode",
            "spatial",
            "flood",
            "text",
            "export",
            "warehouse",
        ],
        default="all",
        help="Bước pipeline muốn chạy (mặc định: all)",
    )
    parser.add_argument(
        "--skip-scrape",
        action="store_true",
        help="Bỏ qua bước cào (dùng khi payload đã có trong R2 Bronze)",
    )
    parser.add_argument(
        "--flood-geojson-2022",
        type=Path,
        default=BASE_DIR / "notebooks" / "danang_flood_2022.geojson",
        help="GeoJSON vùng ngập 2022 (mặc định: notebooks/danang_flood_2022.geojson)",
    )
    parser.add_argument(
        "--flood-geojson-2025",
        type=Path,
        default=BASE_DIR / "notebooks" / "danang_flood_2025.geojson",
        help="GeoJSON vùng ngập 2025 (mặc định: notebooks/danang_flood_2025.geojson)",
    )

    args = parser.parse_args()
    step_functions = {
        "all": step_all,
        "scrape": step_scrape,
        "merge": step_merge,
        "geocode": step_geocode,
        "spatial": step_spatial,
        "flood": step_flood,
        "text": step_text,
        "export": step_export,
        "warehouse": step_warehouse,
    }
    step_functions[args.step](args)


if __name__ == "__main__":
    main()
