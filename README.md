# kz-jobs-pipeline

A data engineering pipeline that tracks the **IT job market in Kazakhstan**. It collects vacancies from the hh.ru API and official exchange rates from the National Bank of Kazakhstan, validates them, stores the full change history in PostgreSQL, builds analytical marts and serves everything through a REST API.

The goal of the project is to show the whole data engineering loop in one small, runnable repository: extraction from different formats, layered modelling, data quality control, history tracking, orchestration, an API on top and tests that run against a real database.

| | |
|---|---|
| **Sources** | hh.ru API (JSON), National Bank of Kazakhstan rates (XML), skills dictionary (CSV) |
| **Storage** | PostgreSQL 16, versioned migrations with Flyway |
| **Processing** | Python 3.11+ (httpx, psycopg 3), SQL for the merge logic and marts |
| **Orchestration** | Apache Airflow (daily DAG) |
| **Serving** | FastAPI with OpenAPI docs |
| **Quality** | pytest (50 tests, integration tests on real PostgreSQL), ruff, GitHub Actions |
| **Packaging** | Docker Compose: one command starts the whole stack |

## Architecture

```mermaid
flowchart LR
    HH[hh.ru API<br/>JSON] --> EX
    NBK[NBK rates<br/>XML] --> EX
    CSV[skills.csv<br/>dictionary] --> TR

    subgraph Airflow DAG kz_jobs_daily
        EX[extract] --> RAW[(raw<br/>JSONB + XML as received)]
        RAW --> TR[normalize + validate]
        TR -->|rejected + reasons| REJ[(ops.rejected_record)]
        TR --> STG[(staging<br/>valid batch)]
        STG -->|SCD2 merge| CORE[(core<br/>vacancy_version, skills, rates)]
        CORE --> MART[(mart<br/>materialized views)]
    end

    CORE --> API[FastAPI]
    MART --> API
    OPS[(ops.pipeline_run<br/>quality report)] -.-> API
```

Layers:

| Layer | Purpose |
|---|---|
| `raw` | Every response stored exactly as received. Any later step can be replayed without calling the external APIs again. |
| `staging` | The validated batch of the current run only (truncated each run). |
| `core` | Clean model with full history: `vacancy_version` (SCD2), `employer`, `skill`, `vacancy_skill`, `currency_rate`. |
| `mart` | Analytical views: skill demand per week, salary quartiles per role, a flat "current vacancies" view. |
| `ops` | Run metadata, quality reports and rejected records. Every row in other layers carries a `run_id` for lineage. |

## Data model

```mermaid
erDiagram
    PIPELINE_RUN ||--o{ VACANCY_VERSION : "run_id"
    PIPELINE_RUN ||--o{ REJECTED_RECORD : "run_id"
    PIPELINE_RUN ||--o{ HH_VACANCY_RAW : "run_id"
    EMPLOYER ||--o{ VACANCY_VERSION : "employer_id"
    VACANCY_VERSION }o--o{ SKILL : "vacancy_skill"

    VACANCY_VERSION {
        bigint version_id PK
        bigint vacancy_id
        text row_hash
        text title
        numeric salary_from
        numeric salary_to
        text salary_currency
        numeric salary_mid_kzt "generated column"
        timestamptz valid_from
        timestamptz valid_to
        boolean is_current
    }
    EMPLOYER { bigint employer_id PK }
    SKILL { int skill_id PK }
    PIPELINE_RUN { bigint run_id PK }
```

## Design decisions

**History with SCD Type 2.** A vacancy changes over time: the salary is raised, the title is edited, the posting is archived. Instead of overwriting, every change closes the current row (`valid_to`) and inserts a new version. Changes are detected by a SHA-256 hash of the tracked business fields, so unchanged vacancies cost nothing. A partial unique index (`WHERE is_current`) lets the database itself guarantee one current version per vacancy, even if two runs overlap.

**Exchange rates are not part of the hash.** KZT values are derived from daily rates. If they were hashed, every vacancy would "change" every day. Salary in KZT is therefore frozen at the rate of the day a version was created, and the original amount and currency are always kept.

**Validation with two severities.** Errors reject a record (missing title, publication date in the future, inverted salary range). Warnings keep the record but remove the suspicious part from analytics (salary outside 50k to 15M KZT per month, unknown currency, non-positive value) and mark it in `salary_flag`. Rejected records are stored with the list of reasons, never dropped silently.

**Quality gate.** If more than `REJECT_THRESHOLD_PCT` (default 10%) of a batch is rejected, the load stops before touching `core`. The rejected records and the report are still saved as evidence, and the run is marked `failed`. A broken source cannot quietly poison the warehouse.

**Resilience.** The hh client retries throttling and 5xx responses with exponential backoff. If the NBK feed is down, the pipeline continues with the latest stored rates and refuses to run if they are older than 5 days. Duplicates inside one run are collapsed.

**Cheap incremental extraction.** The full vacancy page (with `key_skills`) costs one API request, so it is fetched only for vacancies not seen before. Known vacancies are refreshed from the lightweight search payload and keep their skills.

