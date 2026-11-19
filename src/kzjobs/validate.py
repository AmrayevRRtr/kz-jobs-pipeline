"""Data quality rules."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

# plausible monthly salary range in KZT
SALARY_MIN_KZT = Decimal("50000")
SALARY_MAX_KZT = Decimal("15000000")


@dataclass
class ValidationResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def validate(row: dict[str, Any], now: datetime) -> ValidationResult:
    """Validate (and, for warnings, sanitise in place) one normalised row."""
    result = ValidationResult()

    if row["vacancy_id"] is None:
        result.errors.append("missing_id")
    if not row["title"]:
        result.errors.append("missing_title")

    published = row["published_at"]
    if published is None:
        result.errors.append("missing_published_at")
    elif published > now + timedelta(days=1):
        result.errors.append("published_in_future")

    s_from, s_to = row["salary_from"], row["salary_to"]
    if s_from is not None and s_to is not None and s_from > s_to:
        result.errors.append("salary_range_inverted")

    has_salary = s_from is not None or s_to is not None
    if has_salary and not result.errors:
        _check_salary(row, result)
    return result


def _check_salary(row: dict[str, Any], result: ValidationResult) -> None:
    values = [v for v in (row["salary_from"], row["salary_to"]) if v is not None]
    if any(v <= 0 for v in values):
        flag = "non_positive"
    elif row["salary_from_kzt"] is None and row["salary_to_kzt"] is None:
        flag = "unsupported_currency"
    else:
        kzt = [v for v in (row["salary_from_kzt"], row["salary_to_kzt"]) if v is not None]
        flag = "outlier" if any(v < SALARY_MIN_KZT or v > SALARY_MAX_KZT for v in kzt) else None

    if flag:
        result.warnings.append(f"salary_{flag}")
        row["salary_flag"] = flag
        row["salary_from_kzt"] = None
        row["salary_to_kzt"] = None
