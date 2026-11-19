-- Layers of the warehouse: raw -> staging -> core -> mart, plus ops for run metadata.
CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS staging;
CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS mart;
CREATE SCHEMA IF NOT EXISTS ops;

-- One row per pipeline execution. Every other table points back here (lineage).
CREATE TABLE ops.pipeline_run (
    run_id       BIGSERIAL PRIMARY KEY,
    source       TEXT        NOT NULL,
    status       TEXT        NOT NULL DEFAULT 'running'
                 CHECK (status IN ('running', 'success', 'failed')),
    started_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at  TIMESTAMPTZ,
    stats        JSONB       NOT NULL DEFAULT '{}'::jsonb,
    error        TEXT
);

-- Records that failed validation. Kept with the reason so nothing disappears silently.
CREATE TABLE ops.rejected_record (
    id           BIGSERIAL PRIMARY KEY,
    run_id       BIGINT      NOT NULL REFERENCES ops.pipeline_run (run_id),
    source       TEXT        NOT NULL,
    vacancy_id   BIGINT,
    reasons      TEXT[]      NOT NULL,
    payload      JSONB       NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ix_rejected_run ON ops.rejected_record (run_id);
