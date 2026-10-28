# Hồ sơ migration: Bronze trên Cloudflare R2, Silver/Gold trên PostgreSQL

> **Tài liệu tham khảo migration đã hoàn tất**, không phải checklist chạy lại. Hướng dẫn thiết lập và vận hành hiện tại nằm trong [README.md](./README.md) và [DATA_PIPELINE.md](./DATA_PIPELINE.md). Các mục hiện trạng trước migration và thiết kế trong tài liệu này ghi lại bối cảnh/quyết định lịch sử.

## 1. Mục tiêu và phạm vi

Thay thế cách lưu trữ hiện tại trên SQL Server bằng kiến trúc tách riêng:

- **Bronze:** payload gốc bất biến trên Cloudflare R2, lưu theo JSON Lines và Hive-style object key.
- **Silver:** dữ liệu đã parse, chuẩn hoá, geocode và bổ sung đặc trưng không gian trên PostgreSQL + PostGIS.
- **Gold:** dữ liệu curated, ổn định cho FastAPI và huấn luyện/đánh giá mô hình AI trên PostgreSQL.

Phạm vi kế hoạch là chuyển lưu trữ và tổ chức code. Không chủ trương viết lại thuật toán parser, bộ lọc tin, logic text hiện có hoặc quy tắc nghiệp vụ trong một lần di trú. Các xử lý đang chạy được giữ lại, bọc bằng các adapter đọc/ghi mới và chỉ thay đổi khi có kiểm thử, duyệt riêng.

## Trạng thái triển khai

Migration runtime đã hoàn tất theo quyết định của dự án:

- Bronze payload mới được ghi thành JSONL bất biến lên R2, kèm manifest, SHA-256 và Hive-style keys.
- PostgreSQL giữ ledger/index Bronze trong `ops`; payload body không được đưa vào PostgreSQL.
- Các repository runtime chuyển sang `silver`/`gold` PostgreSQL; luồng scrape → replay → merge → geocode → spatial → flood → text và transform Gold giữ nguyên các parser/quy tắc hiện có.
- `scripts/init_db.py` áp dụng migrations PostgreSQL. Importer SQL Server chỉ phục vụ migration một lần và đã được gỡ sau khi người dùng xác nhận chuyển đổi hoàn tất.
- Notebook demo đã chuyển sang nạp secrets từ `.env`; file `.env` local không còn được theo dõi trong Git.

Pipeline thường ngày chỉ dùng R2 và PostgreSQL/PostGIS. Module kết nối SQL Server, helper executor, SQL scripts cũ, migration importer và dependency `pyodbc` đã được gỡ để tránh nhầm backend. Tài liệu bên dưới lưu lại bối cảnh và quyết định kiến trúc đã dùng trong quá trình chuyển đổi; không phải danh sách việc cần chạy lại.

## 2. Hiện trạng trước migration (lưu trữ để tham khảo)

Các gạch đầu dòng dưới đây mô tả repository tại thời điểm lập kế hoạch, không mô tả runtime hiện tại:

- Scraper khi đó lưu payload JSON/HTML vào `raw.listing_payloads` trên SQL Server.
- Replay khi đó dựng `raw.listings`; các bước merge/geocode/spatial/flood/text ghi vào bảng SQL Server `processed.*` và `final.*`.
- Kết nối, repository và truy vấn SQL Server khi đó nằm trong `src/db/` và `sql/`; các module này đã được gỡ sau migration.
- Warehouse khi đó dùng một database SQL Server riêng; runtime hiện tại dùng PostgreSQL `silver`/`gold`.
- Notebook R2/PostgreSQL khi đó mới là thử nghiệm, chưa có adapter production trong `src/`.
- Tại thời điểm khảo sát chưa thấy FastAPI trong source; Gold vẫn được thiết kế như lớp consumer cho API/model.

### Lưu ý bảo mật trước khi dùng R2 thật