**Safe XML parsing.** NBK XML is parsed with `defusedxml`, which blocks entity expansion attacks. A test covers it.

**Relevance filter.** hh text search matches a word anywhere in a posting, so a query like `python` also returns teachers and marketers who mention it. Search results are filtered by hh professional role against `data/reference/it_roles.csv` before any details are fetched. Searching titles only (`HH_SEARCH_FIELD=name`) is also supported but returns far fewer vacancies in Kazakhstan.

**Skill extraction by dictionary.** `data/reference/skills.csv` maps canonical skills to aliases (`Postgres` and `постгрес` become `PostgreSQL`). Ambiguous short tokens (`go`, `r`) are marked exact-only and match only the explicit `key_skills` list, never free text. Symbol-heavy names (`C++`, `C#`) have their own boundary rules.

## Quick start

Requirements: Docker with Compose.

```bash
cp .env.example .env        # optional, defaults work
make demo                   # starts the stack and loads bundled sample data (no internet needed)
```

Then open:

- API docs: http://localhost:8000/docs
- Airflow: http://localhost:8080 (admin / admin, local development only)
- Database: `make psql`

`make demo` runs two daily snapshots of **synthetic** vacancies (generated by `scripts/generate_sample_data.py`, no real employers) that include deliberately broken records, so you can see validation and history in action.

### Run against live data

The hh API answers 403 without an application token, so live mode needs an app registered at https://dev.hh.ru. Put these into `.env`:

```bash
HH_APP_TOKEN=...            # application token issued by hh
HH_USER_AGENT=kz-jobs-pipeline/1.0 (you@example.com)   # hh requires an identifying User-Agent
HH_PERIOD_DAYS=30           # first load: 30 days back; daily runs need only 1-2
```

Then `make run`. The Airflow DAG `kz_jobs_daily` runs the same steps every day at 03:00 UTC (08:00 in Almaty). The offline demo works without any token.

### Without Docker

```bash
pip install -e ".[dev]"
export DATABASE_URL=postgresql://user:pass@localhost:5432/warehouse
# apply migrations/V*.sql in order (Flyway or psql), then:
kzjobs demo
uvicorn kzjobs.api.main:app --reload
```

## Example results (live data)

A snapshot loaded on 2026-11-25 from the hh API: Kazakhstan, 9 search queries, vacancies published in the last 30 days, IT roles only.

| Metric | Value |
|---|---|
| Vacancies loaded | 531 |
| Rejected by validation | 0 |
| With a stated salary | 26.4% |
| With at least one recognized skill | 83.2% |

Share of vacancies mentioning a skill, week of 2026-11-16 (140 vacancies):

| Skill | Share |
|---|---|
| SQL | 48.6% |
| Python | 38.6% |
| Docker | 27.9% |
| CI/CD | 27.1% |
| REST API | 25.7% |
| Git | 24.3% |
| PostgreSQL | 23.6% |
| Kubernetes | 17.9% |
| Linux | 17.1% |
| Java | 17.1% |

Monthly salary in KZT (midpoint of the range), roles with at least 5 stated salaries:

| Role | Vacancies | P25 | Median | P75 |
|---|---|---|---|---|
| Дата-сайентист | 8 | 1,187,500 | 1,400,000 | 1,563,769 |
| BI-аналитик, аналитик данных | 7 | 500,000 | 550,000 | 750,000 |
| Программист, разработчик | 39 | 300,000 | 500,000 | 1,000,000 |
| Тестировщик | 8 | 375,000 | 500,000 | 550,000 |
| Аналитик | 12 | 356,250 | 451,000 | 525,000 |
| Системный администратор | 8 | 367,500 | 375,000 | 412,500 |

Read these as a snapshot, not a trend. Only active postings are returned, so earlier weeks are undercounted, and the weekly series becomes meaningful as the daily DAG accumulates history. Samples per role are small, hh files data engineers mostly under the data scientist role, and `Python` and `Java` shares are partly shaped by the search queries.

## Example results (demo data)

Pipeline report for the two demo runs (stored in `ops.pipeline_run.stats`, exposed at `GET /quality/runs`):

| | Day 1 | Day 2 |
|---|---|---|
| Unique records | 65 (1 duplicate dropped) | 69 |
| Valid / rejected | 62 / 3 (4.6%) | 68 / 1 (1.4%) |
| Rejection reasons | `missing_title`, `salary_range_inverted`, `published_in_future` | `missing_title` |
| Warnings (loaded, salary excluded) | `salary_outlier`, `salary_unsupported_currency` | none |
| New versions | 62 | 8 |
| Changed (new version, old one closed) | 0 | 6 |
| Unchanged (nothing written) | 0 | 54 |

Version history of a vacancy whose salary was raised on day 2, `GET /vacancies/5000000/history`:

