"""Decide whether a posting is an IT job.

Why not use the ``industry`` field? It is self-declared by employers and we
measured it to be wrong (bank telesales postings are tagged "Information
Technology"). Title + skills are the signal that actually correlates with the
role.

Rules, in order:
1. Negative keywords in the title -> reject (sales, accounting, manufacturing
   quality control...).
2. Positive keywords in title or skills -> accept, with the matched keyword
   recorded as the reason.
3. Otherwise -> reject.

Vietnamese is normalized to ASCII (diacritics stripped, đ -> d) so one keyword
list covers both "Lập trình viên" and "Lap trinh vien".

v2 (Day 3, after measuring precision on 21 real postings): dropped the bare
``qa``/``qc``/``analyst``/``du lieu`` keywords. They matched factory quality
control ("Kỹ Sư Chất Lượng", "QC Gia Công") and warehouse data entry, which
halved precision. Specific phrases ("qa engineer", "data analyst") replaced
them.
"""

from __future__ import annotations

import re
import unicodedata

# Non-IT roles. Checked against the title only, because these words can
# legitimately appear in an IT job description.
NON_IT_KEYWORDS: tuple[str, ...] = (
    "telesales",
    "kinh doanh",
    "sales",
    "tuyen sinh",
    "tu van",
    "ban hang",
    "cham soc khach hang",
    "bao hiem",
    "marketing",
    "data entry",
    "nhap lieu",
    "ke toan",
    "tai chinh",
    "financial",
    "finance",
    "hanh chinh",
    "le tan",
    # manufacturing / hardware quality roles that look like "QA/QC"
    "chat luong san pham",
    "gia cong",
    "san xuat",
    "nha may",
    "sua chua",
    "hvac",
    "co khi",
    "xay dung",
)

# Engineering signal. Matched against title AND skills.
IT_KEYWORDS: tuple[str, ...] = (
    # roles
    "developer",
    "engineer",
    "devops",
    "backend",
    "frontend",
    "fullstack",
    "full-stack",
    "mobile",
    "android",
    "ios",
    "tester",
    "testing",
    "automation test",
    "qa engineer",
    "qc engineer",
    "cloud",
    "security",
    "sysadmin",
    "dba",
    "it support",
    "helpdesk",
    "business analyst",
    "phan tich nghiep vu",
    "erp",
    "sap",
    # data
    "data engineer",
    "data analyst",
    "data scientist",
    "big data",
    "kho du lieu",
    # languages / stacks
    "java",
    "python",
    "react",
    "node",
    "php",
    "golang",
    "c++",
    "c#",
    ".net",
    "sql",
    "kotlin",
    "swift",
    "rust",
    # microsoft / low-code
    "sharepoint",
    "microsoft 365",
    "office 365",
    "power bi",
    "power platform",
    "copilot",
    # Vietnamese (already accent-stripped)
    "lap trinh",
    "phan mem",
    "kiem thu",
    "quan tri mang",
    "an toan thong tin",
    "tri tue nhan tao",
    "cong nghe thong tin",
    "cntt",
)

_WHITESPACE_RE = re.compile(r"\s+")


def normalize(text: str | None) -> str:
    """Lowercase, strip Vietnamese diacritics and collapse punctuation."""
    if not text:
        return ""
    lowered = text.lower().replace("đ", "d")
    decomposed = unicodedata.normalize("NFD", lowered)
    without_marks = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    cleaned = re.sub(r"[^a-z0-9+#.]+", " ", without_marks)
    return _WHITESPACE_RE.sub(" ", cleaned).strip()


def _contains(haystack: str, needle: str) -> bool:
    return f" {needle} " in f" {haystack} "


def classify(title: str | None, skills: list[str] | None = None) -> tuple[bool, str]:
    """Return ``(is_it_job, reason)``.

    ``reason`` is one of ``non_it:<keyword>``, ``match:<keyword>`` or
    ``no_it_keyword`` — it is stored with every row so we can audit and tune
    the rules later instead of guessing.
    """
    title_norm = normalize(title)
    skills_norm = normalize(" , ".join(skills or []))

    for keyword in NON_IT_KEYWORDS:
        if _contains(title_norm, keyword):
            return False, f"non_it:{keyword}"

    haystack = f"{title_norm} {skills_norm}"
    for keyword in IT_KEYWORDS:
        if _contains(haystack, keyword):
            return True, f"match:{keyword}"

    return False, "no_it_keyword"
