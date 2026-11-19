"""Daily Airflow DAG: hh.ru + NBK rates -> raw -> validated core (SCD2) -> marts."""

from __future__ import annotations

from datetime import datetime, timedelta

from airflow.decorators import dag, task
from airflow.utils.trigger_rule import TriggerRule

from kzjobs import pipeline
from kzjobs.config import Settings

DEFAULT_ARGS = {
    "owner": "data-eng",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "retry_exponential_backoff": True,
}


@dag(
    dag_id="kz_jobs_daily",
    description="Daily load of the IT job market in Kazakhstan",
    schedule="0 3 * * *",
    start_date=datetime(2026, 11, 1),
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["etl", "hh", "kazakhstan"],
)
def kz_jobs_daily():
    # 'run_id' would be treated by Airflow as a context key, hence pipeline_run_id
    @task
    def start_run() -> int:
        return pipeline.start_run(Settings.from_env())

    @task
    def extract_fx(pipeline_run_id: int) -> dict:
        return pipeline.extract_fx(Settings.from_env(), pipeline_run_id)

    @task
    def extract_hh(pipeline_run_id: int) -> dict:
        return pipeline.extract_hh(Settings.from_env(), pipeline_run_id)

    @task
    def transform_load(pipeline_run_id: int, _upstream: list) -> dict:
        report = pipeline.transform_load(Settings.from_env(), pipeline_run_id)
        return {k: report[k] for k in ("valid", "rejected", "rejected_pct", "versions")}

    @task
    def refresh_marts(_loaded: dict) -> None:
        pipeline.refresh_marts(Settings.from_env())

    @task(trigger_rule=TriggerRule.ALL_DONE)
    def finalize(pipeline_run_id: int) -> str:
        return pipeline.finish_run(Settings.from_env(), pipeline_run_id)

    run = start_run()
    fx = extract_fx(run)
    hh = extract_hh(run)
    loaded = transform_load(run, [fx, hh])
    marts = refresh_marts(loaded)
    marts >> finalize(run)


kz_jobs_daily()