```json
{
  "vacancy_id": 5000000,
  "versions": [
    {
      "version_id": 1,
      "valid_from": "2026-11-17T06:00:00Z",
      "valid_to": "2026-11-18T06:00:00Z",
      "is_current": false,
      "salary_from": 917000
    },
    {
      "version_id": 63,
      "valid_from": "2026-11-18T06:00:00Z",
      "valid_to": null,
      "is_current": true,
      "salary_from": 1054550
    }
  ],
  "changes": [
    {
      "at": "2026-11-18T06:00:00Z",
      "run_id": 2,
      "changed_fields": { "salary_from": { "from": 917000, "to": 1054550 } }
    }
  ]
}
```

(Excerpt: unchanged fields and `row_hash` are omitted.)

Filtering current vacancies, `GET /vacancies?skill=Airflow&limit=1`:

```json
{
  "total": 9,
  "items": [{
    "vacancy_id": 5000048,
    "title": "Junior Data Engineer",
    "employer": "Kokzhiek Retail",
    "area_name": "Алматы",
    "salary_mid_kzt": 1520990,
    "skills": ["Airflow", "Docker", "Git", "Kafka", "Python"]
  }]
}
```

Salary quartiles per role, `GET /salaries/summary` (synthetic numbers, shown for the response shape):

```json
{ "role_name": "Backend-разработчик", "vacancies_with_salary": 13,
  "p25_kzt": 1054550, "median_kzt": 1497645, "p75_kzt": 1673365 }
```

## API

| Endpoint | Description |
|---|---|
| `GET /vacancies` | Current vacancies. Filters: `skill`, `role`, `area`, `min_salary_kzt`, `include_archived`, `limit`, `offset` |
| `GET /vacancies/{id}` | One current vacancy |
| `GET /vacancies/{id}/history` | All versions plus a field-level change log |
| `GET /skills/trends` | Weekly share of vacancies mentioning the top skills (`weeks`, `top`, `category`) |
| `GET /salaries/summary` | Salary quartiles in KZT per professional role |
| `GET /quality/runs` | Recent pipeline runs with their quality reports |
| `GET /health` | Liveness and database check |

## Orchestration

![Airflow DAG](docs/airflow-dag.png)

```
start_run -> [extract_fx, extract_hh] -> transform_load -> refresh_marts -> finalize
```

- `transform_load` contains the quality gate and the SCD2 merge in one transaction.
- `finalize` uses `trigger_rule=all_done`, so a failed run is always recorded as `failed` instead of staying `running`.
- `catchup=False`, `max_active_runs=1`: the hh API only returns the recent window, so backfilling would load nothing, and overlapping runs are not allowed.
- Task retries use exponential backoff.

The DAG is thin on purpose: it only calls the functions in `kzjobs/pipeline.py`, the same code the tests and the CLI run.

## Repository structure

```
.
├── migrations/            Flyway SQL: schemas, raw, core, SCD2, marts
├── src/kzjobs/
│   ├── extract/           hh (JSON, pagination, retries) and nbk (XML) extractors
│   ├── transform/         normalization, skill dictionary matcher
│   ├── validate.py        data quality rules (errors and warnings)
│   ├── load.py            raw inserts, staging, SCD2 merge
│   ├── pipeline.py        pipeline steps, quality gate, run bookkeeping
│   ├── api/main.py        FastAPI application
│   └── cli.py             `kzjobs run` / `kzjobs demo`
├── dags/hh_daily.py       Airflow DAG
├── data/
│   ├── reference/         skills.csv dictionary
│   └── sample/            synthetic demo data
├── tests/                 unit + integration + API tests
├── docker/, Dockerfile, docker-compose.yml, Makefile
└── .github/workflows/     CI: lint + tests on a PostgreSQL service
```

## Testing

```bash
pip install -e ".[dev]"
export TEST_DATABASE_URL=postgresql://user:pass@localhost:5432/warehouse_test
pytest
```

Integration tests apply the same migration files Flyway uses and run on a real PostgreSQL. Without `TEST_DATABASE_URL` only the unit tests run. Covered scenarios include:

- first load, idempotent re-run (nothing written), change creating a closed and a new version;
- the database refusing a second current version for one vacancy;
- rejection with reasons, the quality gate leaving `core` untouched, duplicate collapsing;
- NBK outage fallback and stale-rate protection;
- search-only refresh not wiping skills collected from the full vacancy page;
- retries with backoff, pagination and de-duplication in the hh client (mock transport);
- XML entity attack blocked;
- API filters, history, validation (422) and 404s.

## Limitations and next steps

- Vacancies that disappear from search results are not closed automatically. A "last seen" check with a grace period would detect closed postings.
- Salary is compared as gross or net as published (`salary_gross` is stored), not normalized to a single basis.
- Skill extraction is dictionary based. Embeddings or an LLM pass could catch skills outside the dictionary.
- Marts are materialized views refreshed daily. dbt models would add lineage docs and tests on top.
- Airflow runs as a single local container in Compose. Production would use separate scheduler and webserver services and secrets management.
- The offline demo uses synthetic data. Live results depend on hh API access conditions and on how many postings are active at the time of the run.
