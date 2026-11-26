"""Tests for the IT-job classifier using real titles observed on TopDev."""

from __future__ import annotations

import pytest
from ingestion.filter import classify, normalize


def test_normalize_strips_vietnamese_diacritics() -> None:
    assert normalize("Lập trình viên PHP") == "lap trinh vien php"
    assert normalize("Kỹ sư phần mềm") == "ky su phan mem"


def test_normalize_keeps_cpp_and_csharp() -> None:
    assert "c++" in normalize("Lập trình viên C++")
    assert "c#" in normalize("Developer C#")


@pytest.mark.parametrize(
    "title,skills",
    [
        ("Senior Java Developer", ["Java", "Spring"]),
        ("Lập trình viên PHP", ["PHP", "MySQL"]),
        ("Data Engineer", ["Python", "SQL", "Airflow"]),
        ("Kỹ sư phần mềm", ["C++"]),
        ("QA/Tester", ["Selenium"]),
        ("Chuyên viên Ứng dụng Microsoft 365 & Copilot", ["Sharepoint", "Microsoft 365"]),
    ],
)
def test_it_jobs_are_kept(title: str, skills: list[str]) -> None:
    is_it, reason = classify(title, skills)
    assert is_it is True, f"{title!r} should be IT, got {reason}"


@pytest.mark.parametrize(
    "title,skills",
    [
        ("Tập sự Chuyên viên Khách hàng Cá nhân - Khu vực Hải Phòng", ["Risk Management"]),
        (
            "Nhân viên tư vấn tuyển sinh telesales kinh doanh - Data có sẵn",
            ["Communication"],
        ),
        ("Nhân viên kinh doanh phần mềm", ["SQL"]),  # negative wins over "phan mem"
        ("Chuyên viên nhập liệu data entry", ["Excel"]),
        ("Kế toán tổng hợp", ["Excel", "SAP"]),  # "sap" must not save it
    ],
)
def test_non_it_jobs_are_rejected(title: str, skills: list[str]) -> None:
    is_it, reason = classify(title, skills)
    assert is_it is False, f"{title!r} should not be IT, got {reason}"
    assert reason.startswith(("non_it:", "no_it_keyword"))


def test_reason_is_explained() -> None:
    is_it, reason = classify("Senior Java Developer", ["Java"])
    assert is_it is True
    # either the generic role keyword or the specific language may match first
    matched_keyword = reason.split(":", 1)[1]
    assert matched_keyword in normalize("Senior Java Developer Java")

    is_it, reason = classify("Nhân viên kinh doanh", [])
    assert is_it is False
    assert reason == "non_it:kinh doanh"


@pytest.mark.parametrize(
    "title",
    [
        # manufacturing quality control, not software QA
        "Nhân Viên Quản Lý Chất Lượng (Qc Officer)",
        "Kỹ Sư Chất Lượng PQA/QE",
        "Kỹ Sư Phân Tích Và Sửa Chữa Sản Phẩm (FA/RE)",
        "Nhân viên QC Gia Công",
        "NHÂN VIÊN KIỂM SOÁT CHẤT LƯỢNG SẢN PHẨM (QC)",
        # warehouse data entry, not data engineering
        "Nhân viên Kiểm soát dữ liệu kho EC",
        # hardware support
        "Technical Support Engineer (HVAC/Fresh Graduate)",
        # finance
        "FINANCIAL MANAGER (CAN THO BRANCH)",
    ],
)
def test_manufacturing_and_backoffice_are_rejected(title: str) -> None:
    is_it, reason = classify(title, [])
    assert is_it is False, f"{title!r} should not be IT, got {reason}"


@pytest.mark.parametrize(
    "title,skills",
    [
        ("IT Business Analyst / QA Specialist", ["Business Analysis"]),
        ("Cobol Developer (English speaking)", ["Cobol"]),
        ("Android Developer (Kotlin / Jetpack Compose)", ["Android"]),
        ("Chuyên Gia Kiểm Thử & Đánh Giá An Ninh (Pentest)", ["Penetration Testing"]),
        ("Associate Quality Engineer (Automation)", ["Automation Testing"]),
    ],
)
def test_software_roles_are_kept(title: str, skills: list[str]) -> None:
    is_it, reason = classify(title, skills)
    assert is_it is True, f"{title!r} should be IT, got {reason}"
