"""Generate SYNTHETIC sample data for the offline demo (no real vacancies, no real employers)."""

from __future__ import annotations

import copy
import json
import random
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "data" / "sample"
rng = random.Random(42)

EMPLOYERS = [
    (9001, "Steppe Analytics"), (9002, "Altyn Data Labs"), (9003, "Tengri Soft"),
    (9004, "Caspian Systems"), (9005, "Nomad Cloud"), (9006, "Silk Road Tech"),
    (9007, "Baiterek Digital"), (9008, "Alatau Software"), (9009, "Kokzhiek Retail"),
    (9010, "Zhetysu Fintech"), (9011, "Irtysh Logistics"), (9012, "Ulytau Mobile"),
]  # fmt: skip
AREAS = ["Алматы", "Астана", "Шымкент", "Караганда"]
EXPERIENCE = ["Нет опыта", "От 1 года до 3 лет", "От 3 до 6 лет"]

ROLES = {
    "Дата-инженер": (
        ["Data Engineer", "Junior Data Engineer", "Senior Data Engineer"],
        [
            "Python",
            "SQL",
            "Airflow",
            "Spark",
            "Kafka",
            "PostgreSQL",
            "ClickHouse",
            "dbt",
            "Docker",
            "ETL",
            "Linux",
            "Git",
        ],
        (450_000, 1_400_000),
    ),
    "Аналитик данных": (
        ["Data Scientist", "ML Engineer", "Data Analyst"],
        [
            "Python",
            "SQL",
            "Pandas",
            "Machine Learning",
            "PyTorch",
            "scikit-learn",
            "Tableau",
            "Power BI",
            "Git",
        ],
        (400_000, 1_300_000),
    ),
    "Backend-разработчик": (
        ["Java Developer", "Python Developer", "Backend Developer (Java)"],
        [
            "Java",
            "Spring",
            "Python",
            "FastAPI",
            "PostgreSQL",
            "Docker",
            "Kafka",
            "REST API",
            "Microservices",
            "Git",
            "Redis",
        ],
        (500_000, 1_600_000),
    ),
    "DevOps-инженер": (
        ["DevOps Engineer", "SRE", "Cloud Engineer"],
        [
            "Docker",
            "Kubernetes",
            "Terraform",
            "Ansible",
            "Linux",
            "AWS",
            "Prometheus",
            "Grafana",
            "CI/CD",
            "Git",
        ],
        (600_000, 1_700_000),
    ),
}


def make_vacancy(vid: int, published: str) -> dict:
    role, (titles, pool, (lo, hi)) = rng.choice(list(ROLES.items()))
    skills = rng.sample(pool, k=rng.randint(4, 7))
    emp_id, emp_name = rng.choice(EMPLOYERS)
    payload = {
        "id": str(vid),
        "name": rng.choice(titles),
        "area": {"id": "160", "name": rng.choice(AREAS)},
        "employer": {"id": str(emp_id), "name": emp_name},
        "published_at": published,
        "archived": False,
        "alternate_url": f"https://hh.kz/vacancy/{vid}",
        "professional_roles": [{"id": "0", "name": role}],
        "experience": {"id": "x", "name": rng.choice(EXPERIENCE)},
        "employment": {"id": "full", "name": "Полная занятость"},
        "schedule": {"id": "fullDay", "name": rng.choice(["Полный день", "Удалённая работа"])},
        "key_skills": [{"name": s} for s in skills],
        "description": f"<p>Ищем специалиста. Стек: {', '.join(skills)}.</p><ul><li>Командная работа</li></ul>",
        "_source": "detail",
    }
    if rng.random() < 0.7:
        currency = rng.choices(["KZT", "USD", "RUR"], weights=[85, 12, 3])[0]
        base = rng.randint(lo, hi)
        scale = {"KZT": 1, "USD": 1 / 500, "RUR": 1 / 5.5}[currency]
        sal_from = round(base * scale, -2 if currency == "KZT" else 0)
        has_to = rng.random() < 0.7
        payload["salary"] = {
            "from": int(sal_from),
            "to": int(sal_from * 1.3) if has_to else None,
            "currency": currency,
            "gross": rng.choice([True, False]),
        }
    else:
        payload["salary"] = None
    return payload


def main() -> None:
    day1 = [
        make_vacancy(
            5_000_000 + i, f"2026-11-{rng.randint(9, 16):02d}T{rng.randint(8, 18):02d}:00:00+0500"
        )
        for i in range(60)
    ]

    bad_title = copy.deepcopy(day1[3])
    bad_title["id"] = "5009001"
    bad_title["name"] = ""
    inverted = copy.deepcopy(day1[5])
    inverted["id"] = "5009002"
    inverted["salary"] = {"from": 900_000, "to": 400_000, "currency": "KZT", "gross": False}
    future = copy.deepcopy(day1[7])
    future["id"] = "5009003"
    future["published_at"] = "2027-03-01T10:00:00+0500"
    typo = copy.deepcopy(day1[9])
    typo["id"] = "5009004"
    typo["salary"] = {"from": 800, "to": None, "currency": "KZT", "gross": False}
    odd_ccy = copy.deepcopy(day1[11])
    odd_ccy["id"] = "5009005"
    odd_ccy["salary"] = {"from": 3000, "to": None, "currency": "XYZ", "gross": False}
    duplicate = copy.deepcopy(day1[13])
    day1 += [bad_title, inverted, future, typo, odd_ccy, duplicate]

    day2 = copy.deepcopy(day1[:60])
    for idx in (0, 1, 2, 4, 6, 8):
        v = day2[idx]
        if v["salary"] and v["salary"]["currency"] == "KZT":
            v["salary"]["from"] = int(v["salary"]["from"] * 1.15)
            if v["salary"]["to"]:
                v["salary"]["to"] = int(v["salary"]["to"] * 1.15)
    for idx in (10, 12, 14):
        day2[idx]["archived"] = True
    day2[16]["name"] = day2[16]["name"] + " (remote)"
    day2 += [
        make_vacancy(
            5_000_100 + i, f"2026-11-{rng.randint(16, 17):02d}T{rng.randint(8, 18):02d}:00:00+0500"
        )
        for i in range(8)
    ]
    broken = copy.deepcopy(day2[20])
    broken["id"] = "5009101"
    broken["name"] = "  "
    day2.append(broken)

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "hh_day1.json").write_text(
        json.dumps(day1, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    (OUT / "hh_day2.json").write_text(
        json.dumps(day2, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    rates = [
        ("USD", "ДОЛЛАР США", 500.00, 1),
        ("EUR", "ЕВРО", 580.00, 1),
        ("RUB", "РОССИЙСКИЙ РУБЛЬ", 5.50, 1),
        ("CNY", "КИТАЙСКИЙ ЮАНЬ", 70.00, 1),
        ("JPY", "ЯПОНСКАЯ ИЕНА", 330.00, 100),
    ]
    items = "\n".join(
        f"<item><fullname>{full}</fullname><title>{code}</title><description>{price}</description>"
        f"<quant>{quant}</quant><index>UP</index><change>0.10</change></item>"
        for code, full, price, quant in rates
    )
    xml = (
        '<?xml version="1.0" encoding="utf-8"?>\n<rates><generator>sample</generator>'
        "<title>Sample rates (synthetic)</title><date>17.11.2026</date>\n" + items + "\n</rates>\n"
    )
    (OUT / "nbk_rates.xml").write_text(xml, encoding="utf-8")
    print(f"day1={len(day1)} records, day2={len(day2)} records")


if __name__ == "__main__":
    main()
