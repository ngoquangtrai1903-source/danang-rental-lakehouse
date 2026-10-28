# Da Nang Rental Data Pipeline

Dự án thu thập tin thuê phòng/căn hộ tại Đà Nẵng, xử lý và bổ sung dữ liệu địa lý, sau đó nạp dữ liệu curated vào PostgreSQL. Bronze được lưu bất biến trên Cloudflare R2; pipeline hiện tại không dùng SQL Server.

## Kiến trúc và luồng dữ liệu

```text
Nhà Tốt / Phongtro123 / Phongtro.vn
                 │
                 ▼
Scrapers ──► Cloudflare R2 (Bronze JSONL + manifest)
                 │                     │
                 │                     └── PostgreSQL ops.bronze_payload_index
                 ▼
Replay payloads ─► PostgreSQL silver.listings
                 │
                 ├── merge/deduplicate by lowercase body ─► silver.merged
                 ├── geocode ───────────► silver.geocoded + silver.geocode_report
                 ├── spatial + flood ───► silver.spatial
                 ├── text features ─────► silver.rental_room
                 └── warehouse transform ► gold.rental_room

silver.rental_room ── export ──► data/final/rental_room.csv
```

Chạy `python main.py --step all` theo thứ tự: **scrape → replay/merge → geocode → spatial → flood → text → Gold → export CSV**. Payload nguồn được lưu thành JSONL bất biến trên R2; PostgreSQL lưu index/ledger Bronze cùng các lớp Silver/Gold. Merge replay toàn bộ payload đã index, nên có thể áp dụng parser mới lên dữ liệu Bronze đã lưu. Tại bước merge, tin trùng được nhận diện chỉ bằng `body` sau khi gộp khoảng trắng thừa và chuyển về chữ thường Unicode; body rỗng được giữ lại và nếu trùng thì giữ bản ghi đầu tiên.

Chi tiết từng bước, điều kiện chạy lại và đầu ra được mô tả trong [DATA_PIPELINE.md](./DATA_PIPELINE.md). [MIGRATION_PLAN_R2_POSTGRES.md](./MIGRATION_PLAN_R2_POSTGRES.md) là hồ sơ quyết định migration; [DATA_LAKE_WAREHOUSE_IMPLEMENTATION_PLAN.md](./DATA_LAKE_WAREHOUSE_IMPLEMENTATION_PLAN.md) là tài liệu lịch sử về phương án SQL Server cũ.

## Yêu cầu

- Python 3.10 trở lên.
- PostgreSQL có cài PostGIS; database phải tồn tại trước khi chạy migration.
- Cloudflare R2 bucket và quyền truy cập S3-compatible cho các bước scrape/replay.
- Kết nối Internet cho scraper và bước geocode.

## Cài đặt

PowerShell trên Windows:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Mở `.env` và cấu hình:

| Biến | Dùng cho |
|---|---|
| `POSTGRES_DSN` | Kết nối PostgreSQL, ví dụ database `rental_danang` trên localhost |
| `R2_ENDPOINT_URL` | Cloudflare R2 endpoint |
| `R2_BUCKET_NAME` | Tên bucket Bronze |
| `R2_ACCESS_KEY_ID` | R2 access key |
| `R2_SECRET_ACCESS_KEY` | R2 secret key |
| `R2_REGION` | Region S3-compatible; thường dùng `auto` |

Không commit `.env`, giá trị bí mật, payload scrape hoặc bản dump database. `.env.example` chỉ chứa giá trị mẫu, không dùng làm thông tin đăng nhập thật.

Khởi tạo schema và áp dụng các migration PostgreSQL chưa chạy:

```powershell
python scripts/init_db.py
```

Lệnh này không tạo database PostgreSQL thay cho bạn; hãy tạo database và bật PostGIS trước. Các migration được đọc từ `sql/postgres/`.

## Chạy pipeline

Chạy toàn bộ quy trình, bao gồm crawl nguồn:

