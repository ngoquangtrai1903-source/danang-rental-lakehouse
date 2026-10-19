"""Apply the unchanged warehouse transformation and rebuild the Gold table."""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.db import final_repo
from src.warehouse.repository import replace_rental_room_current
from src.warehouse.transform import transform_lake_final


def load_final_to_warehouse() -> dict[str, int]:
    """Apply the existing transform and atomically rebuild Gold."""
    silver_df = final_repo.fetch_rental_room()
    if silver_df.empty:
        raise ValueError(
            "Silver rental_room is empty; refusing to replace the Gold "
            "table with an empty dataset."
        )
    gold_df, stats = transform_lake_final(silver_df)
    if gold_df.empty:
        raise ValueError(
            "No Silver rental_room rows passed the existing Gold filters; "
            "refusing to replace Gold with an empty dataset."
        )
    loaded_rows = replace_rental_room_current(gold_df)
    if loaded_rows != stats["loaded_rows"]:
        raise RuntimeError(
            "Gold row count mismatch after load: "
            f"expected {stats['loaded_rows']}, got {loaded_rows}."
        )
    print(
        "Gold load complete: "
        f"source={stats['source_rows']}, "
        f"filtered_price_size={stats['rejected_invalid_or_zero_price_size']}, "
        f"filtered_category={stats['rejected_unsupported_category']}, "
        f"filtered_ward={stats['rejected_unsupported_or_null_ward']}, "
        f"filtered_coordinates={stats['rejected_missing_or_invalid_coordinates']}, "
        f"filtered_invalid_rooms={stats['rejected_invalid_rooms']}, "
        f"loaded={loaded_rows}."
    )
    return stats


def main() -> None:
    load_final_to_warehouse()


if __name__ == "__main__":
    main()
