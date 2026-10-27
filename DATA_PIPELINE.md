# Hướng dẫn vận hành pipeline

Tài liệu này mô tả workflow đang được thực thi bởi `main.py`. Pipeline dùng Cloudflare R2 cho Bronze và PostgreSQL/PostGIS cho các lớp Ops, Silver, Gold; không dùng SQL Server.

## Sơ đồ pipeline

```text
Website/API
   │
   ├─ scrape Nhà Tốt (căn hộ)
   ├─ scrape Nhà Tốt (phòng trọ)
   ├─ scrape Phongtro123
   └─ scrape Phongtro.vn
          │ payload mới
          ▼
R2 Bronze: JSONL bất biến + manifest/checksum
          │ ops.bronze_payload_index lưu metadata và khóa dedupe
          ▼
Replay toàn bộ payload ──► silver.listings
          │
          ├─ normalize + deduplicate by lowercase subject/body ─► silver.merged
          ├─ geocode ─────────────────► silver.geocoded
          │                             silver.geocode_report
          ├─ spatial features ─────────► silver.spatial
          ├─ flood labels ────────────► silver.spatial
          ├─ text features ──────────► silver.rental_room
          ├─ warehouse transform ────► gold.rental_room
          └─ CSV export ─────────────► data/final/rental_room.csv
```

## Các bước và đầu vào/đầu ra

| Thứ tự | Bước CLI | Xử lý | Đầu ra |
|---:|---|---|---|
| 1 | `scrape` | Crawl bốn nguồn; chỉ lưu payload mới theo `(source, list_id)` | R2 Bronze JSONL + manifest; index trong PostgreSQL `ops` |
| 2 | `merge` | Đọc/replay toàn bộ payload đã index bằng parser hiện tại, chuẩn hóa và loại tin trùng theo cặp subject/body sau khi gộp khoảng trắng, chuyển chữ thường Unicode | `silver.listings`, `silver.merged` |
| 3 | `geocode` | Bổ sung tọa độ cho listing | `silver.geocoded`, `silver.geocode_report` |
| 4 | `spatial` | Tính các đặc trưng khoảng cách/không gian | `silver.spatial` |
| 5 | `flood` | Gán trạng thái ngập dựa trên GeoJSON hai mốc năm | Cập nhật `silver.spatial` |
| 6 | `text` | Trích xuất đặc trưng văn bản/tiện ích | `silver.rental_room` |
| 7 | `warehouse` | Áp dụng transform Gold và thay current-state trong transaction | `gold.rental_room` |
| 8 | `export` | Xuất dataset Silver để dùng/kiểm tra bên ngoài | `data/final/rental_room.csv` |

Toàn bộ các bước chạy theo thứ tự nêu trên khi gọi `all`. Parser replay lại dữ liệu Bronze mỗi lần `merge`, nên thay đổi parser có thể làm thay đổi Silver sau khi chạy lại pipeline; payload Bronze trên R2 không bị ghi đè bởi bước replay.

## Thiết lập lần đầu