Notebook demo trước đây có thông tin truy cập dịch vụ lưu trực tiếp trong cell; cell hiện tại đã được thay bằng cấu hình từ `.env` và output của cell đã được xoá. **Vẫn phải thu hồi/rotate các credential đã từng được ghi vào notebook**, và dọn lịch sử Git theo quy trình bảo mật của nhóm; thay nội dung cell không thu hồi các credential hoặc xoá chúng khỏi commit cũ. Không chép giá trị bí mật vào tài liệu, log, test hay file cấu hình được commit.

## 3. Kiến trúc đã triển khai

```text
Website/API
    │
    ▼
Scraper hiện tại
    │ payload mới + khóa (source, list_id)
    ▼
R2 Bronze
    ├── JSON Lines bất biến, chia batch
    ├── manifest và checksum cho mỗi batch
    └── Hive-style key theo source/ngày ingest
             │
             ▼
ETL đọc batch đã publish
    ├── parse bằng hàm parser hiện có
    ├── validate và lưu lỗi/reject có nguyên nhân
    ├── nạp Silver
    ├── geocode và PostGIS spatial enrichment
    └── dựng Gold theo hợp đồng tiêu thụ
             │
             ▼
PostgreSQL local + PostGIS
    ├── ops: batch, ledger chống trùng, trạng thái ETL
    ├── silver: dữ liệu parse/chuẩn hoá/enrich
    └── gold: bảng/view phục vụ API và AI
             │
             ├── FastAPI (read-only với Gold)
             └── model training / offline features
```

R2 lưu object/file, không phải cơ sở dữ liệu bảng. PostgreSQL là nơi truy vấn dữ liệu quan hệ và địa lý. Schema `ops` chỉ chứa metadata điều phối, lineage và khóa ingest; payload đầy đủ vẫn chỉ nằm trong R2.

## 4. Thiết kế Bronze trên R2

### 4.1. Định dạng object

Mỗi dòng JSONL là một payload độc lập, UTF-8, có envelope ổn định:

| Trường | Ý nghĩa |
|---|---|
| `source` | Mã nguồn scraper, ví dụ `nhatot_canho` |
| `list_id` | Khóa tin trong nguồn |
| `payload_format` | `json` hoặc `html` |
| `payload` | JSON object gốc hoặc HTML gốc/fallback metadata hiện được parser sử dụng |
| `source_url` | URL nguồn nếu có |
| `scraped_at` | Thời điểm scrape UTC |
| `batch_id` | Mã lần ghi batch |
| `schema_version` | Phiên bản envelope Bronze |

Không chuẩn hoá, cắt bớt hay parse payload ở bước ghi Bronze. Cần quyết định riêng có giữ HTML nguyên văn, HTML đã nén hay cả hai; mặc định ưu tiên bảo toàn chính xác đầu vào parser hiện có.

### 4.2. Hive-style object key

Đề xuất object key:

```text
bronze/listings/source=nhatot_canho/ingest_year=2026/ingest_month=10/ingest_day=17/batch_id=<uuid>/part-00000.jsonl
```

- Chia partition theo **ngày ingest** và `source`, không partition theo `list_id` vì cardinality cao.
- Dùng UTC, ID batch không tái sử dụng; object đã publish là bất biến.
- Một batch có thể có nhiều `part-xxxxx.jsonl` theo giới hạn kích thước cấu hình; không tạo object quá nhỏ cho từng tin.
- Có thể bật gzip thành `.jsonl.gz` sau khi đo kích thước và tốc độ; định dạng logic vẫn JSON Lines. Quyết định này phải được ETL reader hỗ trợ và ghi rõ trong manifest.
- Không giả định thư mục thực sự tồn tại trên R2: Hive path là quy ước prefix/key, không phải filesystem.

### 4.3. Manifest và tính bền vững

Mỗi batch có manifest JSON riêng với `batch_id`, danh sách object key, source, thời gian ingest, số dòng, checksum, schema version và trạng thái. Chỉ batch có manifest hoàn chỉnh mới được ETL coi là đã publish.

Thứ tự ingest an toàn:

