# -*- coding: utf-8 -*-
"""
Scraper phongtro.vn (2 tầng: trang danh sách -> trang chi tiết)
Xuất đầy đủ các cột:
list_id, posted_date, price_vnd, size_m2, price_per_m2_vnd, furnishing_status,
category_name, latitude, longitude, ward_name, street_name, street_number,
subject, body

Cài đặt thư viện cần thiết:
    pip install cloudscraper beautifulsoup4 pandas geopy

Đã xác nhận thực tế trên phongtro.vn (khác hẳn phongtro123.com):
- URL trang danh sách:  https://phongtro.vn/cho-thue-phong-tro-tp-da-nang-trang-{N}
- URL trang chi tiết:   https://phongtro.vn/{slug-phuong}/{ma-tin-so}
- Breadcrumb trang chi tiết: Cho thuê > Phòng trọ > Thành phố Đà Nẵng >
  Phường XXX > [tiêu đề]  -> lấy được category_name và ward_name trực tiếp,
  rất đáng tin cậy (không phải đoán/label-search như site khác).
- Dòng ngay dưới H1 là địa chỉ ngắn: "trần thủ độ, Điện Bàn Đông, Đà Nẵng".
- Khối "Thông số bất động sản" chứa: Mức giá, Diện tích, Ngày đăng,
  Ngày hết hạn, Loại tin, Mã tin (dạng label/value, KHÔNG phải bảng <table>
  chuẩn mà là danh sách <li> - code dùng nhiều chiến lược để bắt được).
- Ngày đăng ở đây CHỈ có ngày, không có giờ (vd "19/09/2026").
- Không có trường furnishing_status rõ ràng trên trang -> suy ra từ từ khóa
  trong phần mô tả (best-effort).
- KHÔNG có bản đồ nhúng -> latitude/longitude phải geocode từ địa chỉ text.
- Trang danh sách: mỗi tin có nhiều thẻ <a> cùng trỏ về 1 URL chi tiết
  (ảnh, tiêu đề trong <h3>, và 1 link gộp "giá+diện tích+địa chỉ" dạng
  "3.5 triệu20 m² trần thủ độ, Điện Bàn Đông, Đà Nẵng") -> code tận dụng
  link gộp này làm nguồn dự phòng cho price/size/address mà không cần mở
  trang chi tiết, tăng độ chắc chắn dữ liệu.
"""

import cloudscraper
from bs4 import BeautifulSoup
import re
import time
import random

try:
    from incremental import (
        encode_html_payload,
        load_existing_payload_ids,
        now_scraped_at,
        save_payloads,
    )
except ImportError:
    from src.scrape.incremental import (
        encode_html_payload,
        load_existing_payload_ids,
        now_scraped_at,
        save_payloads,
    )

SOURCE_NAME = "phongtro_vn"

# ---------- Cấu hình ----------
BASE = "https://phongtro.vn"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://phongtro.vn/",
}

# Href của tin đăng chi tiết có dạng "/mot-slug-bat-ky/123456" (đúng 2 đoạn,
# đoạn cuối toàn số). Pattern này tự động loại trừ: link phân trang
# (".../trang-2"), link hồ sơ người đăng ("/pa/uuid"), link lọc theo
# giá/diện tích (chỉ 1 đoạn), link email-protection...
DETAIL_HREF_RE = re.compile(r"^/([a-z0-9\-]+)/(\d+)/?$", re.IGNORECASE)

# Text gộp trên card danh sách: "3.5 triệu20 m² <địa chỉ...>"
CARD_TEXT_RE = re.compile(
    r"^\s*([\d.,]+)\s*triệu\s*([\d.,]+)\s*m[²2]\s*(.*)$", re.IGNORECASE
)

SIDEBAR_CUTOFF_HEADINGS = {
    "bất động sản dành cho bạn", "tin đăng liên quan", "có thể bạn quan tâm",
}

FURNISHING_NEGATIVE_PATTERNS = [
    "không có nội thất", "không nội thất", "nhà trống", "phòng trống",
    "chưa có nội thất", "không có sẵn nội thất", "không trang bị nội thất",
]

FURNISHING_LUXURY_PATTERNS = [
    "nội thất cao cấp", "nội thất sang trọng",
    "trang bị nội thất cao cấp", "full nội thất cao cấp", "tiện nghi cao cấp",
]

