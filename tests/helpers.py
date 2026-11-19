"""Builders for hh-shaped payloads used across tests."""

from __future__ import annotations

from decimal import Decimal

RATES = {"KZT": Decimal(1), "USD": Decimal(500), "RUB": Decimal("5.5")}


def make_payload(
    vid: int = 1,
    name: str = "Data Engineer",
    salary: dict | None = None,
    published: str = "2026-11-16T10:00:00+0500",
    skills: tuple[str, ...] = ("Python", "SQL"),
    archived: bool = False,
    source: str = "detail",
    employer: tuple[int, str] = (100, "Test Employer"),
) -> dict:
    payload = {
        "id": str(vid),
        "name": name,
        "area": {"id": "160", "name": "Алматы"},
        "employer": {"id": str(employer[0]), "name": employer[1]},
        "published_at": published,
        "archived": archived,
        "alternate_url": f"https://hh.kz/vacancy/{vid}",
        "professional_roles": [{"id": "1", "name": "Дата-инженер"}],
        "experience": {"name": "От 1 года до 3 лет"},
        "employment": {"name": "Полная занятость"},
        "schedule": {"name": "Полный день"},
        "salary": salary,
        "_source": source,
    }
    if source == "detail":
        payload["key_skills"] = [{"name": s} for s in skills]
        payload["description"] = "<p>We build <b>pipelines</b>.</p>"
    return payload