1. Lấy danh sách ID đã commit từ ledger `ops.bronze_payload_index` trong PostgreSQL; loại duplicate trong chính lượt scrape.
2. Ghi các JSONL part với key duy nhất vào vùng/prefix batch đang tạo.
3. Đọc HEAD hoặc kiểm tra checksum, kích thước và số bản ghi đã upload.
4. Ghi manifest hoàn tất lên R2.
5. Trong transaction PostgreSQL, ghi batch và các khóa `(source, list_id)` vào ledger ở trạng thái committed, gắn với object key.
6. Chỉ sau khi commit ledger mới coi payload là đã lưu để các lượt scrape sau bỏ qua.

R2 và PostgreSQL không chia sẻ transaction phân tán. Vì vậy thao tác phải idempotent: retry cùng batch dùng cùng `batch_id`/checksum; object upload thành công nhưng ledger thất bại được nhận biết như orphan để retry hoặc dọn sau thời gian chờ. Không đánh dấu ID đã ingest trước khi object được xác thực và manifest được publish.

### 4.4. Chính sách lưu giữ

- Không overwrite payload cũ khi trùng `(source, list_id)` theo yêu cầu hiện tại.
- Không xoá batch Bronze sau khi ETL thành công; retention/archive chỉ quyết định sau khi có backup, yêu cầu pháp lý và ước tính chi phí.
- Khi có yêu cầu lưu lịch sử thay đổi tin, thiết kế version key riêng theo lần quan sát; không âm thầm đổi semantics hiện tại.

## 5. Thiết kế PostgreSQL + PostGIS

### `ops` — điều phối và lineage

Các bảng tối thiểu dự kiến:

- `ops.ingestion_batch`: batch ID, source, trạng thái, thời gian bắt đầu/kết thúc, số record, checksum/manifest, lỗi.
- `ops.bronze_payload_index`: unique `(source, list_id)`, object key, payload format, scraped time, batch ID, trạng thái ingest.
- `ops.etl_batch`/`ops.etl_step`: batch Bronze được xử lý, phiên bản parser/contract, counts input/output/reject, trạng thái từng bước.

Ledger chỉ lưu metadata đủ để deduplicate và truy vết; không sao chép body/HTML vào PostgreSQL.

### `silver` — dữ liệu chuẩn hoá và enrichment

`silver.listings` được lưu theo `(source, list_id)`. Bước merge tạo `silver.merged` và loại tin đăng trùng giữa các nguồn chỉ theo `body` sau khi gộp khoảng trắng và chuyển về chữ thường Unicode; body rỗng được giữ lại và nếu trùng thì giữ bản ghi đầu tiên.

- `silver.listing`: kết quả parse theo các cột chuẩn hiện tại, gồm subject/body nếu cần cho feature engineering.
- `silver.listing_location`: kết quả địa chỉ/toạ độ, trạng thái geocode, score và nguồn geocode nếu cần tách vòng đời geocode.
- `silver.listing_spatial`: khoảng cách đến CBD, sân bay, bãi biển gần nhất/mã bãi, trường gần nhất/mã trường và feature không gian.
- Reject/error có thể lưu ở `ops` hoặc `silver.rejected_record` với batch ID, source/list ID, bước lỗi và lý do; tránh lưu duplicate toàn payload.

Chuyển đổi đầu tiên nên giữ tên trường và quy tắc dữ liệu tương thích với `raw.listings`, `processed.merged`, `processed.geocoded`, `processed.spatial`; chỉ đổi schema khi đã có mapping và test parity.

### PostGIS và GIS

