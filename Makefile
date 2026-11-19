.PHONY: help up down migrate demo run test lint sample logs psql

help:  ## show this help
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-10s %s\n", $$1, $$2}'

up:  ## start Postgres, apply migrations, start API and Airflow
	docker compose up -d --build

down:  ## stop everything (data volume is kept)
	docker compose down

migrate:  ## re-run Flyway migrations
	docker compose run --rm flyway -connectRetries=10 migrate

demo: up  ## load bundled synthetic data (2 daily snapshots), no internet needed
	docker compose run --rm api kzjobs demo

run:  ## run the pipeline against the live hh and NBK sources
	docker compose run --rm api kzjobs run

test:  ## unit tests (integration tests need TEST_DATABASE_URL)
	pytest

lint:  ## ruff
	ruff check . && ruff format --check .

sample:  ## regenerate synthetic sample data
	python scripts/generate_sample_data.py

psql:  ## open psql in the warehouse
	docker compose exec postgres psql -U $${POSTGRES_USER:-warehouse} -d $${POSTGRES_DB:-warehouse}