FURNISHING_FULL_PATTERNS = [
    "đầy đủ nội thất", "đầy đủ tiện nghi", "full nội thất", "full tiện nghi",
    "nội thất đầy đủ", "tiện nghi đầy đủ", "full nt", "fullnoithat",
    "nội thất full", "nội thất và tiện nghi đầy đủ", "tiện nghi và nội thất đầy đủ",
    "trang bị đầy đủ nội thất", "đầy đủ tiện nghi và nội thất", "Nội thất chỉnh chu",
]

FURNISHING_BASIC_PATTERNS = [
    "nội thất cơ bản", "cơ bản nội thất", "nội thất tối thiểu",
]

# Nhãn hay đứng trước danh sách liệt kê đồ nội thất, vd:
# "Nội thất đã có: điều hoà, bình nóng lạnh, sân phơi riêng..."
FURNISHING_LIST_LABELS = [
    r"nội thất(?:\s*đã)?\s*có", r"nội thất\s*gồm", r"trang bị(?:\s*gồm)?",
    r"tiện nghi(?:\s*đã)?\s*có", r"bao gồm nội thất",
]

# Các món đồ cụ thể - nếu xuất hiện đủ nhiều thì suy ra có nội thất dù
# không dùng đúng cụm "đầy đủ nội thất"
FURNITURE_ITEM_KEYWORDS = [
    "điều hòa", "điều hoà", "máy lạnh", "bình nóng lạnh", "nóng lạnh",
    "tủ lạnh", "máy giặt", "giường", "tủ quần áo", "tủ đồ", "bàn ghế",
    "bàn học", "wifi", "gác lửng", "sàn lửng", "sân phơi", "kệ bếp",
    "bếp nấu ăn", "bếp", "nệm", "quạt trần", "quạt", "tivi", " tv ",
    "kệ tủ", "giường ngủ", "tủ bếp", "rèm cửa", "bình nước nóng",
]


def get_furnishing_status(soup, body_text, subject_text=""):
    """Phân loại tình trạng nội thất theo nhiều tầng, quét trên cả subject
    lẫn body lẫn thuộc tính icon (title/aria-label/alt):
    1) Ưu tiên nhận diện phủ định ("không nội thất"...) trước tiên, vì
       nếu quét từ khóa dương tính trước sẽ dính oan do "không nội thất"
       vẫn chứa chữ "nội thất".
    2) Cụm khẳng định đầy đủ ("đầy đủ nội thất/tiện nghi", "full nội
       thất"...) - bộ từ khóa mở rộng nhiều biến thể.
    3) Cụm "cơ bản".
    4) Liệt kê món đồ cụ thể (vd "Nội thất đã có: điều hoà, bình nóng
       lạnh, sàn lửng gỗ công nghiệp, wifi...") - đếm số món nhận diện
       được để suy ra mức độ (>=3 món -> Đầy đủ, 1-2 món -> Cơ bản).
    """
    haystack_parts = [body_text or "", subject_text or ""]
    for el in soup.find_all(True, limit=300):
        for attr in ("title", "aria-label", "alt"):
            v = el.get(attr)
            if v:
                haystack_parts.append(v)
    combined = " ".join(haystack_parts).lower()
    # chuẩn hoá khoảng trắng để regex liệt kê hoạt động ổn định
    combined_norm = re.sub(r"\s+", " ", combined)

    for p in FURNISHING_NEGATIVE_PATTERNS:
        if p in combined_norm:
            return "Không nội thất"

    for p in FURNISHING_LUXURY_PATTERNS:
        if p in combined_norm:
            return "Nội thất cao cấp"

    for p in FURNISHING_FULL_PATTERNS:
        if p in combined_norm:
            return "Đầy đủ nội thất"

    for p in FURNISHING_BASIC_PATTERNS:
        if p in combined_norm:
            return "Cơ bản"

    # Liệt kê món đồ sau nhãn kiểu "Nội thất đã có: ..."
    list_text = None
    for label_pattern in FURNISHING_LIST_LABELS:
        m = re.search(label_pattern + r"\s*[:\-]?\s*(.+)", combined_norm)
        if m:
            list_text = m.group(1)[:300]  # giới hạn độ dài để tránh dính cả đoạn mô tả dài phía sau
            break

    scan_text = list_text if list_text else combined_norm
    matched_items = {kw for kw in FURNITURE_ITEM_KEYWORDS if kw in scan_text}

    if len(matched_items) >= 8:
        return "Nội thất cao cấp"
    elif len(matched_items) >= 5:
        return "Đầy đủ nội thất"
    elif len(matched_items) >= 2:
        return "Cơ bản"

    return None