- Bật extension PostGIS bằng migration có kiểm tra quyền.
- Lưu điểm listing ở kiểu `geography(Point, 4326)` hoặc geometry SRID 4326 theo quyết định thống nhất; tạo index GiST.
- Nạp bãi biển, trường đại học, sân bay/CBD thành bảng reference có mã ổn định, tọa độ, SRID và nguồn/ghi chú xác minh.
- Tính nearest feature bằng `ST_Distance` và `ORDER BY ... LIMIT 1`; với `geography`, đơn vị trả về là mét. Nếu output contract hiện lưu km, chia đổi và làm tròn đúng quy tắc hiện hành.
- Trước khi thay Haversine, test một bộ tọa độ cố định để đối chiếu sai khác và thống nhất đơn vị/rounding.
- Tích hợp polygon flood vào PostGIS là tuỳ chọn giai đoạn sau; trước hết giữ thuật toán flood hiện có, chỉ chuyển input/output và chứng minh parity.

### `gold` — hợp đồng tiêu thụ

- `gold.rental_listing_current`: current-state curated cho FastAPI và truy vấn ứng dụng. Khóa `(source, list_id)` vẫn có thể được dùng làm khóa đích; việc khử tin trùng nội dung diễn ra ở bước merge, không phải warehouse transform.
- `gold.rental_listing_features`: tập feature ổn định cho training/inference; định nghĩa rõ target, feature time, NULL, loại dữ liệu và leakage.
- API nên đọc view/table Gold bằng DB role chỉ đọc; không cho request path truy vấn trực tiếp Bronze hoặc tự chạy ETL.
- Gold cần tách version/contract của API khỏi tên bảng Silver nội bộ; có thể dùng view versioned khi thay schema.
- Nếu dữ liệu training cần snapshot lịch sử, lưu feature/label snapshot có `dataset_version`/`as_of` riêng. Current-state không thể tự tái tạo lịch sử giá.

## 6. Tổ chức source code đề xuất

Giữ parser và logic nghiệp vụ đang có; thêm ranh giới storage rõ ràng, không tạo framework lớn:

```text
src/
├── scrape/                    # Scraper và parser hiện có; parser không phụ thuộc DB
├── storage/
│   ├── r2_client.py           # Tạo S3-compatible client từ cấu hình môi trường
│   ├── bronze_writer.py       # JSONL batch, checksum, manifest, retry
│   └── bronze_reader.py       # Liệt kê/đọc batch đã publish
├── db/
│   ├── postgres.py            # PostgreSQL engine/connection và transaction
│   └── repositories/          # Repo ops/silver/gold
├── process/
│   ├── rebuild_silver.py      # Đọc Bronze, replay parser, validate, publish Silver
│   ├── geocode_with_arcgis.py # Giữ nghiệp vụ hiện có; đổi adapter nguồn/đích
│   ├── spatial_features.py    # Chuyển truy vấn khoảng cách sang PostGIS theo contract
│   ├── flood_state.py         # Giữ logic, thay persistence khi đã kiểm chứng
│   └── build_gold.py          # Curate Gold cho API/model
└── api/                       # Chỉ tạo khi bắt đầu triển khai FastAPI

sql/
└── postgres/
    ├── migrations/            # DDL có version cho extension/schema/table/index
    └── queries/               # Query PostGIS/ETL cần quản lý

tests/
├── unit/                      # Parser, contract, transform, key/path
├── integration/               # R2 mock/local, PostgreSQL + PostGIS
└── fixtures/                  # Payload nhỏ đã làm sạch, không có credential/PII
```

`main.py` hiện điều phối pipeline đơn giản; giai đoạn đầu có thể giữ một CLI với command rõ ràng (`scrape`, `bronze-commit`, `silver`, `gold`, `all`) thay vì thêm Airflow/Dagster. Chỉ tách orchestrator khi cadence, retry, dependency hoặc số job vượt khả năng CLI.

## 7. Cấu hình và môi trường

- R2: endpoint, bucket, access key/secret key, region tương thích S3 và timeout lấy từ environment/secret store.
- PostgreSQL: `DATABASE_URL`/DSN riêng theo môi trường; driver PostgreSQL được lựa chọn và pin trong dependency manifest.
- Local development: dùng Docker Compose PostgreSQL có PostGIS, volume có tên, healthcheck và script migration; không expose port ra mạng công cộng nếu không cần.
- Cloud migration: thay DSN, secret binding, TLS/CA và endpoint; không đổi parser, tên contract Gold hay logic ETL.
- Có profile `dev`, `test`, `prod`; không dùng notebook làm nơi cấu hình hoặc chạy production.
- Không log credential, raw HTML đầy đủ hoặc URL ký tạm thời.

