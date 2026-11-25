import dataclasses

import httpx

from kzjobs.config import Settings
from kzjobs.extract.hh import HHClient, load_roles

SETTINGS = Settings(
    hh_queries=("data engineer",), hh_request_delay=0, hh_user_agent="tests/1.0 (t@example.com)"
)


def make_transport(calls: list[httpx.Request], throttle_first: bool = False):
    state = {"throttled": False}

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if throttle_first and not state["throttled"]:
            state["throttled"] = True
            return httpx.Response(429)
        if request.url.path == "/vacancies":
            page = int(request.url.params["page"])
            items = [{"id": "1"}, {"id": "2"}] if page == 0 else [{"id": "3"}, {"id": "2"}]
            return httpx.Response(200, json={"items": items, "pages": 2, "page": page})
        vid = request.url.path.rsplit("/", 1)[1]
        return httpx.Response(200, json={"id": vid, "name": f"detail {vid}"})

    return httpx.MockTransport(handler)


def test_pagination_dedupe_and_details_only_for_unknown_ids():
    calls: list[httpx.Request] = []
    client = HHClient(SETTINGS, transport=make_transport(calls), sleep=lambda _s: None)
    payloads = {p["id"]: p for p in client.fetch(known_ids={2})}

    assert set(payloads) == {"1", "2", "3"}
    assert payloads["1"]["_source"] == "detail" and payloads["3"]["_source"] == "detail"
    assert payloads["2"]["_source"] == "search"
    detail_calls = [c for c in calls if c.url.path != "/vacancies"]
    assert sorted(c.url.path for c in detail_calls) == ["/vacancies/1", "/vacancies/3"]


def test_user_agent_and_area_are_sent():
    calls: list[httpx.Request] = []
    client = HHClient(SETTINGS, transport=make_transport(calls), sleep=lambda _s: None)
    client.fetch()
    assert calls[0].headers["User-Agent"] == "tests/1.0 (t@example.com)"
    assert calls[0].url.params["area"] == "40"


def test_retries_on_throttling_with_backoff():
    calls: list[httpx.Request] = []
    sleeps: list[float] = []
    client = HHClient(
        SETTINGS, transport=make_transport(calls, throttle_first=True), sleep=sleeps.append
    )
    assert client.fetch()
    assert 2 in sleeps


def test_search_by_title_and_non_it_roles_are_dropped():
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path == "/vacancies":
            items = [
                {"id": "1", "professional_roles": [{"name": "Дата-инженер"}]},
                {"id": "2", "professional_roles": [{"name": "Учитель, преподаватель, педагог"}]},
                {"id": "3"},
            ]
            return httpx.Response(200, json={"items": items, "pages": 1, "page": 0})
        vid = request.url.path.rsplit("/", 1)[1]
        return httpx.Response(200, json={"id": vid})

    settings = dataclasses.replace(SETTINGS, hh_search_field="name")
    client = HHClient(settings, transport=httpx.MockTransport(handler), sleep=lambda _s: None)
    assert {p["id"] for p in client.fetch()} == {"1", "3"}
    assert calls[0].url.params["search_field"] == "name"


def test_roles_file_keeps_names_with_commas():
    roles = load_roles(Settings().roles_csv)
    assert "программист, разработчик" in roles
    assert "bi-аналитик, аналитик данных" in roles
