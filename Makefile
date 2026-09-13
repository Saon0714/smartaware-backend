.PHONY: install dev test lint fmt typecheck openapi migrate revision worker beat db-create

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

worker:
	uv run celery -A app.worker.celery_app worker --loglevel=info

beat:
	uv run celery -A app.worker.celery_app beat --loglevel=info

db-create:        ## Local Postgres role + database + pgvector
	createdb smartaware 2>/dev/null || true
	psql -d smartaware -c "CREATE EXTENSION IF NOT EXISTS vector;"
