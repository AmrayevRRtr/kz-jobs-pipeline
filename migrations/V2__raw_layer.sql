-- Raw layer: responses are stored exactly as received, so any downstream step
-- can be replayed without calling the external APIs again.
CREATE TABLE raw.hh_vacancy (
    id           BIGSERIAL PRIMARY KEY,
    run_id       BIGINT      NOT NULL REFERENCES ops.pipeline_run (run_id),
    vacancy_id   BIGINT,           -- NULL if the payload has no usable id (rejected later)
    payload      JSONB       NOT NULL,
    fetched_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_raw_hh_run     ON raw.hh_vacancy (run_id);
CREATE INDEX ix_raw_hh_vac     ON raw.hh_vacancy (vacancy_id);
CREATE INDEX ix_raw_hh_payload ON raw.hh_vacancy USING gin (payload jsonb_path_ops);

CREATE TABLE raw.nbk_rates_xml (
    id           BIGSERIAL PRIMARY KEY,
    run_id       BIGINT      NOT NULL REFERENCES ops.pipeline_run (run_id),
    rate_date    DATE        NOT NULL,
    xml          TEXT        NOT NULL,
    fetched_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_raw_nbk_run ON raw.nbk_rates_xml (run_id);
