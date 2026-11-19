-- Reference data: official National Bank of Kazakhstan rates (KZT per 1 unit).
CREATE TABLE core.currency_rate (
    rate_date    DATE          NOT NULL,
    currency     TEXT          NOT NULL,
    rate_kzt     NUMERIC(18,6) NOT NULL CHECK (rate_kzt > 0),
    run_id       BIGINT        REFERENCES ops.pipeline_run (run_id),
    PRIMARY KEY (rate_date, currency)
);

CREATE TABLE core.employer (
    employer_id  BIGINT PRIMARY KEY,
    name         TEXT        NOT NULL,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Canonical skills come from data/reference/skills.csv.
CREATE TABLE core.skill (
    skill_id     SERIAL PRIMARY KEY,
    name         TEXT NOT NULL UNIQUE,
    category     TEXT NOT NULL
);
