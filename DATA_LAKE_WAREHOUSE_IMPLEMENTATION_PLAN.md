# Tài liệu lưu trữ: Kế hoạch Data Lake → Data Warehouse (SQL Server)

> **Tài liệu lịch sử, không dùng làm hướng dẫn vận hành.** Nội dung bên dưới mô tả phương án SQL Server trước migration và một số đề xuất chưa triển khai. Kiến trúc runtime hiện tại cùng hướng dẫn thiết lập/vận hành nằm trong [README.md](./README.md), [DATA_PIPELINE.md](./DATA_PIPELINE.md) và hồ sơ [MIGRATION_PLAN_R2_POSTGRES.md](./MIGRATION_PLAN_R2_POSTGRES.md). Không dùng các cấu hình SQL Server trong tài liệu này cho pipeline hiện tại.

## 1. Mục tiêu ban đầu (trước migration)

Tách rõ hai trách nhiệm:

1. **Data Lake / Lake database**: lưu dữ liệu thu thập và các lớp đã chuẩn hóa, enrich; có thể dựng lại từ dữ liệu nguồn.
2. **Data Warehouse**: nhận dữ liệu curated từ Lake, áp dụng mô hình phân tích, kiểm tra chất lượng và cung cấp bảng ổn định cho BI, truy vấn và mô hình.

Kế hoạch này định hướng triển khai bằng Python và SQL Server, chưa bao gồm code thực thi.

> **Trạng thái hiện tại:** runtime đã chuyển sang R2 + PostgreSQL/PostGIS; phần SQL Server bên dưới chỉ lưu lại mục tiêu và phương án thiết kế cũ. Xem [MIGRATION_PLAN_R2_POSTGRES.md](./MIGRATION_PLAN_R2_POSTGRES.md) để biết kiến trúc đã triển khai.

## 2. Đánh giá tại thời điểm lập kế hoạch (đã lỗi thời)

### Những gì project đang có

- SQL Server database `RentalDaNang` hiện chứa các schema `raw`, `processed`, `final`; theo ranh giới kiến trúc của dự án, đây là database của Data Lake.
- Có thể diễn giải các lớp hiện có như sau:
  - `raw.listings`: dữ liệu scrape ban đầu, gần với Bronze.
  - `processed.merged`, `processed.geocoded`, `processed.spatial`: dữ liệu đã chuẩn hóa/enrich, gần với Silver.
  - `final.rental_room`: lớp cuối đã enrich của Lake, phục vụ dataset ML/export và làm nguồn đầu vào cho Warehouse; đây không phải bảng Warehouse.
- Pipeline Python ghi `final.rental_room`; module export đọc bảng này và tạo `data/final/rental_room.csv`. Bảng và CSV đều thuộc đầu ra Data Lake, không phải Data Warehouse.
- `final.rental_room` hiện vẫn nằm trong cùng database `RentalDaNang`; chưa có database hoặc mô hình Warehouse riêng.
- Các bảng processed/final được dựng lại theo đợt; raw là lớp tích lũy. Vì vậy project hiện chưa có warehouse history hay pipeline đồng bộ sang database thứ hai.

### Nhận định kiến trúc

Thiết kế hiện tại là **nền tảng dữ liệu phân lớp trên SQL Server** (lake-style/lakehouse đơn giản), chưa phải Data Lake theo nghĩa phổ biến là lưu object/file dữ liệu thô với metadata/catalog độc lập. Với quy mô dự án hiện tại, SQL Server là điểm bắt đầu phù hợp; nên dùng thuật ngữ “Lake database” trong tài liệu để tránh nhầm rằng đây đã là một object-storage data lake.

Không nên chuyển bảng `final.rental_room` hiện tại thành warehouse chỉ bằng cách sao chép nguyên bảng. Bảng này đang tối ưu như một dataset phẳng phục vụ ML. Warehouse cần mô hình và hợp đồng dữ liệu riêng, không nên phụ thuộc trực tiếp vào chi tiết nội bộ của pipeline scrape.

## 3. Kiến trúc đích đề xuất thời điểm đó

