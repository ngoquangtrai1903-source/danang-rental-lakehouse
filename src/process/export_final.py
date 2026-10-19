# -*- coding: utf-8 -*-
"""Export the Silver rental-room table from PostgreSQL to CSV."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.db import final_repo

DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "data" / "final" / "rental_room.csv"


def export_final_csv(output_path: Path = DEFAULT_OUTPUT_PATH) -> int:
    """Fetch silver.rental_room and write it as UTF-8-with-BOM CSV."""
    output_path = Path(output_path)
    df = final_repo.fetch_rental_room()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"Exported {len(df)} rows from silver.rental_room: {output_path}")
    return len(df)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Xuất silver.rental_room từ PostgreSQL ra CSV."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Đường dẫn CSV đầu ra (mặc định: data/final/rental_room.csv).",
    )
    args = parser.parse_args()
    export_final_csv(args.output)


if __name__ == "__main__":
    main()
