"""REST API that serves the warehouse to other systems (OpenAPI docs at /docs)."""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from typing import Annotated, Any

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Query

from kzjobs.config import Settings
from kzjobs.db import connect

app = FastAPI(
    title="KZ IT Jobs API",
    version="0.1.0",
    description="Structured access to the IT job market warehouse: current vacancies, "
    "version history, skill trends, salary statistics and pipeline quality reports.",
)

HISTORY_FIELDS = (
    "title", "role_name", "area_name", "experience", "employment", "schedule",
    "salary_from", "salary_to", "salary_currency", "salary_gross", "archived",
)  # fmt: skip


def plain(obj: Any) -> Any:
    """Make query results JSON friendly: NUMERIC columns become numbers, not strings."""
    if isinstance(obj, Decimal):
        return int(obj) if obj == obj.to_integral_value() else float(obj)
    if isinstance(obj, dict):
        return {k: plain(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [plain(v) for v in obj]
    return obj


def get_settings() -> Settings:
    return Settings.from_env()


def get_conn(settings: Annotated[Settings, Depends(get_settings)]) -> Iterator[psycopg.Connection]:
    with connect(settings.database_url) as conn:
        yield conn


Conn = Annotated[psycopg.Connection, Depends(get_conn)]


@app.get("/health", tags=["system"])
def health(conn: Conn) -> dict[str, str]:
    conn.execute("SELECT 1")
    return {"status": "ok"}


@app.get("/vacancies", tags=["vacancies"])
def list_vacancies(
    conn: Conn,
    skill: Annotated[str | None, Query(description="Canonical skill name, e.g. Airflow")] = None,
    role: Annotated[str | None, Query(description="Professional role name")] = None,
    area: Annotated[str | None, Query(description="City / area name")] = None,
    min_salary_kzt: Annotated[float | None, Query(ge=0)] = None,
    include_archived: bool = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    """Current version of each vacancy, with optional filters."""
    where, params = ["TRUE"], {"limit": limit, "offset": offset}
    if skill:
        where.append("%(skill)s = ANY(skills)")
        params["skill"] = skill
    if role:
        where.append("role_name = %(role)s")
        params["role"] = role
    if area:
        where.append("area_name = %(area)s")
        params["area"] = area
    if min_salary_kzt is not None:
        where.append("salary_mid_kzt >= %(min_salary)s")
        params["min_salary"] = min_salary_kzt
    if not include_archived:
        where.append("NOT archived")

    clause = " AND ".join(where)
    total = conn.execute(
        f"SELECT count(*) AS n FROM mart.vacancy_current WHERE {clause}", params
    ).fetchone()["n"]
    items = conn.execute(
        f"""SELECT * FROM mart.vacancy_current WHERE {clause}
            ORDER BY published_at DESC, vacancy_id LIMIT %(limit)s OFFSET %(offset)s""",
        params,
    ).fetchall()
    return plain({"total": total, "limit": limit, "offset": offset, "items": items})


@app.get("/vacancies/{vacancy_id}", tags=["vacancies"])
def get_vacancy(vacancy_id: int, conn: Conn) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM mart.vacancy_current WHERE vacancy_id = %s", (vacancy_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="vacancy not found")
    return plain(row)


@app.get("/vacancies/{vacancy_id}/history", tags=["vacancies"])
def vacancy_history(vacancy_id: int, conn: Conn) -> dict[str, Any]:
    """All stored versions of a vacancy plus a field-level change log between versions."""
    versions = conn.execute(
        """SELECT version_id, valid_from, valid_to, is_current, run_id, row_hash, salary_mid_kzt,
                  title, role_name, area_name, experience, employment, schedule,
                  salary_from, salary_to, salary_currency, salary_gross, archived
           FROM core.vacancy_version WHERE vacancy_id = %s ORDER BY valid_from, version_id""",
        (vacancy_id,),
    ).fetchall()
    if not versions:
        raise HTTPException(status_code=404, detail="vacancy not found")

    changes = []
    for prev, cur in zip(versions, versions[1:], strict=False):
        diff = {f: {"from": prev[f], "to": cur[f]} for f in HISTORY_FIELDS if prev[f] != cur[f]}
        changes.append({"at": cur["valid_from"], "run_id": cur["run_id"], "changed_fields": diff})
    return plain({"vacancy_id": vacancy_id, "versions": versions, "changes": changes})


@app.get("/skills/trends", tags=["analytics"])
def skill_trends(
    conn: Conn,
    weeks: Annotated[int, Query(ge=1, le=52)] = 8,
    top: Annotated[int, Query(ge=1, le=50)] = 10,
    category: str | None = None,
) -> dict[str, Any]:
    """Weekly share of vacancies mentioning each of the top skills (window ends at the latest week)."""
    rows = conn.execute(
        """WITH win AS (
               SELECT * FROM mart.skill_demand_weekly
               WHERE week > (SELECT max(week) FROM mart.skill_demand_weekly) - (%(weeks)s * 7)
                 AND (%(category)s::text IS NULL OR category = %(category)s)
           ),
           best AS (
               SELECT skill FROM win GROUP BY skill ORDER BY sum(vacancies) DESC, skill LIMIT %(top)s
           )
           SELECT w.week, w.skill, w.vacancies, w.share_pct
           FROM win w JOIN best b USING (skill) ORDER BY w.skill, w.week""",
        {"weeks": weeks, "top": top, "category": category},
    ).fetchall()
    series: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        series.setdefault(r["skill"], []).append(
            {"week": r["week"], "vacancies": r["vacancies"], "share_pct": r["share_pct"]}
        )
    return plain({"weeks": weeks, "series": series})


@app.get("/salaries/summary", tags=["analytics"])
def salary_summary(
    conn: Conn, min_vacancies: Annotated[int, Query(ge=1)] = 5
) -> list[dict[str, Any]]:
    """Salary quartiles (KZT, monthly midpoint) per role; roles with too few salaries are hidden."""
    return plain(
        conn.execute(
            """SELECT * FROM mart.salary_by_role
               WHERE vacancies_with_salary >= %s ORDER BY median_kzt DESC""",
            (min_vacancies,),
        ).fetchall()
    )


@app.get("/quality/runs", tags=["system"])
def quality_runs(
    conn: Conn, limit: Annotated[int, Query(ge=1, le=100)] = 10
) -> list[dict[str, Any]]:
    """Latest pipeline runs with their data quality report (rejects, warnings, coverage)."""
    return conn.execute(
        """SELECT run_id, source, status, started_at, finished_at, error, stats
           FROM ops.pipeline_run ORDER BY run_id DESC LIMIT %s""",
        (limit,),
    ).fetchall()
