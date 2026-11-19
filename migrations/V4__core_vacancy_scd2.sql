-- Staging holds the validated batch of the current run only (truncated every run).
CREATE TABLE staging.vacancy (
    vacancy_id        BIGINT PRIMARY KEY,
    row_hash          TEXT        NOT NULL,
    title             TEXT        NOT NULL,
    employer_id       BIGINT,
    employer_name     TEXT,
    area_name         TEXT,
    role_name         TEXT,
    experience        TEXT,
    employment        TEXT,
    schedule          TEXT,
    salary_from       NUMERIC(14,2),
    salary_to         NUMERIC(14,2),
    salary_currency   TEXT,
    salary_gross      BOOLEAN,
    salary_from_kzt   NUMERIC(14,2),
    salary_to_kzt     NUMERIC(14,2),
    salary_flag       TEXT,
    published_at      TIMESTAMPTZ NOT NULL,
    archived          BOOLEAN     NOT NULL DEFAULT FALSE,
    url               TEXT,
    has_details       BOOLEAN     NOT NULL DEFAULT FALSE  -- skills come from the full vacancy page
);

CREATE TABLE staging.vacancy_skill (
    vacancy_id  BIGINT NOT NULL,
    skill_name  TEXT   NOT NULL,
    PRIMARY KEY (vacancy_id, skill_name)
);

-- SCD Type 2: every change of a tracked attribute creates a new version row.
-- valid_from / valid_to define when the version was the truth in OUR warehouse.
CREATE TABLE core.vacancy_version (
    version_id        BIGSERIAL PRIMARY KEY,
    vacancy_id        BIGINT      NOT NULL,
    row_hash          TEXT        NOT NULL,
    title             TEXT        NOT NULL,
    employer_id       BIGINT      REFERENCES core.employer (employer_id),
    area_name         TEXT,
    role_name         TEXT,
    experience        TEXT,
    employment        TEXT,
    schedule          TEXT,
    salary_from       NUMERIC(14,2),
    salary_to         NUMERIC(14,2),
    salary_currency   TEXT,
    salary_gross      BOOLEAN,
    salary_from_kzt   NUMERIC(14,2),   -- converted at the rate of the day the version was created
    salary_to_kzt     NUMERIC(14,2),
    salary_flag       TEXT,            -- NULL, unsupported_currency, outlier, non_positive
    salary_mid_kzt    NUMERIC(14,2) GENERATED ALWAYS AS (
        (COALESCE(salary_from_kzt, salary_to_kzt) + COALESCE(salary_to_kzt, salary_from_kzt)) / 2
    ) STORED,
    published_at      TIMESTAMPTZ NOT NULL,
    archived          BOOLEAN     NOT NULL DEFAULT FALSE,
    url               TEXT,
    valid_from        TIMESTAMPTZ NOT NULL,
    valid_to          TIMESTAMPTZ,
    is_current        BOOLEAN     NOT NULL DEFAULT TRUE,
    run_id            BIGINT      NOT NULL REFERENCES ops.pipeline_run (run_id),
    CHECK (valid_to IS NULL OR valid_to >= valid_from),
    CHECK (is_current = (valid_to IS NULL))
);

-- Guarantees at most one current version per vacancy, even under concurrent runs.
CREATE UNIQUE INDEX ux_vacancy_current ON core.vacancy_version (vacancy_id) WHERE is_current;
CREATE INDEX ix_vacancy_history        ON core.vacancy_version (vacancy_id, valid_from);
CREATE INDEX ix_vacancy_published      ON core.vacancy_version (published_at) WHERE is_current;

-- Skills describe the current state of a vacancy (replaced when the vacancy is re-read).
CREATE TABLE core.vacancy_skill (
    vacancy_id  BIGINT  NOT NULL,
    skill_id    INTEGER NOT NULL REFERENCES core.skill (skill_id),
    PRIMARY KEY (vacancy_id, skill_id)
);
CREATE INDEX ix_vacancy_skill_skill ON core.vacancy_skill (skill_id);