1. Cài Python và dependencies theo phần [Cài đặt trong README](./README.md#cài-đặt).
2. Tạo PostgreSQL database, bật PostGIS và cấu hình `POSTGRES_DSN` trong `.env`.
3. Tạo bucket R2, điền endpoint/bucket/access key/secret key vào `.env`.
4. Áp dụng migrations:

   ```powershell
   python scripts/init_db.py
   ```

Migrations có version và chỉ áp dụng một lần. Không đưa credential thật vào tài liệu, notebook, log hoặc Git.

## Lệnh thường dùng

Chạy crawl mới rồi dựng lại toàn bộ downstream:

```powershell
python main.py --step all
```

Bỏ qua crawl và dùng Bronze đã có trên R2:

```powershell
python main.py --step all --skip-scrape
```

Chạy một bước riêng:

```powershell
python main.py --step merge
python main.py --step geocode
python main.py --step spatial
python main.py --step flood
python main.py --step text
python main.py --step warehouse
python main.py --step export
```

Các giá trị `--step` hợp lệ là `all`, `scrape`, `merge`, `geocode`, `spatial`, `flood`, `text`, `warehouse`, `export`. `--help` in ra danh sách và tuỳ chọn đầy đủ.

Lưu ý về chạy riêng:

- `--skip-scrape` chỉ bỏ crawl; `merge` vẫn đọc Bronze từ R2. Nó không chạy từ các CSV trong `data/raw/`.
- `--step merge` cần R2 và PostgreSQL vì replay toàn bộ payload trước khi merge.
- `--step geocode` cần dữ liệu đã qua merge; `spatial` cần dữ liệu đã geocode; `flood` cần `spatial`; `text` cần `spatial`.
- `--step warehouse` chỉ dựng Gold từ `silver.rental_room` hiện có; `--step export` chỉ xuất CSV từ Silver, không dựng Gold.
- `main.py` hiện không có bước huấn luyện model hoặc các tuỳ chọn `--train`.

Ở bước `merge`, tiêu chí loại tin trùng là cặp `subject` và `body` sau khi gộp các khoảng trắng liên tiếp và chuyển về chữ thường Unicode; không dùng `source` hoặc `list_id` trong tiêu chí này. Chỉ các dòng có cả hai nội dung sau chuẩn hóa mới được so sánh; dòng thiếu một trong hai được giữ lại. Nếu trùng, giữ dòng xuất hiện trước và không sửa nội dung gốc.

## Dữ liệu flood

Mặc định pipeline đọc:

- `notebooks/danang_flood_2022.geojson`
- `notebooks/danang_flood_2025.geojson`

Thay file đầu vào khi cần:

```powershell
python main.py --step flood `
  --flood-geojson-2022 path\to\flood_2022.geojson `
  --flood-geojson-2025 path\to\flood_2025.geojson
```

`flooded_2022` và `flooded_2025` giữ trạng thái từng năm; `flood_risk_label` là `0` nếu cả hai năm không ngập, `1` nếu ngập đúng một năm, `2` nếu ngập cả hai. Nhãn mô tả hai sự kiện lịch sử, không dự báo ngập.

- GeoJSON chỉ chứa polygon ngập (`is_flood=1`) được hiểu là flood-only: điểm ngoài polygon được xem là không ngập.
- Nếu GeoJSON có cả polygon khô (`is_flood=0`) và ngập, điểm ngoài vùng polygon được giữ `NULL` vì không có thông tin bao phủ.
- Tọa độ thiếu/không hữu hạn cho trạng thái `NULL`. Polygon không hợp lệ được thử sửa bằng Shapely; nếu không thể khôi phục polygon hợp lệ, bước flood dừng với lỗi.

GeoJSON đầu vào là file nguồn cần thiết và không nên loại khỏi repository nếu vẫn dùng đường dẫn mặc định.

## Lưu ý dữ liệu và Git

- R2 là nơi lưu payload Bronze chính thức. PostgreSQL `ops` giữ batch/index/metadata, không giữ payload body.
- Gold hiện là bảng current-state, không phải lịch sử biến động giá. Transform không loại dòng trùng; tuy nhiên bảng `gold.rental_room` vẫn có khóa chính `(source, list_id)`, nên dữ liệu trùng khóa tự nhiên có thể khiến thao tác nạp Gold thất bại.
- Gold chỉ giữ tọa độ trong bbox Đà Nẵng `[107.3000, 15.9167, 108.3333, 16.2333]` (thứ tự `[min_lon, min_lat, max_lon, max_lat]`), bao gồm điểm nằm trên biên; giá `Phòng trọ` không vượt quá 10 triệu.
- `rooms` được chuẩn hóa trước; “Không xác định” của căn hộ được điền bằng mode số phòng căn hộ hợp lệ trong tập còn lại sau các bộ lọc trước đó, nhưng trước giới hạn 3 phòng (nếu mode hòa, chọn giá trị nhỏ hơn). Sau đó chỉ giữ số phòng không vượt quá 3. Phòng trọ được chuẩn hóa thành `1`; nếu không có mode hợp lệ thì rooms chưa xác định bị loại.
- Các thư mục `data/raw/`, `data/processed/`, `data/final/` và `reports/` chứa dữ liệu/đầu ra local và được `.gitignore` loại khỏi các file mới.
- `.gitignore` không tự bỏ các file đã được Git theo dõi. Trước khi push, kiểm tra `git status --short`; nếu muốn bỏ dữ liệu/artifact cũ khỏi commit, cần chủ động bỏ tracking bằng `git rm --cached` sau khi rà soát thay đổi sẽ được stage. Lệnh này giữ bản local nhưng tạo thay đổi trong Git index.
