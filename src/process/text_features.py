# -*- coding: utf-8 -*-
"""
Đọc silver.spatial, trích xuất đặc trưng nhị phân từ subject/body,
ghi silver.rental_room (PostgreSQL).

    has_balcony, free_hours, has_camera_security, has_elevator,
    has_mezzanine, private_bathroom, wifi, has_parking, has_window
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.db import final_repo, processed_repo


# ============================================================================
# BỘ PATTERN CHO TỪNG ĐẶC TRƯNG (rút ra từ các mẫu body thực tế)
# Mỗi pattern là 1 regex (đã lowercase, so khớp trên text đã lowercase).
# ============================================================================
FEATURE_PATTERNS = {
    # "Ban công rộng", "có ban công, lối đi riêng", "Ban công nhìn xuống đường",
    # "lô gia riêng" (thuật ngữ kiến trúc tương đương ban công), tin song ngữ "balcony"
    "has_balcony": [
        r"ban\s*c[oôố]ng",
        r"l[oô]\s*gia",
        r"balcony",
    ],

    # "Giờ giấc tự do" và rất nhiều biến thể: có từ chen giữa ("giờ giấc đi
    # lại tự do"), không có chữ "giấc" ("giờ tự do"), thứ tự đảo ngược,
    # giọng Nam/Trung ("ra vô thỏa mái"), và các cụm phủ định-giới hạn
    # ("không giới hạn/gò bó/khống chế giờ giấc").
    "free_hours": [
        r"gi[oờ]\s*gi[aấ]c.{0,20}(t[uự]\s*do|thoải\s*mái|thỏa\s*mái|tự\s*chủ|tự\s*quản|linh\s*hoạt)",
        r"(t[uự]\s*do|thoải\s*mái|thỏa\s*mái|linh\s*hoạt).{0,20}gi[oờ]\s*gi[aấ]c",
        r"gi[oờ].{0,15}t[uự]\s*do",
        r"t[uự]\s*do.{0,15}gi[oờ]",
        r"ra\s*v[aàô]o?\s*(t[uự]\s*do|thoải\s*mái|thỏa\s*mái)",
        r"(t[uự]\s*do|thoải\s*mái).{0,10}ra\s*v[aàô]o?",
        r"kh[oô]ng\s*(giới\s*hạn|quy\s*định|gò\s*bó|khống\s*chế|giới\s*nghiêm)",
    ],

    # "camera", "cam an ninh", emoji 📹
    "has_camera_security": [
        r"camera",
        r"📹",
        r"\bcam\b\s*an\s*ninh",
        r"an\s*ninh\s*camera",
    ],

    # "Có thang máy", emoji 🛗 (nhiều tin CHỈ dùng emoji, không kèm chữ)
    "has_elevator": [
        r"thang\s*m[aá]y",
        r"🛗",
        r"\belevator\b",
    ],

    # "gác lửng"/"gác lững" (2 cách viết đều phổ biến), "gác xép", "gác đúc",
    # "gác gỗ", "duplex" (kiểu phòng gác lửng), "có gác", fallback từ "gác"
    # đơn lẻ (rủi ro thấp vì tiếng Việt tách âm tiết bằng khoảng trắng nên
    # không lẫn vào từ khác)
    "has_mezzanine": [
        r"g[aá]c\s*l[uửữ]ng",
        r"g[aá]c\s*x[eé]p",
        r"g[aá]c\s*đúc",
        r"g[aá]c\s*g[oỗ]",
        r"s[aà]n\s*l[uửữ]ng",
        r"duplex",
        r"\bc[oó]\s*g[aá]c\b",
        r"ph[oò]ng\s*g[aá]c\b",
        r"\bg[aá]c\b",
    ],

    # "WC riêng", "vệ sinh riêng", "khép kín", "NVS riêng" (viết tắt Nhà Vệ
    # Sinh), "WC độc lập", "toilét riêng" (biến thể chính tả), "wc ... trong
    # phòng" (cho phép từ chen giữa như "wc ngay trong phòng")
    "private_bathroom": [
        r"(wc|vệ\s*sinh|toilet|toilét|nh[aà]\s*vệ\s*sinh|nvs)\s*(riêng|độc\s*lập)",
        r"khép\s*k[ií]n",
        r"(wc|vệ\s*sinh|toilet|nvs)\s*.{0,6}trong\s*(ph[oò]ng|bếp)",
        r"ph[oò]ng\s*vệ\s*sinh\s*trong",
        r"c[oô]ng\s*tr[iì]nh\s*vệ\s*sinh\s*khép\s*k[ií]n",
    ],

    # "Wifi", "Wi-Fi", viết tắt "wf", "internet" (thường dùng thay thế)
    "wifi": [
        r"wi[\s\-]?fi",
        r"\bwf\b",
        r"internet",
    ],

    # "Chỗ để xe", "bãi để xe", "gửi xe"/"giữ xe", "nhà xe" (cụm ghép không
    # chứa để/đậu/đỗ nhưng rất phổ biến), cả 2 thứ tự "đậu xe"/"xe đậu"
    "has_parking": [
        r"ch[oổỗ]\s*(để|đậu|đỗ)\s*xe",
        r"b[aã]i\s*(để|đậu|đỗ)?\s*xe",
        r"g[uử]i\s*xe",
        r"gi[uữ]\s*xe",
        r"nh[aà]\s*xe",
        r"(để|đậu|đỗ)\s*(được\s*)?(xe|[oô]\s*t[oô])",
        r"([oô]\s*t[oô]|xe)\s*(để|đậu|đỗ)",
        r"\bparking\b",
    ],

    # "cửa sổ", "cửa kính" (kèm ánh sáng tự nhiên), "giếng trời" (skylight,
    # tương đương cửa sổ lấy sáng), tin song ngữ "window"
    "has_window": [
        r"c[uử]a\s*s[oổ]",
        r"c[uử]a\s*k[ií]nh",
        r"gi[eế]ng\s*tr[oờ]i",
        r"window",
    ],
}

# Các từ phủ định đứng ngay trước từ khóa sẽ khiến match đó bị BỎ QUA
# (vd "không có wifi" sẽ không tính wifi=True từ chính cụm đó)
NEGATION_RE = re.compile(r"(kh[oô]ng|ko|chưa|hết)\s*(c[oó])?\s*$")


def safe_text(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    return str(v).strip()


def contains_pattern(text_lower, patterns, negation_window=15):
    """True nếu có ít nhất 1 pattern khớp trong text VÀ không bị phủ định
    ngay trước đó (vd 'không có wifi' sẽ không tính là wifi=True)."""
    for pat in patterns:
        for m in re.finditer(pat, text_lower):
            start = max(0, m.start() - negation_window)
            context_before = text_lower[start:m.start()]
            if NEGATION_RE.search(context_before):
                continue  # bị phủ định ngay trước -> bỏ qua match này
            return True
    return False


def extract_features(subject, body):
    combined = f"{safe_text(subject)} {safe_text(body)}".lower()
    return {
        feature: contains_pattern(combined, patterns)
        for feature, patterns in FEATURE_PATTERNS.items()
    }


def main():
    print("📥 Đang đọc silver.spatial...")
    df = processed_repo.fetch_spatial()
    if df.empty:
        raise SystemExit("❌ silver.spatial trống. Chạy bước spatial trước.")

    for col in ("subject", "body"):
        if col not in df.columns:
            raise KeyError(f"Dataset đầu vào thiếu cột bắt buộc: '{col}'")

    print(f"ℹ️  Đang trích xuất đặc trưng cho {len(df)} dòng...")

    feature_rows = [
        extract_features(row.get("subject"), row.get("body"))
        for _, row in df.iterrows()
    ]
    feature_df = pd.DataFrame(feature_rows, index=df.index)

    for col in feature_df.columns:
        df[col] = feature_df[col]

    # duplicate_mask = df.duplicated(subset=["latitude", "longitude"], keep="first")
    # price = pd.to_numeric(df["price_vnd"], errors="coerce")
    # size = pd.to_numeric(df["size_m2"], errors="coerce")
    # condition = (size <= 100) & (price >= 500000) & (~duplicate_mask)
    # df = df[condition].copy()

    final_repo.rebuild_rental_room(df)

    print("\n✅ Đã lưu kết quả vào: silver.rental_room")
    print("\n📊 Tỷ lệ True theo từng đặc trưng:")
    for col in FEATURE_PATTERNS:
        n_true = int(df[col].sum())
        pct = n_true / len(df) * 100 if len(df) else 0
        print(f"   {col:<22} {n_true:>6}/{len(df)} ({pct:5.1f}%)")


if __name__ == "__main__":
    main()