# ---------- Helper: HTTP ----------
def make_scraper():
    return cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "windows", "desktop": True}
    )


def fetch(scraper, url, retries=3, timeout=20):
    for attempt in range(retries):
        try:
            res = scraper.get(url, headers=HEADERS, timeout=timeout)
            if res.status_code == 200:
                soup = BeautifulSoup(res.text, "html.parser")
                setattr(soup, "_raw_html_payload", res.text)
                return soup
            else:
                print(f"  ⚠️ HTTP {res.status_code} tại {url} (lần {attempt+1})")
        except Exception as e:
            print(f"  ⚠️ Lỗi fetch {url}: {e} (lần {attempt+1})")
        time.sleep(2 + attempt)
    return None


# ---------- Helper: Parse tiền / diện tích (tái sử dụng cho cả 2 nguồn) ----------
def parse_price_vnd(text):
    if not text:
        return None
    text = text.strip()
    if "thỏa thuận" in text.lower():
        return None

    m = re.search(r"([\d]+(?:[.,]\d+)?)\s*triệu", text, re.IGNORECASE)
    if m:
        return round(float(m.group(1).replace(",", ".")) * 1_000_000)

    m = re.search(r"([\d]+(?:[.,]\d+)?)\s*tỷ", text, re.IGNORECASE)
    if m:
        return round(float(m.group(1).replace(",", ".")) * 1_000_000_000)

    m = re.search(r"([\d]+(?:[.,]\d+)?)\s*nghìn", text, re.IGNORECASE)
    if m:
        return round(float(m.group(1).replace(",", ".")) * 1_000)

    m = re.search(r"([\d][\d.,]*)\s*(?:đồng|vnd|đ)\b", text, re.IGNORECASE)
    if m:
        digits = re.sub(r"[.,]", "", m.group(1))
        if digits.isdigit():
            return int(digits)

    return None


def parse_size_m2(text):
    if not text:
        return None
    m = re.search(r"([\d]+(?:[.,]\d+)?)\s*m[²2]", text, re.IGNORECASE)
    if m:
        return float(m.group(1).replace(",", "."))
    return None


def parse_card_text(text):
    """Parse chuỗi gộp trên trang danh sách: '3.5 triệu20 m² <địa chỉ>'."""
    if not text:
        return None, None, None
    m = CARD_TEXT_RE.match(text.strip())
    if not m:
        return None, None, None
    price = round(float(m.group(1).replace(",", ".")) * 1_000_000)
    size = float(m.group(2).replace(",", "."))
    address = m.group(3).strip()
    return price, size, address


def parse_address_vn(address_text, known_ward=None):
    """Tách ward_name / street_name / street_number từ chuỗi kiểu
    'trần thủ độ, Điện Bàn Đông, Đà Nẵng' hoặc
    '45, Đường Đinh Công Tráng, Hải Châu, Đà Nẵng'.
    known_ward (lấy từ breadcrumb) được ưu tiên hơn vì đáng tin cậy hơn."""
    ward_name = known_ward
    street_name = street_number = None
    if not address_text:
        return ward_name, street_name, street_number

    parts = [p.strip() for p in address_text.split(",") if p.strip()]
    if not parts:
        return ward_name, street_name, street_number

    # Bỏ thành phố ở cuối (luôn là phần tử cuối cùng, vd "Đà Nẵng")
    remain = parts[:-1] if len(parts) >= 2 else parts

    if remain:
        ward_candidate = remain[-1]
        street_parts = remain[:-1]
    else:
        ward_candidate, street_parts = None, []

    if not ward_name and ward_candidate:
        ward_name = re.sub(
            r"^(phường|xã|thị trấn|quận|huyện)\s+", "", ward_candidate,
            flags=re.IGNORECASE,
        ).strip()

    if street_parts:
        street_text = ", ".join(street_parts).strip()
        m = re.match(r"^(\d+[A-Za-z]?(?:/\d+[A-Za-z]?)*)\s*,?\s*(.*)$", street_text)
        if m and m.group(2):
            street_number = m.group(1)
            street_text = m.group(2)
        street_name = re.sub(
            r"^(đường|phố|ngõ|hẻm|kiệt|lô)\s+", "", street_text, flags=re.IGNORECASE
        ).strip() or None

    return ward_name, street_name, street_number


