"""Extractor for the public hh.ru vacancies API (JSON)."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterator

import httpx

from kzjobs.config import Settings

log = logging.getLogger(__name__)

RETRY_STATUSES = {429, 500, 502, 503, 504}


class HHError(RuntimeError):
    pass


class HHClient:
    def __init__(
        self,
        settings: Settings,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        headers = {"User-Agent": settings.hh_user_agent, "HH-User-Agent": settings.hh_user_agent}
        if settings.hh_app_token:
            headers["Authorization"] = f"Bearer {settings.hh_app_token}"
        self._settings = settings
        self._sleep = sleep
        self._client = httpx.Client(
            base_url=settings.hh_base_url, headers=headers, timeout=30.0, transport=transport
        )

    def close(self) -> None:
        self._client.close()

    def _get(self, path: str, params: dict | None = None, attempts: int = 4) -> dict:
        """GET with exponential backoff on throttling and transient server errors."""
        for attempt in range(1, attempts + 1):
            try:
                resp = self._client.get(path, params=params)
            except httpx.TransportError as exc:
                if attempt == attempts:
                    raise HHError(f"network error for {path}: {exc}") from exc
                self._sleep(2**attempt)
                continue
            if resp.status_code in RETRY_STATUSES and attempt < attempts:
                log.warning("hh %s -> %s, retry %s/%s", path, resp.status_code, attempt, attempts)
                self._sleep(2**attempt)
                continue
            if resp.status_code != 200:
                raise HHError(f"hh {path} returned {resp.status_code}: {resp.text[:200]}")
            return resp.json()
        raise HHError(f"unreachable retry loop for {path}")

    def search(self, text: str) -> Iterator[dict]:
        """Yield vacancy summaries for one search query, page by page."""
        s = self._settings
        page = 0
        while page < s.hh_max_pages:
            data = self._get(
                "/vacancies",
                {
                    "text": text,
                    "area": s.hh_area,
                    "period": s.hh_period_days,
                    "per_page": 100,
                    "page": page,
                    "order_by": "publication_time",
                },
            )
            yield from data.get("items", [])
            page += 1
            if page >= data.get("pages", 0):
                break
            self._sleep(s.hh_request_delay)

    def detail(self, vacancy_id: int | str) -> dict:
        return self._get(f"/vacancies/{vacancy_id}")

    def fetch(self, known_ids: set[int] | None = None) -> list[dict]:
        """Run all configured queries; fetch full details only for vacancies we have not seen."""
        known_ids = known_ids or set()
        found: dict[int, dict] = {}
        for query in self._settings.hh_queries:
            for item in self.search(query):
                found.setdefault(int(item["id"]), item)
            self._sleep(self._settings.hh_request_delay)

        payloads: list[dict] = []
        for vacancy_id, item in found.items():
            if self._settings.hh_fetch_details and vacancy_id not in known_ids:
                try:
                    payloads.append({**self.detail(vacancy_id), "_source": "detail"})
                    self._sleep(self._settings.hh_request_delay)
                    continue
                except HHError as exc:
                    log.warning(
                        "detail %s failed, falling back to search item: %s", vacancy_id, exc
                    )
            payloads.append({**item, "_source": "search"})
        log.info(
            "hh: %s unique vacancies from %s queries", len(payloads), len(self._settings.hh_queries)
        )
        return payloads