```text
Nguồn scrape
    │
    ▼
RentalDaNangLake (SQL Server)
    raw.listings                         Bronze
    processed.merged/geocoded/spatial   Silver
    final.rental_room                   Lake final output / ML dataset
    │
    │ Extract → validate → transform → stage → load
    ▼
Python warehouse loader (`src/warehouse/`)
    ├── đọc Lake final theo batch
    ├── kiểm tra schema, chất lượng và khóa
    ├── transform sang warehouse dimensions/facts
    ├── nạp staging và reconcile
    └── publish trong transaction
    │
    ▼
RentalDaNangWarehouse (SQL Server database riêng)
    stg.*       staging/reconciliation
    dw.dim_*    dimensions
    dw.fact_*   facts
    mart.*      bảng/view thân thiện BI và phân tích
```

### Quyết định cơ sở dữ liệu

- Tạo database riêng `RentalDaNangWarehouse`; trong giai đoạn đầu có thể nằm cùng SQL Server instance với Lake để giảm vận hành.
- Dùng connection profile riêng cho Lake và Warehouse. Không đổi mặc định kết nối Lake của scraper/processing hiện tại.
- Không để Python ghép dữ liệu chéo database tùy tiện trong logic transform. Cấu hình rõ hai kết nối, extraction có giới hạn và load sang đích có kiểm soát.
- Nếu sau này cần mở rộng, hai database có thể chuyển sang hai instance/host riêng mà không đổi hợp đồng dữ liệu.

### Quyết định thư mục

```text
src/
├── db/                         # Kết nối và repository Lake hiện có
├── process/                    # Xử lý Bronze → Silver → curated Lake
└── warehouse/
    ├── extract/                # Đọc curated output từ Lake
    ├── transform/              # Ánh xạ source contract sang warehouse model
    ├── load/                   # Staging, kiểm tra, upsert/MERGE
    └── run_warehouse.py        # Điều phối riêng ETL sang Warehouse

sql/
├── ...                         # SQL Lake hiện có
└── warehouse/
    ├── 00_create_database.sql  # Tùy chọn; quản trị có thể tạo thủ công
    ├── 01_create_schemas.sql
    ├── 02_create_dimensions.sql
    ├── 03_create_facts.sql
    ├── 04_create_marts.sql
    └── migration/              # Các thay đổi schema có phiên bản

data/
├── raw/                        # Chỉ file đầu vào/legacy; không là bản chuẩn của Lake
├── processed/                  # File tạm/legacy nếu còn cần
├── final/                      # CSV export và snapshot để kiểm tra/trao đổi
└── warehouse/                  # Chỉ artifact tùy chọn; Warehouse chuẩn nằm trong SQL Server
```

`src/warehouse/` là module Python được đề xuất để tách trách nhiệm code. `sql/warehouse/` chứa DDL và truy vấn warehouse. Folder `data/warehouse/` không thay thế database Warehouse và không được coi là nguồn sự thật; chỉ dùng nếu sau này cần lưu batch manifest, file trao đổi hoặc bản export.

## 4. Warehouse model đề xuất

### Mức hiện tại: curated current-state table

Warehouse không nhận `final.rental_room` như một bảng đã là Warehouse. Loader đọc Lake final, kiểm tra contract/chất lượng, bỏ trường văn bản/định danh không cần cho đích, lọc giá/diện tích không hợp lệ theo quy tắc đã chốt, rồi nạp current-state vào `dw.rental_room_current` ở database riêng. Bảng v1 giữ grain một dòng mỗi `(source, list_id)` và các thuộc tính phân tích trong một bảng phẳng để đáp ứng phạm vi yêu cầu hiện tại. Nạp lại là full refresh nguyên tử; không lưu lịch sử giá.

### Hướng mở rộng: dimensional warehouse

Khi có nhu cầu BI đa chủ đề hoặc dữ liệu lớn hơn, có thể tách bảng phẳng thành:

- `dw.dim_date`: ngày đăng, ngày scrape, ngày nạp.
- `dw.dim_location`: địa danh/ward theo tên chuẩn, có thể bổ sung mã địa giới khi có nguồn tham chiếu đáng tin cậy.
- `dw.dim_listing_source`: nguồn scrape.
- `dw.dim_listing_type`: loại tin/danh mục.
- `dw.dim_furnishing`: tình trạng nội thất chuẩn hóa.
- `dw.fact_rental_listing_current`: một dòng cho mỗi listing tự nhiên (`source`, `list_id`), chứa giá, diện tích, giá/m², tọa độ, khoảng cách, flood labels, amenity flags và khóa tới các dimension.
- `mart.rental_listing_current`: view hoặc bảng mart dễ dùng cho dashboard và phân tích, không chứa trường thô dài như `body` trừ khi có nhu cầu rõ ràng.

