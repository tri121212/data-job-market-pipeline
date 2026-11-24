# Ghi chú nguồn dữ liệu (cập nhật Ngày 2 — 2026-11-24)

## Kết luận: dùng TopDev, không dùng ITviec/TopCV

| Nguồn | Kết quả khảo sát | Quyết định |
|---|---|---|
| ITviec | `robots.txt` cho phép, nhưng mọi URL đều trả **403 — Cloudflare "Just a moment..."** (kể cả `.rss`, `/feed`) | ❌ Bỏ, không vượt Cloudflare |
| TopCV | `robots.txt` cho phép, nhưng trả **403 — Cloudflare "Attention Required"** | ❌ Bỏ |
| JobStreet VN | 403 Cloudflare | ❌ Bỏ |
| **TopDev** | `robots.txt` **Allow: /**, trang chi tiết trả 200, có **JSON-LD `JobPosting`** | ✅ **Dùng** |

Lý do chọn TopDev: dữ liệu có cấu trúc chuẩn schema.org, không phải bám vào CSS class (dễ vỡ), và trang chi tiết render phía server.

## Cách khám phá job
- `https://topdev.vn/sitemap-jobs.xml` → sitemap index, **480 trang**, mỗi trang 20 job URL ⇒ ~9.600 job.
- URL dạng: `https://topdev.vn/detail-jobs/<slug>-<job_id>`.
- Trang `/it-jobs` và `/jobs/search` là **client-rendered** (Next.js) → HTML tải về gần như rỗng, **không** dùng để crawl danh sách.
- Vì vậy pipeline đi theo hướng: **sitemap → URL → tải trang chi tiết → parse JSON-LD**.

## Field map (JSON-LD → bảng của mình)

| Nguồn | Cột đích | Ghi chú |
|---|---|---|
| `title` | `title` | |
| `hiringOrganization.name` | `company` | |
| `hiringOrganization.sameAs` | `company_url` | |
| `identifier.value` | `source_id` | số nguyên, ổn định theo job |
| `industry` | `industry` | ⚠️ không đáng tin (xem dưới) |
| `datePosted` / `validThrough` | `posted_at` / `valid_through` | `YYYY-MM-DD` |
| `skills` (string, phẩy) | `skills[]` | vd `"Sharepoint, Microsoft 365"` |
| `baseSalary.currency` | `currency` | thường `VND` |
| `baseSalary.value.minValue/maxValue` | `salary_min/max` | **string**, phải cast int |
| `baseSalary.value.unitText` | `salary_unit` | `MONTH` |
| `jobLocation.address.addressRegion` | `location_region` | vd "Hải Phòng", "Hồ Chí Minh" |
| `jobLocation.address.addressCountry` | `location_country` | `VN` |
| `description` (HTML) | `description_html` + `description_text` | strip tag bằng BeautifulSoup |
| `employmentType` | `employment_type` | ⚠️ luôn `["OTHER"]` — vô dụng |

## Edge case phát hiện (đã xử lý trong parser)

1. **Lương "Thoả thuận"**: `baseSalary` vẫn tồn tại nhưng `value` là **chuỗi `"Negotiable"`**, không phải object. Parser phải xử lý cả 3 dạng: object có min/max, chuỗi số, chuỗi `"Negotiable"`.
2. **Giá trị lương là string** (`"3000000"`), không phải int → phải `int()`, có thể có dấu phẩy.
3. **`employmentType` luôn `["OTHER"]`** → cấp bậc (intern/fresher/junior/senior) phải suy ra từ **title** hoặc để trống giai đoạn đầu.
4. **`industry` sai**: nhiều job telesales/ngân hàng vẫn ghi `"Information Technology"` → **không lọc IT bằng `industry`**; phải lọc bằng keyword trong title/skills.
5. **Trùng lặp**: cùng một job xuất hiện ở nhiều URL (sitemap + slug khác nhau) → dedupe theo `source_id`.
6. **Slug sitemap không đáng tin**: `hai-phong` khớp `ai`, `data` khớp "data có sẵn" trong job telesales → nếu lọc theo slug phải dùng regex có ranh giới `(^|-)token(-|$)`.

## Lệnh chạy thăm dò

```bash
python -m ingestion.explore --sitemap-page 1 --limit 5
python -m ingestion.explore --limit 3 --save docs/samples/live --out data/explore.jsonl
```

## Fixtures dùng cho test
- `docs/samples/topdev_job_bank.html.gz` — job có lương khoảng (3–16tr).
- `docs/samples/topdev_job_it.html.gz` — job lương "Thoả thuận", 2 skill.