## 8. Lộ trình triển khai và cổng nghiệm thu

### Phase 0 — Bảo mật, kiểm kê, chốt contract

- Rotate credential R2 xuất hiện trong notebook; xoá secret khỏi notebook/output và xử lý lịch sử Git theo chính sách.
- Chốt sources, payload envelope, Hive partition, kích thước batch, retention, retry và quy tắc tin trùng.
- Kiểm kê số payload, số listing, khóa thiếu payload và các output cần bảo toàn trong SQL Server.
- Đóng băng một tập fixture nhỏ, loại bỏ thông tin bí mật/PII nếu cần.

**Gate:** không còn credential hoạt động trong source/notebook/history đã xử lý; có contract Bronze/Silver/Gold và baseline counts được duyệt.

### Phase 1 — Dựng nền PostgreSQL và PostGIS local

- Khởi tạo PostgreSQL/PostGIS local, migration versioned, role riêng cho migration/runtime/API.
- Tạo schema `ops`, `silver`, `gold`, key/index/check constraints và job-state model.
- Tạo bảng reference GIS và kiểm thử SRID, `ST_Distance`, GiST.

**Gate:** tạo database rỗng từ migration sạch được; test kết nối, rollback và privilege pass.

### Phase 2 — Bronze R2 writer/reader

- Thay persistence payload của scraper bằng writer batch JSONL bất biến.
- Dedupe qua ledger, tạo manifest/checksum, chịu được retry và xử lý object orphan.
- Reader chỉ đọc batch có manifest complete; xác thực schema version, checksum và row count.
- Trong thời gian đầu giữ SQL Server làm sink phụ hoặc so sánh, không coi hai nơi cùng là nguồn chuẩn lâu dài.

**Gate:** thử upload thành công, duplicate scrape, timeout giữa part/manifest/ledger, retry, đọc lại JSON/HTML chính xác; không mất ID đã cam kết.

### Phase 3 — Replay Bronze sang Silver (shadow)

- Đọc R2 Bronze và gọi nguyên parser hiện có.
- Áp dụng cùng bộ lọc listing/normalization hiện tại; reject được đếm và có lý do.
- Ghi staging theo `batch_id`; kiểm tra khóa, schema, counts; publish Silver transactionally/idempotently.
- Chạy song song với SQL Server trên cùng input; so sánh theo `(source, list_id)` và từng cột trọng yếu.

**Gate:** mọi chênh lệch đều giải thích được; không có mất khóa âm thầm; chạy lại cùng batch không tạo duplicate.

### Phase 4 — PostGIS, Gold và parity downstream

- Di chuyển/geocode coordinates và report; giữ kết quả geocode hiện có hoặc cache để tránh gọi ArcGIS lại không cần thiết.
- Chuyển phép tính nearest beach/university sang PostGIS, kiểm tra km và mã nearest.
- Dựng Gold, kiểm thử consumer contract, feature leakage, NULL semantics và output AI.
- So sánh Gold với `final.rental_room`/Warehouse hiện tại theo khóa và số liệu.

**Gate:** geocode/spatial/flood/text parity đạt ngưỡng được duyệt; Gold query ổn định; rollback đã diễn tập.

### Phase 5 — Cutover có thể rollback

1. Backup SQL Server và đóng băng/ghi nhận watermark.
2. Chạy full backfill toàn bộ Bronze lịch sử; reconcile số payload, unique key và số dòng từng lớp.
3. Chạy ít nhất một chu kỳ shadow hoàn chỉnh; ký duyệt chênh lệch.
4. Chuyển orchestrator sang R2 → PostgreSQL; đổi consumer sang Gold mới.
5. Giữ SQL Server read-only trong khoảng thời gian rollback đã chốt; không xoá bảng cũ.
6. Nếu lỗi, đổi cấu hình consumer/orchestrator về SQL Server snapshot và điều tra, không ghi hai nguồn đồng thời tuỳ tiện.

