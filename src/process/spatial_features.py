# -*- coding: utf-8 -*-
"""
Tính đặc trưng không gian (spatial features) từ latitude/longitude
Sử dụng công thức Haversine để tính khoảng cách giữa 2 điểm trên Trái Đất.

Logic từ notebooks/main.ipynb cell 12
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.db import processed_repo


# ============================================================================
# 1. CÔNG THỨC HAVERSINE (Tính khoảng cách giữa 2 toạ độ)
# ============================================================================
def haversine_vectorized(lat1, lon1, lat2, lon2):
    """
    Tính khoảng cách (km) giữa 2 điểm bằng công thức Haversine.
    Vectorized để tính nhanh trên toàn bộ DataFrame.
    """
    # Chuyển đổi sang radians
    lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])
    
    # Công thức Haversine
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat/2)**2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon/2)**2
    c = 2 * np.arcsin(np.sqrt(a))
    
    # Bán kính Trái Đất (km)
    R = 6371
    return c * R

# ============================================================================
# 2. TOẠ ĐỘ CÁC ĐIỂM THAM CHIẾU (Reference Points) - UPDATED & ACCURATE
# ============================================================================

# Trung tâm thành phố Đà Nẵng (CBD) - Cầu Rồng / Nguyễn Văn Linh
CBD_COORDS = (16.0610, 108.2230)

# Các bãi biển Đà Nẵng và lân cận dùng để tính khoảng cách tới bãi gần nhất.
BEACHES = {
    # Quanh bán đảo Sơn Trà
    "TienSa": (16.1264, 108.2435),
    "BaiBac": (16.1221, 108.2825),
    "BaiBut_BaiRang": (16.1018, 108.2762),
    # Tuyến biển du lịch phía Đông
    "PhamVanDong": (16.0746, 108.2482),
    "MyKhe": (16.0652, 108.2471),
    "BacMyAn": (16.0398, 108.2523),
    "SonThuy": (16.01627344969784, 108.26275388058494),
    "NonNuoc": (15.995852110443508, 108.27384535559464),
    # Tuyến biển vịnh Đà Nẵng
    "ThanhBinh": (16.07340142742003, 108.20052576741917),
    "XuanThieu": (16.1042, 108.1631),
    "NamO": (16.1241, 108.1223),
    "LangVan": (16.1648, 108.1252),
}

# Sân bay Quốc tế Đà Nẵng (Nhà ga hành khách)
AIRPORT_COORDS = (16.0439, 108.1994)

# Bounding box Đà Nẵng (min_lat, min_lng, max_lat, max_lng)
DA_NANG_BBOX = (15.85, 107.85, 16.30, 108.35)

# Các trường Đại học tại Đà Nẵng (Toạ độ cổng chính / khuôn viên thực tế)
UNIVERSITIES = {
    # --- Trường Đại học Đà Nẵng & Các trường thành viên ---
    'DUE': (16.0478, 108.2400),     # ĐH Kinh tế - 71 Ngũ Hành Sơn
    'DUT': (16.0738, 108.1499),     # ĐH Bách Khoa - 54 Nguyễn Lương Bằng, Hòa Khánh
    'UTE': (16.0604, 108.2140),     # ĐH Sư Phạm Kỹ Thuật - 48 Cao Thắng, Hải Châu (mã chuẩn UTE, cũ ghi DHN)
    'UFLS': (16.0319, 108.2198),    # ĐH Ngoại Ngữ - 131 Lương Nhữ Hộc, Cẩm Lệ (mã chuẩn UFLS)
    'UED': (16.0612, 108.1583),     # ĐH Sư Phạm - 459 Tôn Đức Thắng, Liên Chiểu (mã chuẩn UED)
    'VKU': (15.9753, 108.2524),     # ĐH CNTT & Truyền thông Việt - Hàn - Làng ĐH Hòa Quý (mã chuẩn VKU, cũ ghi DUS)
    'VNUK': (16.0776, 108.2201),    # Viện Nghiên cứu & Đào tạo Việt - Anh - 158A Lê Lợi, Hải Châu
    'SMP': (15.9752, 108.2523),     # Khoa Y Dược - ĐH Đà Nẵng - Làng ĐH Hòa Quý

    # --- Các Trường Đại học Tư thục & Quốc tế ---
    'FPTU': (15.9688, 108.2605),    # ĐH FPT Đà Nẵng - Khu đô thị FPT City, Ngũ Hành Sơn
    'DTU_NVL': (16.0602, 108.2098), # ĐH Duy Tân - Cơ sở 254 Nguyễn Văn Linh
    'DTU_HK': (16.0822, 108.1472),  # ĐH Duy Tân - Cơ sở Hòa Khánh (03 Nam Cao)
    'DAU': (16.0327, 108.2206),     # ĐH Kiến Trúc Đà Nẵng - 566 Núi Thành, Hải Châu
    'UDA': (16.0322, 108.2189),     # ĐH Đông Á - 339 Nguyễn Hữu Thọ, Hải Châu
    'UPU': (15.9741, 108.2561),     # ĐH Phan Châu Trinh - KĐT Nam Đà Nẵng
    'UPES3': (16.0682, 108.1831),   # ĐH Thể dục Thể thao Đà Nẵng - 44 Dũng Sĩ Thanh Khê
}

# ============================================================================
# 3. VALIDATE TỌA ĐỘ
# ============================================================================
def validate_coords(df, lat_col="latitude", lon_col="longitude", bbox=DA_NANG_BBOX):
    """Ép kiểu số cho lat/lng, loại (gán NaN) cho giá trị không phải số
    hoặc nằm ngoài bounding-box Đà Nẵng - tránh tính khoảng cách từ tọa độ
    lỗi/geocode sai. Trả về (lat, lon, n_invalid_numeric, n_out_of_bbox)."""
    lat = pd.to_numeric(df[lat_col], errors="coerce")
    lon = pd.to_numeric(df[lon_col], errors="coerce")

    min_lat, min_lon, max_lat, max_lon = bbox
    in_bbox = lat.between(min_lat, max_lat) & lon.between(min_lon, max_lon)

    n_invalid_numeric = int((lat.isna() | lon.isna()).sum())
    n_out_of_bbox = int((~in_bbox & lat.notna() & lon.notna()).sum())

    lat = lat.where(in_bbox)
    lon = lon.where(in_bbox)

    return lat, lon, n_invalid_numeric, n_out_of_bbox


# ============================================================================
# 4. SCRIPT XỬ LÝ VÀ TRÍCH XUẤT ĐẶC TRƯNG KHÔNG GIAN
# ============================================================================
def process_spatial_features(df: pd.DataFrame, verbose=True) -> pd.DataFrame:
    for col in ("latitude", "longitude"):
        if col not in df.columns:
            raise KeyError(f"Dataset đầu vào thiếu cột bắt buộc: '{col}'")

    lat, lon, n_invalid, n_out_bbox = validate_coords(df)
    df = df.copy()
    df["latitude"], df["longitude"] = lat, lon

    if verbose:
        print(f"ℹ️  Tổng {len(df)} dòng.")
        if n_invalid:
            print(f"⚠️  {n_invalid} dòng có latitude/longitude rỗng hoặc không phải số.")
        if n_out_bbox:
            print(
                f"⚠️  {n_out_bbox} dòng có toạ độ NẰM NGOÀI phạm vi Đà Nẵng "
                f"(bbox={DA_NANG_BBOX}) -> bị loại khỏi tính khoảng cách để "
                f"tránh tạo feature sai lệch lớn."
            )

    df["dist_to_cbd"] = haversine_vectorized(
        df["latitude"], df["longitude"], CBD_COORDS[0], CBD_COORDS[1]
    ).round(3)

    beach_distances = {
        beach_code: haversine_vectorized(
            df["latitude"], df["longitude"], beach_lat, beach_lon
        )
        for beach_code, (beach_lat, beach_lon) in BEACHES.items()
    }
    beach_distances_df = pd.DataFrame(beach_distances, index=df.index)
    df["dist_to_beach"] = beach_distances_df.min(axis=1).round(3)

    has_any_valid_beach = beach_distances_df.notna().any(axis=1)
    nearest_beach = pd.Series(index=df.index, dtype=object)
    if has_any_valid_beach.any():
        nearest_beach.loc[has_any_valid_beach] = beach_distances_df.loc[
            has_any_valid_beach
        ].idxmin(axis=1)
    df["nearest_beach_code"] = nearest_beach

    df["dist_to_airport"] = haversine_vectorized(
        df["latitude"], df["longitude"], AIRPORT_COORDS[0], AIRPORT_COORDS[1]
    ).round(3)

    uni_dist_dict = {}
    for uni_code, (u_lat, u_lng) in UNIVERSITIES.items():
        uni_dist_dict[uni_code] = haversine_vectorized(
            df["latitude"], df["longitude"], u_lat, u_lng
        )

    uni_df = pd.DataFrame(uni_dist_dict, index=df.index)
    df["dist_to_nearest_uni"] = uni_df.min(axis=1).round(3)

    has_any_valid = uni_df.notna().any(axis=1)
    nearest_uni = pd.Series(index=df.index, dtype=object)
    if has_any_valid.any():
        nearest_uni.loc[has_any_valid] = uni_df.loc[has_any_valid].idxmin(axis=1)
    df["nearest_uni_code"] = nearest_uni

    if verbose:
        n_null_dist = int(df["dist_to_nearest_uni"].isna().sum())
        pct = (n_null_dist / len(df) * 100) if len(df) else 0.0
        print(
            f"\n📊 Số dòng KHÔNG tính được khoảng cách (do thiếu/sai toạ độ): "
            f"{n_null_dist}/{len(df)} ({pct:.1f}%)"
        )

    processed_repo.rebuild_spatial(df)
    if verbose:
        print(f"\n✅ Đã xử lý xong {len(df)} bản ghi.")
        print("📁 Đã ghi: silver.spatial")

    return df


def main():
    parser = argparse.ArgumentParser(
        description="Tính đặc trưng không gian (khoảng cách haversine) từ latitude/longitude"
    )
    parser.add_argument("--quiet", action="store_true", help="Tắt bớt log chi tiết")
    args, _unknown = parser.parse_known_args()

    print("📥 Đang đọc silver.geocoded...")
    df = processed_repo.fetch_geocoded()
    if df.empty:
        raise SystemExit("❌ silver.geocoded trống. Chạy bước geocode trước.")

    df_result = process_spatial_features(df, verbose=not args.quiet)

    print("\n--- MẪU KẾT QUẢ ĐẶC TRƯNG KHÔNG GIAN ---")
    cols_to_show = [
        "latitude",
        "longitude",
        "dist_to_cbd",
        "dist_to_beach",
        "nearest_beach_code",
        "dist_to_nearest_uni",
        "nearest_uni_code",
    ]
    print(df_result[cols_to_show].head())


if __name__ == "__main__":
    main()
