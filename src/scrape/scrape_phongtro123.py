# -*- coding: utf-8 -*-
"""
Scraper phongtro123.com (2 tầng: trang danh sách -> trang chi tiết)
Xuất đầy đủ các cột:
list_id, posted_date, price_vnd, size_m2, price_per_m2_vnd, furnishing_status,
category_name, latitude, longitude, ward_name, street_name, street_number,
subject, body

Cài đặt thư viện cần thiết:
    pip install cloudscraper beautifulsoup4 pandas geopy

Ghi chú:
- Các trường như posted_date, ward_name, street_name, category_name, body,
  furnishing_status CHỈ có trên trang CHI TIẾT từng tin, không có trên trang
  danh sách -> script phải mở từng link chi tiết để cào (chậm hơn nhưng đủ dữ liệu).
- Trang chi tiết KHÔNG có sẵn latitude/longitude trong HTML (chỉ có link Google
  Maps embed chứa địa chỉ dạng text). Script sẽ geocode địa chỉ đó bằng
  Nominatim (OpenStreetMap, miễn phí) - có thể chậm và không phải lúc nào cũng
  chính xác 100%. Nếu bạn có Google Geocoding API key, có thể thay hàm
  geocode_address() để dùng Google cho chính xác hơn.
- Vì đây là parser dựa trên "tìm theo nhãn/heading" (label-based), nó khá bền
  vững trước thay đổi class CSS, nhưng nếu site đổi cấu trúc hoàn toàn bạn cần
  in soup.prettify() của 1 trang chi tiết ra để kiểm tra lại.
"""

import cloudscraper
from bs4 import BeautifulSoup
import re
import time
import random
from urllib.parse import unquote, urlparse, parse_qs

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

SOURCE_NAME = "phongtro123"

# ---------- Cấu hình ----------
BASE = "https://phongtro123.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://phongtro123.com/",
}

CATEGORY_MAP = {
    "cho thuê phòng trọ": "Phòng trọ",
    "cho thuê nhà nguyên căn": "Nhà nguyên căn",
    "cho thuê nhà": "Nhà nguyên căn",
    "cho thuê căn hộ": "Căn hộ",
    "tìm người ở ghép": "Ở ghép",
    "cho thuê mặt bằng": "Mặt bằng",
}

FURNISHING_NEGATIVE_PATTERNS = [
    "không có nội thất", "không nội thất", "nhà trống", "phòng trống",
    "chưa có nội thất", "không có sẵn nội thất", "không trang bị nội thất",
]

