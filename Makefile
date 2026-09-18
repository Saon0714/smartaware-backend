.PHONY: install dev test lint fmt typecheck openapi migrate revision update worker beat db-create

install:          ## Sync dependencies from uv.lock
	uv sync

dev:              ## Run the API with autoreload
	uv run fastapi dev app/main.py --port 8000

test:
	uv run pytest -q

lint:
	uv run ruff check .

fmt:
	uv run ruff format . && uv run ruff check --fix .

typecheck:
	uv run mypy app

openapi:          ## Export the schema the frontend generates its client from
	uv run python scripts/export_openapi.py openapi.json

migrate:          ## Apply migrations
	uv run alembic upgrade head

revision:         ## make revision m="add widgets"
	uv run alembic revision --autogenerate -m "$(m)"

update:           ## After a git pull: apply migrations, then seed. Idempotent.
	uv run python scripts/update.py

worker:
	uv run celery -A app.worker.celery_app worker --loglevel=info

beat:
	uv run celery -A app.worker.celery_app beat --loglevel=info

db-create:        ## Local Postgres role, database and pgvector (run once, needs superuser)
	@# Installing pgvector into template1 means every database created
	@# afterwards - including the throwaway test database - inherits it, so
	@# migrations never need superuser to CREATE EXTENSION.
	psql -d template1 -c "CREATE EXTENSION IF NOT EXISTS vector;"
	psql -d postgres -c "DO \$$\$$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='smartaware') THEN CREATE ROLE smartaware LOGIN PASSWORD 'smartaware'; END IF; END \$$\$$;"
	@# CREATEDB is for the test suite only. Do not grant it in production.
	psql -d postgres -c "ALTER ROLE smartaware CREATEDB;"
	createdb -O smartaware smartaware 2>/dev/null || true
	psql -d smartaware -c "CREATE EXTENSION IF NOT EXISTS vector;"

seed:             ## Seed reference data (idempotent)
	uv run python scripts/seed.py

create-admin:     ## make create-admin email=a@b.com
	uv run python scripts/create_admin.py --email "$(email)" --generate