Warehouse phải giữ khóa nguồn tự nhiên (`source`, `list_id`) để trace về Lake. Dùng surrogate key cho dimensions/facts khi cần quan hệ nhiều bảng. Không dùng URL hay tiêu đề làm khóa.

### Lịch sử giá và trạng thái tin: lựa chọn cần định nghĩa

Lake hiện không bảo đảm có lịch sử các lần thay đổi giá của cùng một tin: raw đang tích lũy theo khóa `(source, list_id)` và merge giữ một bản ghi; final được rebuild. Vì vậy không thể tạo fact lịch sử giá đáng tin chỉ từ bảng final hiện có.

- **Nếu mục tiêu trước mắt là dashboard trạng thái mới nhất**: bắt đầu bằng `fact_rental_listing_current`; khi loader chạy lại, cập nhật bản ghi theo `(source, list_id)`.
- **Nếu cần phân tích biến động giá/tin theo thời gian**: phải định nghĩa snapshot grain (mỗi listing mỗi lần scrape/ngày), lưu observation history tại Lake hoặc ghi snapshot bất biến vào Warehouse. Khi đó fact sẽ là `fact_rental_listing_snapshot`, với unique key phù hợp gồm listing và batch/snapshot time.
- Không bật lịch sử bằng cách copy định kỳ cùng một bảng final mà không có snapshot/batch ID; cách đó dễ tạo bản sao giả và không biết giá trị nào thực sự thay đổi.

Khuyến nghị: triển khai current-state trước; chốt nhu cầu history trước khi thiết kế snapshot fact và thay đổi scraper.

## 5. Hợp đồng dữ liệu giữa Lake và Warehouse

Trước khi viết ETL, lập data contract cho từng trường:

- Tên cột, kiểu dữ liệu SQL, nullable, đơn vị, định nghĩa nghiệp vụ, nguồn gốc, quy tắc chuẩn hóa.
- Natural key: `(source, list_id)`.
- Các cột thời gian: phân biệt `posted_date`, `scraped_at`, `warehouse_loaded_at` và `batch_id`.
- Định nghĩa `flood_risk_label` và các cờ amenity; NULL không được tự chuyển thành `0`.
- Giá/diện tích/giá mỗi m²: xác định đơn vị VND, m², kiểm tra outlier và quy tắc precision.
- Địa danh: dùng tên chuẩn làm thuộc tính hiển thị; chỉ gán mã hành chính khi đối chiếu với dimension tham chiếu đã được kiểm chứng.
- Giữ `body`, `subject`, URL và trường nhận diện cá nhân theo nguyên tắc tối thiểu cần thiết; quyết định rõ dữ liệu nào được phép sao chép vào warehouse và thời gian lưu.

Contract phải có version. Khi schema Lake đổi, ETL phải phát hiện và báo lỗi tương thích thay vì âm thầm bỏ cột hoặc ghi sai vị trí.

## 6. Quy trình ETL đề xuất

1. **Preflight**: kiểm tra kết nối cả hai database, schema/version, quyền, nguồn không rỗng và job đang không chạy trùng.
2. **Xác định batch**: tạo `batch_id`, thời điểm bắt đầu, source watermark và contract version.
3. **Extract**: đọc một tập dữ liệu nhất quán từ curated output của Lake. Giai đoạn đầu có thể full extract 5 nghìn dòng; sau đó mới tối ưu watermark/incremental.
4. **Validate**: kiểm tra schema, duplicate key, null bắt buộc, loại dữ liệu, miền giá trị, nhãn flood hợp lệ và tổng số dòng.
5. **Transform**: áp dụng mapping dimension/fact một cách deterministic; không sửa dữ liệu nguồn; lưu số dòng bị reject cùng lý do.
6. **Stage**: bulk-load batch vào `stg` với `batch_id`, không ghi thẳng vào fact/mart.
7. **Reconcile**: đối chiếu row count, distinct natural keys, null counts và tổng kiểm tra các thuộc tính quan trọng giữa extract và stage.
8. **Load dimensions**: upsert dimension trước facts; xử lý dimension không tìm thấy theo chính sách rõ ràng (unknown member), không mất dòng fact.
9. **Load facts**: dùng unique constraints và `MERGE`/update-insert có transaction; lựa chọn current-state hay snapshot grain như mục 4.
10. **Publish**: chỉ đánh dấu batch thành công sau khi toàn bộ load/reconcile commit; mart chỉ nhìn thấy batch đã publish.
11. **Audit và dọn staging**: ghi thống kê và lỗi; giữ staging theo chính sách retention để điều tra, không xóa dữ liệu lịch sử cần audit.

