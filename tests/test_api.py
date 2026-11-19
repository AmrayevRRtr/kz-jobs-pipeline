from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from kzjobs.api.main import app, get_settings
from kzjobs.pipeline import run_all
from tests.helpers import make_payload

T1 = datetime(2026, 11, 17, 6, 0, tzinfo=UTC)


@pytest.fixture
def client(settings, fx_xml):
    run_all(
        settings,
        [
            make_payload(
                1,
                skills=("Python", "Airflow"),
                salary={"from": 700000, "to": None, "currency": "KZT", "gross": False},
            ),
            make_payload(2, skills=("Java", "Spring")),
            make_payload(3, name="Old role", archived=True),
        ],
        fx_xml,
        T1,
    )
    run_all(
        settings,
        [
            make_payload(
                1,
                skills=("Python", "Airflow"),
                salary={"from": 800000, "to": None, "currency": "KZT", "gross": False},
            )
        ],
        fx_xml,
        T1 + timedelta(days=1),
    )
    app.dependency_overrides[get_settings] = lambda: settings
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_vacancies_hide_archived_and_filter_by_skill(client):
    ids = {v["vacancy_id"] for v in client.get("/vacancies").json()["items"]}
    assert ids == {1, 2}
    by_skill = client.get("/vacancies", params={"skill": "Airflow"}).json()
    assert by_skill["total"] == 1 and by_skill["items"][0]["vacancy_id"] == 1
    assert client.get("/vacancies", params={"include_archived": True}).json()["total"] == 3


def test_salary_filter(client):
    res = client.get("/vacancies", params={"min_salary_kzt": 750000}).json()
    assert [v["vacancy_id"] for v in res["items"]] == [1]


def test_history_shows_field_level_changes(client):
    body = client.get("/vacancies/1/history").json()
    assert len(body["versions"]) == 2
    change = body["changes"][0]["changed_fields"]
    assert float(change["salary_from"]["from"]) == 700000
    assert float(change["salary_from"]["to"]) == 800000


def test_unknown_vacancy_is_404(client):
    assert client.get("/vacancies/999/history").status_code == 404
    assert client.get("/vacancies/999").status_code == 404


def test_limit_is_validated(client):
    assert client.get("/vacancies", params={"limit": 1000}).status_code == 422


def test_skill_trends_and_salaries(client):
    trends = client.get("/skills/trends").json()
    assert "Python" in trends["series"]
    assert client.get("/salaries/summary").json()[0]["role_name"] == "Дата-инженер"


def test_quality_runs_expose_the_report(client):
    runs = client.get("/quality/runs").json()
    assert runs[0]["status"] == "success" and "quality" in runs[0]["stats"]