# ---------- Helper: tìm nội dung theo heading ----------
def get_section_after_heading(soup, heading_text):
    heading = None
    for tag in soup.find_all(re.compile(r"^h[1-6]$")):
        if tag.get_text(strip=True).lower() == heading_text.lower():
            heading = tag
            break
    if not heading:
        return ""

    parts = []
    for sib in heading.find_next_siblings():
        if sib.name and re.match(r"^h[1-6]$", sib.name):
            break
        txt = sib.get_text("\n", strip=True)
        if txt:
            parts.append(txt)

    if parts:
        return "\n".join(parts).strip()

    parent = heading.find_parent(["div", "section"])
    if parent:
        full = parent.get_text("\n", strip=True)
        return full.replace(heading.get_text(strip=True), "", 1).strip()

    return ""


def get_labeled_values(soup, labels_wanted):
    """Bắt cặp nhãn:giá trị theo nhiều chiến lược (bền vững trước thay đổi
    CSS vì dựa trên TEXT nhãn thật, không dựa trên class đoán mò):
    1) <table><tr><td>label</td><td>value</td></tr>
    2) <dl><dt>label</dt><dd>value</dd>
    3) <li> có nhiều dòng text, dòng đầu là nhãn, phần còn lại là giá trị
       (khớp với cấu trúc "Thông số bất động sản" của phongtro.vn)
    4) fallback: regex "label: value" trên toàn bộ text trang
    """
    data = {}

    for tr in soup.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        if len(cells) >= 2:
            label = cells[0].get_text(strip=True).rstrip(":").lower()
            if label in labels_wanted and label not in data:
                data[label] = cells[1].get_text(" ", strip=True)

    if len(data) < len(labels_wanted):
        for dt in soup.find_all("dt"):
            label = dt.get_text(strip=True).rstrip(":").lower()
            dd = dt.find_next_sibling("dd")
            if label in labels_wanted and dd and label not in data:
                data[label] = dd.get_text(" ", strip=True)

    if len(data) < len(labels_wanted):
        for li in soup.find_all("li"):
            texts = [t.strip() for t in li.stripped_strings if t.strip()]
            if len(texts) >= 2:
                label = texts[0].rstrip(":").lower()
                if label in labels_wanted and label not in data:
                    data[label] = " ".join(texts[1:]).strip()

    if len(data) < len(labels_wanted):
        full_text = soup.get_text("\n", strip=True)
        for label in labels_wanted:
            if label in data:
                continue
            m = re.search(
                re.escape(label) + r"\s*:?\s*\n?\s*(.+)", full_text, re.IGNORECASE
            )
            if m:
                data[label] = m.group(1).split("\n")[0].strip()

    return data


def get_breadcrumb(soup):
    """Lấy breadcrumb dạng list text, bỏ qua các <li> rỗng (icon phân
    cách). Vd: ['Cho thuê','Phòng trọ','Thành phố Đà Nẵng',
    'Phường Điện Bàn Đông','<tiêu đề>']"""
    for ol in soup.find_all("ol"):
        items = [li.get_text(strip=True) for li in ol.find_all("li")]
        items = [t for t in items if t]
        if len(items) >= 3:
            return items
    return []


# ---------- Cào trang danh sách ----------
def get_relative_path(href):
    if href.startswith(BASE):
        href = href[len(BASE):]
    return href


def collect_valid_anchors(soup):
    """Duyệt DOM theo thứ tự tài liệu, dừng khi gặp heading đánh dấu khối
    'gợi ý sitewide' để không lẫn dữ liệu không liên quan."""
    valid = []
    for el in soup.find_all(True):
        if el.name in ("h1", "h2", "h3", "h4", "h5", "h6"):
            if el.get_text(strip=True).lower() in SIDEBAR_CUTOFF_HEADINGS:
                break
        if el.name == "a" and el.get("href"):
            valid.append(el)
    return valid