**Gate:** dashboard/reports/API/model smoke tests pass; latency, count, error rate và backup đã kiểm chứng.

### Phase 6 — PostgreSQL cloud (tương lai)

- Chọn managed PostgreSQL có PostGIS và extension/version phù hợp; xác minh network, TLS, backup/PITR, storage, connection pool và chi phí.
- Chuyển database qua backup/restore hoặc logical replication theo downtime cho phép; kiểm tra SRID/index/function PostGIS.
- Thay secret/DSN/observability, chạy canary rồi cutover; giữ local làm dev/test, không làm writer dự phòng song song.

**Gate:** restore drill, failover expectations và performance đạt SLA được duyệt.

## 9. Di trú dữ liệu và chuyển đổi an toàn

- Trước di trú, export các payload hiện có từ SQL Server thành JSONL theo envelope mới; kiểm tra HTML không bị biến dạng encoding và JSON parse lại được.
- Dùng checksum để đối chiếu payload nguồn/đích; ghi manifest và thống kê theo source/date.
- Những listing SQL Server không có payload gốc không thể dựng lại payload chính xác. Phải xuất chúng thành legacy snapshot có nhãn rõ ràng hoặc backfill từ website khi khả thi; không trộn giả payload đã chuẩn hoá vào vùng Bronze như thể dữ liệu nguồn.
- Backfill Bronze trước, sau đó replay vào Silver/Gold. Không chuyển thẳng bảng `final` sang Gold mà bỏ qua validation.
- Không drop SQL Server tables/database trong cutover. Giữ read-only và backup đến khi rollback window kết thúc, archive được xác nhận và có restore test.

## 10. Kiểm thử, chất lượng và quan sát vận hành

- **Unit:** parser không đổi, serialization JSONL, HTML UTF-8, key/path partition, dedupe và filter.
- **Integration:** R2-compatible endpoint hoặc mock với kiểm thử manifest/upload/read/retry; PostgreSQL + PostGIS cho migration, constraints, geography và query nearest.
- **Data quality:** source/list ID không rỗng, unique key, schema version, thời gian UTC, geometry hợp lệ, tọa độ trong bbox, giá/diện tích hợp lệ, tỷ lệ reject được giải thích.
- **Reconciliation:** Bronze rows = parse accepted + rejected; Silver distinct keys đúng; Gold counts phân nhóm source/category/ward đối chiếu baseline.
- **Idempotency/failure:** chạy batch hai lần, lỗi sau upload trước manifest, sau manifest trước ledger, ETL crash trước publish, retry sau commit.
- **Observability:** log batch ID, object key, counts, duration, retries và error summary; không log payload nhạy cảm.
- **Cost:** đo dung lượng Bronze, request/list operation, egress, PostgreSQL storage/index, backup và chi phí geocode trước mở rộng.

## 11. Quyết định cần chốt trước khi code

| Chủ đề | Đề xuất mặc định |
|---|---|
| Nguồn chuẩn payload | R2 Bronze sau khi object + manifest được xác thực |
| Chống trùng | PostgreSQL `ops.bronze_payload_index`, unique `(source, list_id)`; payload không overwrite |
| Định dạng Bronze | JSON Lines, một record envelope cho mỗi tin; gzip chỉ sau benchmark |
| Partition | `source` + ingest date + batch ID; không partition theo `list_id` |
| Silver/Gold | PostgreSQL local + PostGIS, schema tách lớp |
| GIS | PostGIS geography; output khoảng cách giữ contract km hiện tại |
| Parser | Tái sử dụng parser; không thay thuật toán trong migration |
| Orchestration | CLI hiện có trước; chưa cần Spark/Airflow cho quy mô hiện tại |
| Cutover | Shadow run, full backfill, parity, switch bằng cấu hình, giữ SQL Server read-only |
| Lịch sử giá | Chưa có; cần versioned observations/snapshot riêng nếu muốn phân tích biến động |

