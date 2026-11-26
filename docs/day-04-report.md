# Báo cáo Ngày 4 — Loader: MinIO → Postgres

> Mục tiêu: đưa 11 job IT đã crawl vào bảng `raw.job_postings`, chạy lại không nhân đôi.
> Ngày: 2026-11-26 · Chi phí: **$0** (Postgres local).

---

## 1. Kết quả

| Hạng mục | Trạng thái |
|---|---|
| `ingestion/load.py` | ✅ |
| Bảng `raw.job_postings` (DDL trong `docker/init/` + loader tự tạo) | ✅ |
| Upsert idempotent | ✅ chạy 2 lần: `11 inserted` → `0 inserted / 11 updated` |
| Test | ✅ 3 test mới (tổng **45**) |
| Commit + push | ✅ |

---

## 2. Vì sao là **upsert**, không phải insert

Job tuyển dụng tồn tại nhiều ngày. Crawler ngày nào cũng thấy lại job cũ → nếu insert thường, bảng sẽ phình gấp N lần theo số ngày.

Thiết kế:
- **1 dòng / 1 job** (`source_id` là PK).
- `first_seen_at`: lần đầu thấy → **không bao giờ đổi** (dùng cho phân tích "job mới trong 7 ngày").
- `last_seen_at`: lần cuối thấy → cập nhật mỗi lần load (dùng để biết job còn sống).

Đây là **SCD-lite**: không giữ lịch sử thay đổi nội dung, nhưng giữ lịch sử tồn tại.

---

## 3. Bảng `raw.job_postings`

| Cột | Kiểu | Vì sao |
|---|---|---|
| `source_id` | text PK | Khoá tự nhiên (đuôi URL job), ổn định qua re-crawl |
| `source` | text | Chuẩn bị cho đa nguồn (thêm nguồn khác sau này) |
| `dt` | date | Partition logic theo ngày, dùng cho incremental dbt |
| `company_id` | text | ID công ty từ JSON-LD (đã sửa hiểu nhầm ở Ngày 3) |
| `title`, `company` | text | Cột tiện cho query nhanh, tránh phải bóc JSONB |
| `is_it_job`, `filter_reason` | bool, text | Audit: biết vì sao bản ghi được giữ |
| `payload` | jsonb | Toàn bộ job đã parse — dbt sẽ dùng lại, không cần crawl lại |
| `crawled_at` | timestamptz | Thời điểm crawl |
| `first_seen_at`, `last_seen_at` | timestamptz | Lịch sử tồn tại |

Đánh index `dt` và `source` vì dbt sẽ lọc theo ngày.

---

## 4. Câu SQL quan trọng

```sql
INSERT INTO raw.job_postings (...)
VALUES (...)
ON CONFLICT (source_id) DO UPDATE SET
    dt            = EXCLUDED.dt,
    title         = EXCLUDED.title,
    company       = EXCLUDED.company,
    payload       = EXCLUDED.payload,
    crawled_at    = EXCLUDED.crawled_at,
    last_seen_at  = now()          -- chỉ cột này "trôi" theo thời gian
RETURNING (xmax = 0) AS inserted;
```

### Mẹo `xmax = 0`
Postgres không trả về "inserted/updated" một cách trực tiếp. Nhưng với `ON CONFLICT DO UPDATE`:
- Dòng **mới chèn** có `xmax = 0`.
- Dòng **bị update** mang `xmax` = transaction id của lần ghi trước.

Nhờ `RETURNING (xmax = 0)` mình đếm được cả hai loại **trong cùng một câu lệnh**, không cần `SELECT` kiểm tra trước (tránh race condition).

Đây là chi tiết hay để kể khi phỏng vấn — thể hiện hiểu Postgres chứ không chỉ biết viết `INSERT`.

---

## 5. Chứng minh idempotent

```
lần 1: 2026-11-26: 40 file(s) -> 11 rows | inserted=11 updated=0
lần 2: 2026-11-26: 41 file(s) -> 11 rows | inserted=0  updated=11
```