```powershell
python main.py --step all
```

Bỏ qua crawl nhưng vẫn replay payload đã lưu/index trên R2:

```powershell
python main.py --step all --skip-scrape
```

Các bước có thể chạy riêng:

```powershell
python main.py --step scrape
python main.py --step merge
python main.py --step geocode
python main.py --step spatial
python main.py --step flood
python main.py --step text
python main.py --step warehouse
python main.py --step export
```

`--step merge` vẫn đọc và replay Bronze từ R2; `--skip-scrape` chỉ bỏ việc lấy tin mới, không bỏ replay. `warehouse` dựng lại `gold.rental_room` từ Silver hiện có; `export` xuất `silver.rental_room` ra CSV. Các tuỳ chọn hợp lệ được liệt kê bằng:

```powershell
python main.py --help
```

Mặc định, flood step dùng `notebooks/danang_flood_2022.geojson` và `notebooks/danang_flood_2025.geojson`. Có thể chỉ định file khác:

```powershell
python main.py --step flood `
  --flood-geojson-2022 path\to\flood_2022.geojson `
  --flood-geojson-2025 path\to\flood_2025.geojson
```

Nhãn `flood_risk_label` biểu thị số năm trong hai mốc 2022/2025 có ghi nhận ngập: `0` = không năm nào, `1` = một năm, `2` = cả hai năm. Đây là nhãn lịch sử, không phải dự báo rủi ro ngập tương lai.

## Các lớp dữ liệu

| Lớp | Lưu ở | Nội dung |
|---|---|---|
| Bronze | Cloudflare R2 | Payload JSON/HTML bất biến theo batch JSONL, kèm manifest/checksum |
| Ops | PostgreSQL `ops` | Metadata batch và index `(source, list_id)`; không lưu payload body |
| Silver | PostgreSQL `silver` | Listing đã parse, merge, geocode, spatial/text enrich |
| Gold | PostgreSQL `gold` | Dataset curated hiện tại cho downstream consumer |
| CSV export | `data/final/` | Bản xuất của `silver.rental_room`, UTF-8 BOM, không có cột index |

Gold hiện là current-state, không lưu lịch sử thay đổi giá. Warehouse transform không loại dòng trùng; bảng `gold.rental_room` vẫn áp dụng khóa chính `(source, list_id)`, do đó các dòng trùng khóa tự nhiên có thể làm nạp Gold thất bại. Transform loại giá/diện tích không hợp lệ; chuẩn hóa category, ward và số phòng; chỉ giữ tọa độ trong bbox `[107.3000, 15.9167, 108.3333, 16.2333]` theo thứ tự `[min_lon, min_lat, max_lon, max_lat]`; giới hạn giá `Phòng trọ` ở 10 triệu; điền rooms chưa xác định bằng mode số phòng của căn hộ trước khi chỉ giữ `rooms <= 3`. Xem `src/warehouse/transform.py` và kiểm thử tương ứng để biết chi tiết.

## Thư mục chính

```text
main.py                 CLI điều phối pipeline
src/scrape/             Scrapers cho bốn nguồn tin
src/storage/            Ghi/đọc Bronze trên R2
src/db/                 Kết nối PostgreSQL và repository
src/process/            Replay, merge, geocode, spatial, flood, text, export
src/warehouse/          Transform và nạp Gold
scripts/init_db.py      Áp dụng migration PostgreSQL
sql/postgres/           Migration có version
tests/                  Unit và contract tests
notebooks/              Notebook phân tích và GeoJSON flood đầu vào
```

`data/raw/`, `data/processed/`, `data/final/`, `reports/` và `bronze_ops.sql` là dữ liệu/kết quả local bị loại khỏi các commit mới bởi `.gitignore`; Bronze chính thức nằm trên R2. Các GeoJSON flood đầu vào trong `notebooks/` vẫn được giữ trong repository vì pipeline dùng chúng mặc định.
