"""Turn a raw hh vacancy payload into a flat, typed row ready for validation and loading."""

from __future__ import annotations

import hashlib
import html
import json
import re
from datetime import datetime
from decimal import Decimal
from typing import Any

from kzjobs.transform.skills import SkillMatcher

# FX-derived values are not tracked: they change daily and would version every vacancy.
TRACKED_FIELDS = (
    "title",
    "employer_id",
    "area_name",
    "role_name",
    "experience",
    "employment",
    "schedule",
    "salary_from",
    "salary_to",
    "salary_currency",
    "salary_gross",
    "archived",
)

CURRENCY_ALIASES = {"RUR": "RUB", "BYR": "BYN"}

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def strip_html(value: str | None) -> str:
    if not value:
        return ""
    text = html.unescape(_TAG_RE.sub(" ", value))
    return _WS_RE.sub(" ", text).strip()


def parse_datetime(value: str | None) -> datetime | None:
    """hh returns e.g. 2026-11-18T10:15:00+0500."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _name(obj: dict | None) -> str | None:
    return (obj or {}).get("name")


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except Exception:  # noqa: BLE001 - bad numeric input becomes "no value", validator decides
        return None


def to_kzt(
    amount: Decimal | None, currency: str | None, rates: dict[str, Decimal]
) -> Decimal | None:
    if amount is None or not currency:
        return None
    rate = rates.get(currency)
    if rate is None:
        return None
    return (amount * rate).quantize(Decimal("0.01"))


def compute_hash(row: dict[str, Any]) -> str:
    """Stable fingerprint of the tracked attributes (used to detect a change)."""
    material = {k: (str(row[k]) if row.get(k) is not None else None) for k in TRACKED_FIELDS}
    return hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()


def normalize_vacancy(
    payload: dict, matcher: SkillMatcher, rates: dict[str, Decimal]
) -> dict[str, Any]:
    """Flatten one payload. Never raises on missing data: the validator decides what is fatal."""
    salary = payload.get("salary") or {}
    currency = salary.get("currency")
    currency = CURRENCY_ALIASES.get(currency, currency) if currency else None
    sal_from, sal_to = _decimal(salary.get("from")), _decimal(salary.get("to"))

    employer = payload.get("employer") or {}
    roles = payload.get("professional_roles") or []
    snippet = payload.get("snippet") or {}
    key_skills = [ks.get("name", "") for ks in (payload.get("key_skills") or [])]

    text = " ".join(
        [
            payload.get("name") or "",
            strip_html(payload.get("description")),
            strip_html(snippet.get("requirement")),
            strip_html(snippet.get("responsibility")),
        ]
    )

    raw_id = payload.get("id")
    try:
        vacancy_id = int(raw_id) if raw_id is not None else None
    except (TypeError, ValueError):
        vacancy_id = None

    employer_id = employer.get("id")
    row: dict[str, Any] = {
        "vacancy_id": vacancy_id,
        "title": (payload.get("name") or "").strip(),
        "employer_id": int(employer_id) if employer_id not in (None, "") else None,
        "employer_name": employer.get("name"),
        "area_name": _name(payload.get("area")),
        "role_name": _name(roles[0]) if roles else None,
        "experience": _name(payload.get("experience")),
        "employment": _name(payload.get("employment")),
        "schedule": _name(payload.get("schedule")),
        "salary_from": sal_from,
        "salary_to": sal_to,
        "salary_currency": currency,
        "salary_gross": salary.get("gross"),
        "salary_from_kzt": to_kzt(sal_from, currency, rates),
        "salary_to_kzt": to_kzt(sal_to, currency, rates),
        "salary_flag": None,
        "published_at": parse_datetime(payload.get("published_at")),
        "archived": bool(payload.get("archived", False)),
        "url": payload.get("alternate_url"),
        "skills": matcher.find(text, key_skills),
        "has_details": payload.get("_source") == "detail",
    }
    row["row_hash"] = compute_hash(row)
    return row