Kiểm tra trong DB:
```sql
SELECT count(*) rows, count(DISTINCT source_id) uniq_ids,
       count(*) FILTER (WHERE first_seen_at < last_seen_at) updated_rows
FROM raw.job_postings;
--  rows | uniq_ids | updated_rows
--     11 |       11 |           11
```

`uniq_ids = rows` → không có bản ghi trùng. `updated_rows = 11` → `last_seen_at` đã trôi, `first_seen_at` giữ nguyên.

---

## 6. Code walkthrough

### `config.py` — thêm DSN
```python
pg_host: str = Field("localhost", validation_alias="POSTGRES_HOST")
...
@property
def dsn(self) -> str:
    return f"postgresql://{user}:{password}@{host}:{port}/{db}"
```
Dùng `validation_alias` để tận dụng lại đúng tên biến mà `docker-compose.yml` đã dùng (`POSTGRES_USER`…), không phải đổi compose.

### `load.py` — 4 hàm chính
| Hàm | Việc |
|---|---|
| `parse_jsonl` | đọc JSONL, bỏ dòng trống |
| `record_params` | map 1 record → tham số SQL (`Jsonb` cho payload, `datetime` cho crawled_at) |
| `dates_in_bucket` | lấy danh sách `dt` từ key (`--all`) |
| `upsert_rows` | chạy upsert, đếm insert/update |

`ensure_schema()` chạy DDL `IF NOT EXISTS` mỗi lần load → DB mới toanh cũng tự có bảng, không cần nhớ chạy migrate tay.

### `docker/init/02_raw_job_postings.sql`
DDL đặt trong `docker-entrypoint-initdb.d` để **lần đầu** tạo volume là có bảng luôn. Loader vẫn tự tạo lại nếu thiếu → hai lớp bảo hiểm.

---

## 7. Test (45 tổng)

| File | Test | Nội dung |
|---|---|---|
| `test_load.py` | +3 | parse JSONL bỏ dòng trống, map đủ cột, lấy danh sách ngày |
| còn lại | 42 | như Ngày 3 |

Test **không cần database**: phần SQL thuần được tách khỏi phần kết nối, nên CI nhanh và không flaky. Phần chạy thật với Postgres được kiểm chứng thủ công ở mục 5.

---

## 8. Câu hỏi phỏng vấn

**Q1. Làm sao biết một job là "mới" hay "cũ"?**
> "`first_seen_at` chỉ set khi insert, không update. Job có `first_seen_at` trong 7 ngày gần nhất là job mới; `last_seen_at` cũ quá 7 ngày thì coi như đã hết."

**Q2. Nếu job bị sửa nội dung (đổi lương) thì sao?**
> "Hiện tại em ghi đè `payload` và giữ `first_seen_at` — đủ cho phân tích xu hướng. Nếu cần audit lịch sử thay đổi thì phải thêm bảng `job_posting_history` (SCD Type 2), đánh đổi bằng dung lượng."

**Q3. Tại sao không load thẳng vào bảng phân tích?**
> "Vì raw phải giữ nguyên payload gốc. Mọi logic làm sạch nằm ở dbt staging để có thể sửa và chạy lại mà không mất dữ liệu."

**Q4. `xmax = 0` là gì?**
> "Cột hệ thống của Postgres. Với `ON CONFLICT DO UPDATE`, dòng insert mới có `xmax = 0`, dòng update thì khác 0 — nên `RETURNING (xmax = 0)` cho biết ngay dòng đó vừa insert hay update."

---

## 9. Việc Ngày 5 (chuẩn bị)

- [ ] Cài `dbt-postgres`, tạo project dbt.
- [ ] `stg_job_postings`: parse JSONB → cột, dedupe, cast lương.
- [ ] Test `unique` + `not_null` trên `source_id`.
- [ ] `dbt build` xanh.
