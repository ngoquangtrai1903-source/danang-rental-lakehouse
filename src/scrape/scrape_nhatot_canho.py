import time
import requests
from datetime import datetime

try:
    from incremental import (
        load_existing_payload_ids,
        now_scraped_at,
        save_payloads,
    )
    from furnishing_fallback import infer_furnishing_status, is_unknown_furnishing_status
except ImportError:
    from src.scrape.incremental import (
        load_existing_payload_ids,
        now_scraped_at,
        save_payloads,
    )
    from src.scrape.furnishing_fallback import (
        infer_furnishing_status,
        is_unknown_furnishing_status,
    )

SOURCE_NAME = "nhatot_canho"

# ==========================================
# 1. CẤU HÌNH PIPELINE
# ==========================================
HEADERS = {
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "accept": "application/json, text/plain, */*",
    "referer": "https://nhatot.com",
}


# ==========================================
# 2. HÀM BIẾN ĐỔI DỮ LIỆU (TRANSFORM)
# ==========================================
def process_ad_data(ad):
    """
    Hàm này nhận JSON thô của 1 bài đăng và trả về 1 Dictionary phẳng (Flat),
    chỉ giữ lại các thuộc tính có giá trị phân tích và đã được làm sạch.
    """
    # 1. Xử lý thời gian
    list_time_ms = ad.get("list_time", 0)
    posted_date = datetime.fromtimestamp(list_time_ms / 1000).strftime('%Y-%m-%d') if list_time_ms else ""

    orig_time_ms = ad.get("orig_list_time", 0)
    created_date = datetime.fromtimestamp(orig_time_ms / 1000).strftime('%Y-%m-%d') if orig_time_ms else ""

    # 2. Xử lý tính năng (Feature Params) an toàn
    feature_params = ad.get("feature_params", {})

    # Khởi tạo giá trị mặc định (tránh lỗi UnboundLocalError)
    furnishing_status = "Không xác định"
    rooms = "Không xác định"

    # Quét qua cả 2 nhóm compare và seo_structure cho chắc chắn
    for group in ['seo_structure', 'compare']:
        items = feature_params.get(group, {}).get('items', [])
        for item in items:
            if item.get('id') == 'furnishing_sell':
                furnishing_status = item.get('value')
            elif item.get('id') == 'rooms':
                rooms = item.get('value')

    # 3. Làm sạch Text
    clean_subject = str(ad.get("subject", "")).replace('\n', ' ').replace('\r', '').strip()
    clean_body = str(ad.get("body", "")).replace('\n', ' ').replace('\r', '').strip()
    if is_unknown_furnishing_status(furnishing_status):
        inferred_furnishing_status = infer_furnishing_status(
            clean_subject,
            clean_body,
        )
        if inferred_furnishing_status is not None:
            furnishing_status = inferred_furnishing_status

    # 4. Trích xuất dữ liệu thô ban đầu
    price = ad.get("price", 0)
    size = ad.get("size", 0)
    price_per_m2 = ad.get("price_million_per_m2", 0.0)

    # 5. Logic bù trừ chéo (Mutual Imputation)
    if price > 0:
        if size == 0 and price_per_m2 > 0:
            size = round((price / 1000000) / price_per_m2)
        elif price_per_m2 == 0 and size > 0:
            price_per_m2 = round((price / 1000000) / size, 6)

    return {
        "list_id": ad.get("list_id", ""),
        "posted_date": posted_date,


        "price_vnd": price,
        "size_m2": size,
        "price_per_m2_vnd": round(price_per_m2 * 1_000_000, 0),

        "furnishing_status": furnishing_status,
        "rooms": rooms,  # Thêm số phòng ngủ
        "category_name": ad.get("category_name", ""),

        "latitude": ad.get("latitude", ""),
        "longitude": ad.get("longitude", ""),
        "ward_name": ad.get("ward_name_v3", ""),
        "street_name": ad.get("street_name", ""),

        "subject": clean_subject,
        "body": clean_body
    }


# ==========================================
# 3. HÀM CHẠY PIPELINE (EXTRACT & LOAD)
# ==========================================
def run_data_pipeline(total_pages=5, source=SOURCE_NAME, stop_on_known=True, stale_page_limit=3):
    limit = 20
    raw_payloads = []
    existing_ids = load_existing_payload_ids(source)
    stale_pages = 0

    print(f"🚀 KHỞI ĐỘNG PIPELINE CÀO DỮ LIỆU NHÀ TỐT → R2 Bronze[{source}] (Mục tiêu: {total_pages} trang)")

    for page in range(1, total_pages + 1):
        offset = (page - 1) * limit
        print(f"📥 Đang thu thập Trang {page}/{total_pages}...")

        url = (
            f"https://gateway.chotot.com/v1/public/ad-listing?"
            f"region_v2=3017&cg=1010&st=u,h&w=1"
            f"&o={offset}&page={page}&limit={limit}"
            f"&fingerprint=1037883d-3704-4529-a95a-a2c184364295"
            f"&include_expired_ads=true&key_param_included=true"
            f"&video_count_included=true&seo_title_included=true"
        )

        try:
            response = requests.get(url, headers=HEADERS, timeout=10)

            if response.status_code == 200:
                ads_list = response.json().get("ads", [])

                if not ads_list:
                    print("⚠️ Không còn dữ liệu để cào. Kết thúc vòng lặp.")
                    break

                page_new_count = 0
                page_ids = []
                for ad in ads_list:
                    list_id = str(ad.get("list_id", "")).strip()
                    page_ids.append(list_id)
                    if not list_id or list_id in existing_ids:
                        continue
                    scraped_at = now_scraped_at()
                    raw_payloads.append(
                        {
                            "list_id": list_id,
                            "payload_format": "json",
                            "payload": ad,
                            "source_url": ad.get("url") or ad.get("link"),
                            "scraped_at": scraped_at,
                        }
                    )
                    existing_ids.add(list_id)
                    page_new_count += 1

                if page_new_count == 0 and page_ids and all(
                    list_id in existing_ids for list_id in page_ids if list_id
                ):
                    stale_pages += 1
                    if stop_on_known and stale_pages >= stale_page_limit:
                        print(f"⏹️ {stale_pages} trang liên tiếp chỉ có tin cũ. Dừng sớm.")
                        break
                else:
                    stale_pages = 0

            else:
                print(f"❌ Lỗi HTTP {response.status_code} tại trang {page}. Bỏ qua trang này.")

        except Exception as e:
            print(f"❌ Lỗi hệ thống tại trang {page}: {e}")

        # Nghỉ 2 giây để tránh bị ban IP
        time.sleep(2)

    inserted = save_payloads(source, raw_payloads)
    if inserted:
        print(f"\n✅ PIPELINE HOÀN TẤT! Đã thêm {inserted} payload mới vào R2 Bronze[{source}]")
    else:
        print("\nℹ️ Không có payload mới; các payload đã lưu được giữ nguyên.")


# ==========================================
# CHẠY CHƯƠNG TRÌNH
# ==========================================
if __name__ == "__main__":
    # Thay đổi số trang muốn cào tại đây (Ví dụ: 10, 50, 100)
    run_data_pipeline(total_pages=61)