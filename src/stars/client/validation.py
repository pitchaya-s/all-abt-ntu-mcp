from __future__ import annotations

import re

def validate_course_code(course_code: str) -> str:
    code = course_code.strip().upper()
    if len(code) > 10 or not re.fullmatch(r"(?=.*[A-Z])(?=.*\d)[A-Z0-9]+", code):
        raise ValueError("Course code must contain only letters and digits, including at least one of each.")
    return code

def _academic_term(academic_year: int, semester: int | str) -> tuple[int, str, str]:
    if isinstance(academic_year, bool) or not isinstance(academic_year, int) or not 2000 <= academic_year <= 2100:
        raise ValueError("Academic year must be a four-digit NTU year, such as 2026 (AY2026/27).")
    semester_text = str(semester).upper()
    if semester_text not in {"1", "2", "S"}:
        raise ValueError("Semester must be 1, 2, or 'S' for Special Term.")
    return academic_year, semester_text, f"{academic_year};{semester_text}"