def collect_post_links(scraper, category_slug="cho-thue-phong-tro",
                        city_url_slug="tp-da-nang", total_pages=5):
    """Trả về dict {post_id: {'url', 'subject', 'card_price_vnd',
    'card_size_m2', 'card_address'}}"""
    posts = {}
    for page in range(1, total_pages + 1):
        url = f"{BASE}/{category_slug}-{city_url_slug}-trang-{page}"
        print(f"📥 Đang lấy danh sách link trang {page}/{total_pages}: {url}")
        soup = fetch(scraper, url)
        if not soup:
            continue

        anchors = collect_valid_anchors(soup)
        found_this_page = set()
        for a in anchors:
            href = a.get("href", "")
            rel = get_relative_path(href)
            m = DETAIL_HREF_RE.match(rel)
            if not m:
                continue
            post_id = m.group(2)
            full_url = href if href.startswith("http") else BASE + href

            entry = posts.setdefault(post_id, {"url": full_url})
            found_this_page.add(post_id)

            # Subject: ưu tiên link nằm trong heading (h2/h3/h4)
            heading_parent = a.find_parent(["h1", "h2", "h3", "h4", "h5", "h6"])
            if heading_parent and not entry.get("subject"):
                entry["subject"] = (a.get("title") or a.get_text(strip=True)).strip()

            # Link gộp giá+diện tích+địa chỉ
            text = a.get_text(" ", strip=True)
            if "card_address" not in entry:
                price, size, address = parse_card_text(text)
                if address:
                    entry["card_price_vnd"] = price
                    entry["card_size_m2"] = size
                    entry["card_address"] = address

            # Fallback subject từ alt ảnh nếu vẫn chưa có
            if not entry.get("subject"):
                img = a.find("img")
                if img and img.get("alt"):
                    entry["subject"] = img["alt"].strip()

        print(f"  👉 {len(found_this_page)} tin ở trang {page} "
              f"(tổng cộng {len(posts)} tin duy nhất)")
        time.sleep(random.uniform(1.5, 2.5))

    return posts


# ---------- Cào trang chi tiết ----------
LABELS_WANTED = {"mức giá", "diện tích", "ngày đăng", "ngày hết hạn", "loại tin", "mã tin"}


def parse_detail_page(soup, url, fallback=None):
    fallback = fallback or {}
    post_id_from_url = url.rstrip("/").rsplit("/", 1)[-1]

    data = {
        "list_id": post_id_from_url if post_id_from_url.isdigit() else None,
        "posted_date": None,
        "price_vnd": None,
        "size_m2": None,
        "price_per_m2_vnd": None,
        "furnishing_status": None,
        "category_name": None,
        "latitude": None,
        "longitude": None,
        "ward_name": None,
        "street_name": None,
        "street_number": None,
        "subject": None,
        "body": None,
        "listing_type": None,
        "url": url,
    }

    h1 = soup.find("h1")
    data["subject"] = (h1.get_text(strip=True) if h1 else None) or fallback.get("subject")

    # Breadcrumb: category_name + ward_name (rất đáng tin cậy trên site này)
    crumbs = get_breadcrumb(soup)
    if len(crumbs) >= 2:
        data["category_name"] = crumbs[1]
    ward_from_breadcrumb = None
    if len(crumbs) >= 2:
        ward_raw = crumbs[-2]  # phần tử ngay trước tiêu đề
        ward_from_breadcrumb = re.sub(
            r"^(phường|xã|thị trấn|quận|huyện)\s+", "", ward_raw, flags=re.IGNORECASE
        ).strip()

    # Dòng địa chỉ ngắn ngay dưới H1 (vd "trần thủ độ, Điện Bàn Đông, Đà Nẵng")
    address_line = None
    if h1:
        for tag in h1.find_all_next(limit=6):
            txt = tag.get_text(" ", strip=True)
            if txt and "," in txt and 3 < len(txt) < 150:
                address_line = txt
                break

    # Bảng "Thông số bất động sản"
    info = get_labeled_values(soup, LABELS_WANTED)

    price_text = info.get("mức giá")
    size_text = info.get("diện tích")
    data["price_vnd"] = parse_price_vnd(price_text) if price_text else fallback.get("card_price_vnd")
    data["size_m2"] = parse_size_m2(size_text) if size_text else fallback.get("card_size_m2")
    if data["price_vnd"] and data["size_m2"]:
        data["price_per_m2_vnd"] = round(data["price_vnd"] / data["size_m2"])

    if "mã tin" in info:
        m = re.search(r"\d+", info["mã tin"])
        if m:
            data["list_id"] = m.group(0)

    if "loại tin" in info:
        data["listing_type"] = info["loại tin"]

    if "ngày đăng" in info:
        m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", info["ngày đăng"])
        if m:
            d, mo, y = m.groups()
            data["posted_date"] = f"{y}-{int(mo):02d}-{int(d):02d}"

    # Địa chỉ: ưu tiên dòng dưới H1, fallback sang địa chỉ trên card listing
    address_text = address_line or fallback.get("card_address")
    ward_name, street_name, street_number = parse_address_vn(
        address_text, known_ward=ward_from_breadcrumb
    )
    data["ward_name"] = ward_name
    data["street_name"] = street_name
    data["street_number"] = street_number

    # Mô tả
    data["body"] = get_section_after_heading(soup, "Thông tin mô tả")

    # Furnishing (best-effort, không có field rõ ràng trên site này)
    data["furnishing_status"] = get_furnishing_status(soup, data["body"], data["subject"])

    # Toạ độ: sẽ được geocode ở bước riêng (geocode_with_arcgis.py)
    data["latitude"] = None
    data["longitude"] = None

    return data


