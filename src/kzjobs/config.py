"""Runtime configuration. Everything comes from environment variables (12-factor)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_QUERIES = (
    "data engineer",
    "дата инженер",
    "data scientist",
    "python developer",
    "java developer",
    "devops",
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    database_url: str = "postgresql://warehouse:warehouse@localhost:5432/warehouse"

    hh_base_url: str = "https://api.hh.ru"
    hh_user_agent: str = "kz-jobs-pipeline/0.1 (set-your-email@example.com)"
    hh_app_token: str | None = None
    hh_area: int = 40
    hh_queries: tuple[str, ...] = DEFAULT_QUERIES
    hh_period_days: int = 1
    hh_max_pages: int = 5
    hh_fetch_details: bool = True
    hh_request_delay: float = 0.3

    nbk_rates_url: str = "https://nationalbank.kz/rss/get_rates.cfm"

    skills_csv: Path = REPO_ROOT / "data" / "reference" / "skills.csv"
    reject_threshold_pct: float = 10.0

    @classmethod
    def from_env(cls) -> Settings:
        env = os.environ
        queries = env.get("HH_QUERIES")
        return cls(
            database_url=env.get("DATABASE_URL", cls.database_url),
            hh_base_url=env.get("HH_BASE_URL", cls.hh_base_url),
            hh_user_agent=env.get("HH_USER_AGENT", cls.hh_user_agent),
            hh_app_token=env.get("HH_APP_TOKEN") or None,
            hh_area=int(env.get("HH_AREA", cls.hh_area)),
            hh_queries=tuple(q.strip() for q in queries.split(";") if q.strip())
            if queries
            else DEFAULT_QUERIES,
            hh_period_days=int(env.get("HH_PERIOD_DAYS", cls.hh_period_days)),
            hh_max_pages=int(env.get("HH_MAX_PAGES", cls.hh_max_pages)),
            hh_fetch_details=_bool(env.get("HH_FETCH_DETAILS"), cls.hh_fetch_details),
            hh_request_delay=float(env.get("HH_REQUEST_DELAY", cls.hh_request_delay)),
            nbk_rates_url=env.get("NBK_RATES_URL", cls.nbk_rates_url),
            skills_csv=Path(env.get("SKILLS_CSV", str(cls.skills_csv))),
            reject_threshold_pct=float(env.get("REJECT_THRESHOLD_PCT", cls.reject_threshold_pct)),
        )