ETL phải idempotent: chạy lại cùng batch không tạo duplicate và không làm trạng thái sai. Mỗi bước phải có transaction/rollback phù hợp. Không truncate fact production trước khi staging đã hợp lệ.

## 7. Quản trị, vận hành và bảo mật

- Thêm cấu hình riêng cho Warehouse, ví dụ server/database/user; không ghi credential vào source code hoặc tài liệu.
- Dùng Windows auth trong môi trường phát triển hiện tại nếu phù hợp; khi deploy, dùng account riêng tối thiểu quyền cho Lake-read và Warehouse-write.
- Tách quyền DDL bootstrap khỏi account runtime ETL.
- Tạo bảng audit/job control, ví dụ `ctl.etl_batch` và `ctl.etl_step_log`, gồm batch ID, source watermark, counts, timestamps, status, error summary, contract version.
- Log không ghi toàn bộ `body`, thông tin nhạy cảm, connection string hoặc credentials.
- Dùng timeout, retry có giới hạn cho lỗi tạm thời; lỗi data/schema phải dừng rõ ràng, không được biến thành thành công.
- Có backup/restore thử nghiệm cho cả hai database; không coi CSV export là backup.
- Quản lý DDL qua migration có version, backup trước migration, kiểm tra trên development trước production.

## 8. Lộ trình triển khai theo phase và tiêu chí hoàn tất

### Phase 0 — Chốt yêu cầu và hợp đồng

- Chọn current-state hay snapshot history cho warehouse.
- Chốt người dùng đích: Power BI, SQL query, model training hay cả ba.
- Chốt refresh cadence, độ trễ chấp nhận được, retention, các cột nhạy cảm và định nghĩa metrics.
- Lập mapping từ `final.rental_room` sang dimensions/facts và data quality rules.

**Gate:** có data dictionary, grain của fact, khóa, NULL policy và tiêu chí reconcile được duyệt.

### Phase 1 — Thiết kế database đích

- Tạo `RentalDaNangWarehouse` riêng; Lake hiện tại tiếp tục chạy nguyên trạng.
- Thiết kế schema `ctl`, `stg`, `dw`, `mart`.
- Thêm PK/UK/FK/check constraints và index dựa trên truy vấn dự kiến.
- Tạo migration theo version; xác định quyền bootstrap và quyền ETL.

**Gate:** database mới được tạo từ migration sạch; constraints và quyền được xác minh.

### Phase 2 — ETL full-load đầu tiên

- Tạo `src/warehouse/` và cấu hình riêng cho Lake/Warehouse.
- Extract `final.rental_room`; validate và stage theo batch.
- Nạp dimensions trước, sau đó fact current-state và mart.
- Lưu audit counts và trạng thái batch.

**Gate:** tổng dòng nguồn = accepted + rejected; natural key không duplicate; mọi rejects có lý do; rollback không làm hỏng batch đã publish.

**Trạng thái:** đã hoàn thành phiên bản đầu với bảng phẳng `dw.rental_room_current`, lọc `price_vnd`/`size_m2` NULL hoặc 0, chuẩn hóa category chỉ còn `Phòng trọ`/`Căn hộ/Chung cư`, lọc ward theo allowlist 12 phường Đà Nẵng, loại tọa độ NULL/không hợp lệ, gán `rooms = "1"` cho category `Phòng trọ`, chuẩn hóa `rooms` có hậu tố `PN` thành số cho căn hộ, giữ nhãn `"Không xác định"` cho căn hộ thiếu số phòng và loại giá trị phòng căn hộ không phải số như `nhiều hơn 10 PN`, khóa tự nhiên, kiểm tra trùng khóa và transactional full refresh. Bảng audit chi tiết, staging riêng và star schema vẫn là phần mở rộng.

### Phase 3 — Orchestration và vận hành

- Thêm bước chạy warehouse độc lập với pipeline scrape/process.
- Chỉ chạy sau khi Lake final đã hoàn tất và vượt validation.
- Hỗ trợ chạy lại, khóa tránh chạy chồng lấn, mã thoát lỗi chính xác và cảnh báo thất bại.
- Cấu hình lịch chạy phù hợp cadence scrape.

**Gate:** chạy lại batch không tạo duplicate; lỗi giữa chừng có thể resume/retry an toàn.

### Phase 4 — Incremental và lịch sử (nếu được yêu cầu)