# ---------- Main ----------
def scrape_phongtro_vn(
    category_slug="cho-thue-phong-tro",
    city_url_slug="tp-da-nang",
    total_pages=5,
    source=SOURCE_NAME,
    max_posts=None,
):
    scraper = make_scraper()
    existing_ids = load_existing_payload_ids(source)

    print("🚀 BƯỚC 1: Thu thập link tin đăng từ các trang danh sách\n")
    posts_index = collect_post_links(
        scraper, category_slug=category_slug, city_url_slug=city_url_slug,
        total_pages=total_pages,
    )
    print(f"\n✅ Tổng cộng {len(posts_index)} tin đăng duy nhất.\n")

    known_count = sum(post_id in existing_ids for post_id in posts_index)
    items = [(post_id, meta) for post_id, meta in posts_index.items() if post_id not in existing_ids]
    print(f"⏭️ Bỏ qua {known_count} tin đã có; còn {len(items)} tin mới cần tải chi tiết.")
    if max_posts:
        items = items[:max_posts]

    print("🚀 BƯỚC 2: Cào chi tiết từng tin đăng\n")
    raw_payloads = []
    for i, (post_id, meta) in enumerate(items, 1):
        url = meta["url"]
        print(f"📄 [{i}/{len(items)}] #{post_id} - {url}")
        soup = fetch(scraper, url)
        if not soup:
            print("  ❌ Bỏ qua (không tải được trang).")
            continue
        raw_payloads.append(
            {
                "list_id": post_id,
                "payload_format": "html",
                "payload": encode_html_payload(
                    getattr(soup, "_raw_html_payload"), meta
                ),
                "source_url": url,
                "scraped_at": now_scraped_at(),
            }
        )

        time.sleep(random.uniform(1.5, 2.5))

        if i % 20 == 0:
            inserted = save_payloads(source, raw_payloads)
            raw_payloads.clear()
            print(f"  💾 Đã lưu tạm {inserted} payload mới vào R2 Bronze[{source}]")

    inserted = save_payloads(source, raw_payloads)
    print(f"\n🎉 Hoàn tất cào {source}: đã lưu {inserted} payload mới.")
    return inserted


if __name__ == "__main__":
    scrape_phongtro_vn(
        category_slug="cho-thue-phong-tro",  # đổi sang cho-thue-can-ho / cho-thue-nha / ... nếu cần
        city_url_slug="tp-da-nang",
        total_pages=50,
        max_posts=None,   # đặt số nhỏ (vd 10) để test trước khi chạy full
    )