## 12. Rủi ro chính và biện pháp

| Rủi ro | Biện pháp |
|---|---|
| R2 upload thành công nhưng PostgreSQL ledger thất bại (hoặc ngược lại) | Manifest, batch state machine, retry idempotent, orphan reconciliation |
| Dedupe chỉ dựa trên listing keys PostgreSQL nhưng mất database | Backup/PITR cho `ops`, khả năng rebuild ledger từ manifests/JSONL |
| Chuyển đổi âm thầm làm thay đổi parser output | Shadow run và so sánh theo natural key/cột |
| PostGIS cho số khác Haversine | Chốt geography/geometry, đơn vị, rounding và test tọa độ cố định |
| Lệ thuộc notebook demo chứa credentials | Rotate trước, secret store/environment sau, kiểm tra Git history |
| HTML/JSON payload lớn hoặc chứa dữ liệu nhạy cảm | Compression, access control, retention, không log/copy payload xuống DB |
| Mất dữ liệu legacy không có payload | Snapshot riêng có nguồn gốc rõ hoặc backfill; không giả lập raw |
| Chuyển lên cloud làm lộ DB/chi phí kết nối | Private networking, TLS, least privilege, pooling và cost alert |

## 13. Tiêu chí hoàn tất toàn bộ migration

- Scraper chỉ commit ID sau khi Bronze object và manifest được xác thực.
- Có thể dựng lại Silver và Gold hoàn toàn từ Bronze cùng phiên bản contract/code đã ghi nhận.
- Một batch chạy lại không phát sinh duplicate và không publish dữ liệu dở dang.
- Parser/logic nghiệp vụ được giữ nguyên hoặc mọi thay đổi được duyệt/test riêng.
- Có lineage từ Gold → Silver → batch manifest → object Bronze.
- API/model chỉ phụ thuộc vào Gold contract, không phụ thuộc SQL Server hoặc chi tiết object key R2.
- Có backup/restore drill cho R2 metadata/manifest và PostgreSQL, cùng quy trình rollback.
- SQL Server chỉ được ngừng sử dụng sau khi parity, cutover và thời hạn lưu giữ được xác nhận.

## 14. Cách vận hành phiên bản đã triển khai

1. Cài dependencies từ `requirements.txt`.
2. Sao chép `.env.example` thành `.env`, rồi điền `POSTGRES_DSN`, `R2_ENDPOINT_URL`, `R2_BUCKET_NAME`, `R2_ACCESS_KEY_ID` và `R2_SECRET_ACCESS_KEY` local. Không gửi secret qua chat hoặc commit file `.env`.
3. Cài PostgreSQL/PostGIS local, sau đó chạy `python scripts/init_db.py` để áp dụng migrations nếu database chưa được khởi tạo.
4. Chạy `python main.py --step all`; `--skip-scrape` bỏ bước crawl nhưng vẫn replay toàn bộ Bronze payload từ R2.

Không chạy importer SQL Server: dữ liệu đã được migrate và công cụ một lần đã được gỡ khỏi repository.

Runtime mapping:

| Pipeline output | PostgreSQL/R2 target |
|---|---|
| Payload scrape | R2 JSONL; `ops.bronze_payload_index` chỉ lưu metadata/index |
| Parser replay | `silver.listings` |
| Merge/geocode/report/spatial | `silver.merged`, `silver.geocoded`, `silver.geocode_report`, `silver.spatial` |
| Text feature output | `silver.rental_room` |
| Existing warehouse transform output | `gold.rental_room` |

Các phép tính khoảng cách, parser, filter và warehouse transform chưa được thay đổi trong migration; PostGIS được bật trong schema nhưng chưa thay thế thuật toán Haversine hiện có. Không chạy migration/backfill hoặc truy cập dịch vụ cloud cho tới khi `.env`, backup và quyền truy cập đã được kiểm tra.
