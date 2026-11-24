# Ghi chú nguồn dữ liệu

Cập nhật trong Ngày 2 (khảo sát nguồn).

## Ứng viên

| Nguồn | URL | robots.txt | JS-rendered? | Ghi chú |
|---|---|---|---|---|
| ITviec | https://itviec.com/it-jobs | TODO | TODO | |
| TopCV | https://www.topcv.vn/tim-viec-lam-it | TODO | TODO | |

## Field cần lấy

- `title` — tên vị trí
- `company` — tên công ty
- `salary_raw` — chuỗi lương gốc ("20–30 triệu", "1000 USD", "Thoả thuận")
- `location` — Hà Nội / HCM / Remote / ...
- `level` — Intern / Fresher / Junior / Mid / Senior
- `skills` — danh sách tag
- `posted_at` — ngày đăng
- `url` — dùng làm khoá tự nhiên (hash)

## Edge case phát hiện

- (ghi trong Ngày 2)