FURNISHING_FULL_PATTERNS = [
    "đầy đủ nội thất", "đầy đủ tiện nghi", "full nội thất", "full tiện nghi",
    "nội thất đầy đủ", "tiện nghi đầy đủ", "full nt", "fullnoithat",
    "nội thất full", "nội thất và tiện nghi đầy đủ", "tiện nghi và nội thất đầy đủ",
    "nội thất cao cấp", "nội thất sang trọng", "trang bị đầy đủ nội thất",
    "đầy đủ tiện nghi và nội thất", "full nội thất cao cấp", "đầy đủ"
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


# ---------- Helper: Parse tiền / diện tích ----------
def parse_price_vnd(text):
    if not text:
        return None
    text = text.strip()
    if "thỏa thuận" in text.lower():
        return None

    # "3.2 triệu/tháng", "2,5 triệu/tháng"
    m = re.search(r"([\d]+(?:[.,]\d+)?)\s*triệu", text, re.IGNORECASE)
    if m:
        return round(float(m.group(1).replace(",", ".")) * 1_000_000)

    m = re.search(r"([\d]+(?:[.,]\d+)?)\s*tỷ", text, re.IGNORECASE)
    if m:
        return round(float(m.group(1).replace(",", ".")) * 1_000_000_000)

    m = re.search(r"([\d]+(?:[.,]\d+)?)\s*nghìn", text, re.IGNORECASE)
    if m:
        return round(float(m.group(1).replace(",", ".")) * 1_000)

    # "900.000 đồng/tháng" -> dấu chấm là phân cách nghìn
    m = re.search(r"([\d][\d.,]*)\s*(?:đồng|vnd|đ)\b", text, re.IGNORECASE)
    if m:
        digits = re.sub(r"[.,]", "", m.group(1))
        if digits.isdigit():
            return int(digits)

    return None


def parse_size_m2(text):
    if not text:
        return None
    m = re.search(r"([\d]+(?:[.,]\d+)?)\s*m\s*(?:²|2)", text, re.IGNORECASE)
    if m:
        return float(m.group(1).replace(",", "."))
    return None


# ---------- Helper: tìm nội dung theo heading ----------
def get_section_after_heading(soup, heading_text):
    """Tìm heading (h1-h6) có text khớp heading_text, lấy nội dung ngay sau đó
    cho đến heading tiếp theo."""
    heading = None
    for tag in soup.find_all(re.compile(r"^h[1-6]$")):
        if tag.get_text(strip=True).lower() == heading_text.lower():
            heading = tag
            break
    if not heading:
        return ""

    parts = []
    # Thử lấy các sibling ngay sau heading trước
    for sib in heading.find_next_siblings():
        if sib.name and re.match(r"^h[1-6]$", sib.name):
            break
        txt = sib.get_text("\n", strip=True)
        if txt:
            parts.append(txt)

    if parts:
        return "\n".join(parts).strip()

    # Fallback: heading và nội dung nằm trong cùng 1 container cha
    parent = heading.find_parent(["div", "section"])
    if parent:
        full = parent.get_text("\n", strip=True)
        return full.replace(heading.get_text(strip=True), "", 1).strip()

    return ""


def get_info_table(soup):
    """Tìm các cặp nhãn:giá trị trong bảng thông tin
    (Quận huyện / Tỉnh thành / Địa chỉ / Mã tin / Ngày đăng / Ngày hết hạn)."""
    labels_wanted = {
        "quận huyện", "tỉnh thành", "địa chỉ", "mã tin",
        "ngày đăng", "ngày hết hạn",
    }
    data = {}

    # 1) Thử dạng <table><tr><td>label</td><td>value</td></tr
    for tr in soup.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        if len(cells) >= 2:
            label = cells[0].get_text(strip=True).rstrip(":").lower()
            value = cells[1].get_text(" ", strip=True)
            if label in labels_wanted:
                data[label] = value

    # 2) Thử dạng <dl><dt>label</dt><dd>value</dd>
    if not data:
        dts = soup.find_all("dt")
        for dt in dts:
            label = dt.get_text(strip=True).rstrip(":").lower()
            dd = dt.find_next_sibling("dd")
            if label in labels_wanted and dd:
                data[label] = dd.get_text(" ", strip=True)

    # 3) Fallback: quét toàn bộ text bằng regex "Label: value" theo dòng
    if not data:
        full_text = soup.get_text("\n", strip=True)
        for label in labels_wanted:
            m = re.search(
                re.escape(label) + r"\s*:\s*(.+)", full_text, re.IGNORECASE
            )
            if m:
                data[label] = m.group(1).split("\n")[0].strip()

    return data


def get_breadcrumb_category(soup):
    """Lấy mục đầu tiên trong breadcrumb (vd 'Cho thuê phòng trọ')."""
    ol = soup.find("ol")
    if ol:
        a = ol.find("a")
        if a:
            text = a.get_text(strip=True).lower()
            for key, val in CATEGORY_MAP.items():
                if key in text:
                    return val
            return a.get_text(strip=True)
    return None


def parse_address(address_text):
    """Tách ward_name, street_name, street_number từ chuỗi địa chỉ kiểu
    'Đường Bình Hoà 15, Phường Cẩm Lệ, Đà Nẵng' hoặc '47 Hoàng Diệu, Hải Châu, Đà Nẵng'."""
    ward_name = street_name = street_number = None
    if not address_text:
        return ward_name, street_name, street_number

    parts = [p.strip() for p in address_text.split(",") if p.strip()]

    street_part = None
    for p in parts:
        low = p.lower()
        if low.startswith(("phường ", "xã ", "thị trấn ")):
            ward_name = re.sub(
                r"^(phường|xã|thị trấn)\s+", "", p, flags=re.IGNORECASE
            ).strip()
        elif street_part is None:
            street_part = p

    if street_part:
        street_part = re.sub(
            r"^(đường|phố|ngõ|hẻm|kiệt)\s+", "", street_part, flags=re.IGNORECASE
        ).strip()
        # Nếu bắt đầu bằng số nhà (vd "47 Hoàng Diệu") -> tách số nhà
        m = re.match(r"^(\d+[A-Za-z]?(?:/\d+[A-Za-z]?)*)\s+(.*)", street_part)
        if m:
            street_number = m.group(1)
            street_name = m.group(2).strip()
        else:
            # Địa chỉ dạng "Bình Hoà 15" -> là TÊN đường có số, không tách số nhà
            street_name = street_part

    return ward_name, street_name, street_number


def get_furnishing_status(soup, body_text="", subject_text=""):
    """Phân loại tình trạng nội thất theo nhiều tầng, quét trên mục 'Nổi
    bật' (đặc thù site này) + subject + body + thuộc tính icon:
    1) Ưu tiên nhận diện phủ định ("không nội thất"...) trước tiên, vì
       nếu quét từ khóa dương tính trước sẽ dính oan do "không nội thất"
       vẫn chứa chữ "nội thất".
    2) Cụm khẳng định đầy đủ ("đầy đủ nội thất/tiện nghi", "full nội
       thất"...) - bộ từ khóa mở rộng nhiều biến thể.
    3) Cụm "cơ bản".
    4) Liệt kê món đồ cụ thể (vd "Nội thất đã có: điều hoà, bình nóng
       lạnh, sàn lửng, wifi...") - đếm số món nhận diện được để suy ra
       mức độ (>=3 món -> Đầy đủ, 1-2 món -> Cơ bản).
    """
    noi_bat_section = get_section_after_heading(soup, "Nổi bật")

    haystack_parts = [noi_bat_section, body_text or "", subject_text or ""]
    for el in soup.find_all(True, limit=300):
        for attr in ("title", "aria-label", "alt"):
            v = el.get(attr)
            if v:
                haystack_parts.append(v)
    combined = " ".join(haystack_parts).lower()
    combined_norm = re.sub(r"\s+", " ", combined)

    for p in FURNISHING_NEGATIVE_PATTERNS:
        if p in combined_norm:
            return "Không nội thất"

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
            list_text = m.group(1)[:300]  # giới hạn độ dài, tránh dính cả đoạn mô tả dài phía sau
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


def get_map_address_query(soup):
    """Lấy chuỗi địa chỉ dùng trong Google Maps embed (q=...) để geocode."""
    iframe = soup.find("iframe", src=re.compile(r"maps/embed"))
    src = iframe.get("src") if iframe else None
    if not src:
        # đôi khi src nằm trong link text thay vì thuộc tính (do markdown-like render)
        a = soup.find("a", href=re.compile(r"maps/embed"))
        src = a.get("href") if a else None
    if not src:
        return None
    qs = parse_qs(urlparse(src).query)
    if "q" in qs:
        return unquote(qs["q"][0])
    m = re.search(r"[?&]q=([^&]+)", src)
    if m:
        return unquote(m.group(1))
    return None


# ---------- Cào trang danh sách: chỉ để lấy link tin ----------
# QUAN TRỌNG: href chứa "-pr<số>.html" mới là tin đăng thật. Selector cũ
# `a[href*='pr']` KHỚP NHẦM cả link "/cdn-cgi/l/email-protection" (vì chữ
# "protection" chứa "pr") và rất nhiều link menu/sidebar khác -> đây là
# nguyên nhân chính khiến dữ liệu bị nhiễu/thiếu. Dùng regex chặt ở cuối
# chuỗi href để chỉ khớp đúng URL tin đăng.
POST_HREF_RE = re.compile(r"-pr(\d+)\.html$")


def normalize_url(href):
    href = href.strip()
    return href if href.startswith("http") else BASE + href


def extract_post_id(href_or_url):
    m = POST_HREF_RE.search(href_or_url)
    return m.group(1) if m else None


# Các heading đánh dấu bắt đầu khối "tin gợi ý sitewide" (vd "Tin mới đăng",
# "Tin đăng nổi bật"...) - khối này KHÔNG lọc theo tỉnh/thành hiện tại, nếu
# không loại trừ sẽ lẫn tin đăng của Hà Nội/HCM/... vào kết quả Đà Nẵng.
SIDEBAR_CUTOFF_HEADINGS = {
    "tin mới đăng", "tin mới cập nhật", "tin đăng nổi bật",
    "tin đăng cùng khu vực", "có thể bạn quan tâm", "bài viết mới",
}


def is_sidebar_cutoff_heading(tag):
    if tag.name not in ("h1", "h2", "h3", "h4", "h5", "h6"):
        return False
    heading_text = re.sub(r"\s+", " ", tag.get_text(" ", strip=True))
    heading_text = heading_text.rstrip(" :").casefold()
    return heading_text in SIDEBAR_CUTOFF_HEADINGS


def find_primary_price_tag(soup, h1):
    """Find the first price marker after the listing title, before suggestions."""
    found_title = False
    price_pattern = re.compile(
        r"(?:[\d]+(?:[.,]\d+)?\s*(?:triệu|tỷ|nghìn)|"
        r"[\d][\d.,]*\s*(?:đồng|vnd|đ)\b|thỏa thuận)",
        re.IGNORECASE,
    )
    for element in soup.find_all(True):
        if is_sidebar_cutoff_heading(element):
            break
        if element is h1:
            found_title = True
            continue
        if not found_title:
            continue

        classes = element.get("class", [])
        if "text-green" not in classes:
            continue
        if price_pattern.search(element.get_text("", strip=True)):
            return element
    return None


def find_price_row_size(price_tag):
    """Read area only from the compact row containing the primary price."""
    container = price_tag.parent
    for _ in range(4):
        if container is None or container.name in ("body", "html"):
            break
        if any(
            is_sidebar_cutoff_heading(heading)
            for heading in container.find_all(re.compile(r"^h[1-6]$"))
        ):
            break
        size = parse_size_m2(container.get_text("", strip=True))
        if size is not None:
            return size
        container = container.parent
    return None


def collect_valid_anchors(soup):
    """Duyệt DOM theo thứ tự tài liệu, chỉ lấy các thẻ <a> tin đăng xuất
    hiện TRƯỚC khối sidebar gợi ý sitewide (nếu có)."""
    valid_anchors = []
    for el in soup.find_all(True):
        if is_sidebar_cutoff_heading(el):
            break
        if el.name == "a" and POST_HREF_RE.search(el.get("href", "")):
            valid_anchors.append(el)
    return valid_anchors


def collect_post_links(scraper, city_slug="da-nang", total_pages=5):
    """Trả về dict {post_id: {'url':..., 'subject':...}} để tránh trùng lặp
    và tránh lẫn tin đăng gợi ý ở tỉnh/thành khác xuất hiện trong sidebar
    'Tin mới cập nhật' của trang chi tiết/trang danh sách."""
    posts = {}
    for page in range(1, total_pages + 1):
        url = f"{BASE}/tinh-thanh/{city_slug}?page={page}"
        print(f"📥 Đang lấy danh sách link trang {page}/{total_pages}: {url}")
        soup = fetch(scraper, url)
        if not soup:
            continue

        # Chỉ lấy các thẻ <a> có href thật sự khớp pattern tin đăng, và nằm
        # trước khối sidebar gợi ý sitewide (tránh lẫn tin tỉnh/thành khác)
        anchors = collect_valid_anchors(soup)

        found_this_page = 0
        for a in anchors:
            href = a.get("href", "")
            post_id = extract_post_id(href)
            if not post_id:
                continue

            full_url = normalize_url(href)

            # Ưu tiên lấy subject từ thuộc tính title (KHÔNG bị cắt bởi
            # CSS line-clamp), fallback sang text hiển thị nếu thiếu title
            subject = a.get("title", "").strip() or a.get_text(strip=True)
            if not subject:
                continue

            if post_id not in posts:
                posts[post_id] = {"url": full_url, "subject": subject}
                found_this_page += 1

        print(f"  👉 Tìm thấy {found_this_page} tin mới ở trang {page} "
              f"(tổng cộng {len(posts)} tin duy nhất)")
        time.sleep(random.uniform(1.5, 2.5))

    return posts


# ---------- Cào trang chi tiết ----------
def parse_detail_page(soup, url, fallback_subject=None):
    data = {
        "list_id": extract_post_id(url),
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
        "url": url,
    }

    h1 = soup.find("h1")
    data["subject"] = (h1.get_text(strip=True) if h1 else None) or fallback_subject

    # Giá và diện tích lấy từ cùng hàng thông tin của tin chính. Không quét
    # text nodes toàn trang vì các tin gợi ý có thể nằm ngay sau nội dung chính.
    if h1:
        price_tag = find_primary_price_tag(soup, h1)
        if price_tag:
            data["price_vnd"] = parse_price_vnd(
                price_tag.get_text(" ", strip=True)
            )
            data["size_m2"] = find_price_row_size(price_tag)
    if data["price_vnd"] and data["size_m2"]:
        data["price_per_m2_vnd"] = round(data["price_vnd"] / data["size_m2"])

    # Bảng thông tin
    info = get_info_table(soup)
    if "mã tin" in info:
        m = re.search(r"\d+", info["mã tin"])
        if m:
            data["list_id"] = m.group(0)  # ưu tiên "Mã tin" trên trang, đã có fallback từ URL ở trên

    if "ngày đăng" in info:
        m = re.search(r"(\d{1,2}:\d{2})\s+(\d{1,2}/\d{1,2}/\d{4})", info["ngày đăng"])
        if m:
            time_part, date_part = m.groups()
            d, mo, y = date_part.split("/")
            data["posted_date"] = f"{y}-{int(mo):02d}-{int(d):02d} {time_part}"

    # Fallback: thẻ <time title="Thứ 4, 21:22 09/09/2026"> chứa timestamp
    # tuyệt đối chính xác (đã xác nhận qua HTML mẫu khối "Tin mới cập nhật").
    # CHÚ Ý: phải giới hạn tìm kiếm TRƯỚC khối sidebar "Tin đăng cùng khu
    # vực/nổi bật" ở cuối trang chi tiết, nếu không sẽ vô tình lấy nhầm
    # <time> của một tin gợi ý KHÁC thay vì tin đang cào.
    if not data["posted_date"]:
        time_tag = None
        for el in soup.find_all(True):
            if is_sidebar_cutoff_heading(el):
                break
            if el.name == "time" and el.get("title") and \
                    re.search(r"\d{1,2}:\d{2}\s+\d{1,2}/\d{1,2}/\d{4}", el.get("title", "")):
                time_tag = el
                break
        if time_tag:
            m = re.search(r"(\d{1,2}:\d{2})\s+(\d{1,2}/\d{1,2}/\d{4})", time_tag.get("title", ""))
            if m:
                time_part, date_part = m.groups()
                d, mo, y = date_part.split("/")
                data["posted_date"] = f"{y}-{int(mo):02d}-{int(d):02d} {time_part}"

    address_text = info.get("địa chỉ")
    ward_name, street_name, street_number = parse_address(address_text)
    data["ward_name"] = ward_name
    data["street_name"] = street_name
    data["street_number"] = street_number

    # Category
    data["category_name"] = get_breadcrumb_category(soup)

    # Mô tả (body)
    data["body"] = get_section_after_heading(soup, "Thông tin mô tả")

    # Furnishing status
    data["furnishing_status"] = get_furnishing_status(soup, data["body"], data["subject"])

    # Toạ độ (geocode địa chỉ lấy từ Google Maps embed, hoặc dùng địa chỉ ở bảng)
    # Toạ độ: sẽ được geocode ở bước riêng (geocode_with_arcgis.py)
    data["latitude"] = None
    data["longitude"] = None

    return data


# ---------- Main ----------
def scrape_phongtro123_full(
    city_slug="da-nang",
    total_pages=5,
    source=SOURCE_NAME,
    max_posts=None,
):
    scraper = make_scraper()
    existing_ids = load_existing_payload_ids(source)

    print("🚀 BƯỚC 1: Thu thập link tin đăng từ các trang danh sách\n")
    posts_index = collect_post_links(scraper, city_slug=city_slug, total_pages=total_pages)
    print(f"\n✅ Tổng cộng {len(posts_index)} tin đăng duy nhất (đã lọc link rác/trùng lặp).\n")

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
                    getattr(soup, "_raw_html_payload"),
                    {"subject": meta.get("subject")},
                ),
                "source_url": url,
                "scraped_at": now_scraped_at(),
            }
        )

        time.sleep(random.uniform(1.5, 2.5))

        # Lưu tạm mỗi 20 tin để tránh mất dữ liệu nếu bị ngắt giữa chừng
        if i % 20 == 0:
            inserted = save_payloads(source, raw_payloads)
            raw_payloads.clear()
            print(f"  💾 Đã lưu tạm {inserted} payload mới vào R2 Bronze[{source}]")

    inserted = save_payloads(source, raw_payloads)
    print(f"\n🎉 Hoàn tất cào {source}: đã lưu {inserted} payload mới.")
    return inserted


if __name__ == "__main__":
    scrape_phongtro123_full(
        city_slug="da-nang",
        total_pages=60,         # số trang danh sách muốn cào
        max_posts=None,         # đặt số nhỏ (vd 10) để test nhanh trước khi chạy full
    )