- Đo chi phí full-load trước; với dữ liệu hiện tại có thể chưa cần incremental phức tạp.
- Chọn watermark đáng tin cậy (ví dụ ingestion/batch time), không dùng `scraped_at` nếu field đó không bảo đảm được cập nhật/monotonic.
- Nếu cần lịch sử, bổ sung snapshot capture upstream trước khi xây `fact_rental_listing_snapshot`.

**Gate:** test bản ghi mới, bản ghi thay đổi, bản ghi biến mất/ẩn, duplicate delivery và chạy bù batch cũ.

### Phase 5 — Dashboard, tối ưu và mở rộng

- Cấp quyền đọc chỉ trên `mart`.
- Kiểm tra query plan, index, thời gian refresh và dung lượng.
- Chỉ cân nhắc partitioning, columnstore, orchestration platform hoặc object-storage lake khi volume/SLA chứng minh cần thiết.

**Gate:** truy vấn người dùng đạt SLA đã thỏa thuận; backup, recovery và data lineage có thể diễn tập.

## 9. Chiến lược kiểm thử và nghiệm thu

- **Unit tests**: field mapping, chuẩn hóa, key construction, NULL semantics, dimension resolution.
- **Integration tests**: SQL Server test database; DDL migrations; staging-to-dw transaction; constraints.
- **Idempotency tests**: cùng batch nạp hai lần không phát sinh duplicate hoặc thay đổi counts sai.
- **Failure tests**: mất kết nối, lỗi constraint, lỗi transform, rollback giữa chừng, resume.
- **Reconciliation tests**: source/extract/stage/fact counts, key uniqueness, counts theo nguồn/ngày/nhãn.
- **Data quality checks**: giá/diện tích âm hoặc bất thường, tọa độ ngoài miền, flood label ngoài 0–2, furnishing/ward chưa chuẩn.
- **Acceptance run**: full-load dữ liệu đại diện, đối chiếu truy vấn Warehouse với Lake, người dùng xác nhận mart và dashboard.

## 10. Rủi ro và cách giảm thiểu

| Rủi ro | Ảnh hưởng | Giảm thiểu |
|---|---|---|
| Nhầm `final.rental_room` trong Lake với Warehouse | Coupling, thay đổi pipeline ảnh hưởng BI | Dùng DB riêng và contract ổn định |
| Fact grain không rõ | Đếm tin/giá sai, duplicate | Chốt grain và natural key trước DDL |
| Dùng `scraped_at` làm change watermark không đáng tin | Bỏ sót bản ghi cập nhật | Audit batch/watermark riêng; bổ sung snapshot upstream nếu cần |
| Load trực tiếp vào bảng production | Bảng dở dang khi job lỗi | Staging + reconcile + transaction + publish |
| NULL biến thành 0/false | Sai kết quả phân tích | Giữ semantics NULL trong contract và tests |
| Copy toàn bộ `body`/URL không cần thiết | Tăng rủi ro riêng tư, dung lượng | Data minimization và retention |
| Hai pipeline chạy đồng thời | Đọc final đang rebuild | Job lock hoặc publish marker/batch boundary |
| Chỉ có CSV export | Không có lineage/recovery đầy đủ | Warehouse SQL là nguồn phân tích; CSV chỉ là artifact |

## 11. Thứ tự thực thi khuyến nghị

1. Chốt current-state warehouse trước; ghi rõ có/không cần lịch sử giá.
2. Chốt data contract từ `final.rental_room` và DQ rules.
3. Tạo database `RentalDaNangWarehouse` riêng và schema `ctl/stg/dw/mart`.
4. Xây full-load ETL có staging, audit, transaction, reconciliation, idempotency.
5. Tạo mart và kiểm chứng với truy vấn Lake.
6. Thêm orchestration sau pipeline Lake, nhưng giữ lệnh warehouse độc lập để chạy lại.
7. Chỉ triển khai incremental/history sau khi xác nhận cách ghi nhận thay đổi upstream.

**Khuyến nghị tổng thể:** giữ SQL Server Lake hiện tại ổn định; dùng `src/warehouse/` làm ranh giới code rõ ràng và database `RentalDaNangWarehouse` làm ranh giới lưu trữ. Bản triển khai hiện tại là current-state table phẳng có lọc, kiểm tra khóa và transactional replacement; bổ sung staging/audit/star schema khi nhu cầu BI tăng. Không xây historical price fact cho đến khi có cơ chế snapshot đáng tin cậy.
