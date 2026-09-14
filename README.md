# smartaware-backend

FastAPI backend for the SmartAWARE public website, Customer Portal and Admin Portal.

This is a **standalone repository**. The frontend (`smartaware-frontend`) is a
separate repo with a separate deploy, and communicates with this service purely
over HTTP. There is no shared code between them — the only contract is the
OpenAPI schema this service publishes at `/openapi.json`.

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- PostgreSQL 17 with the `pgvector` extension
- Redis 7+

## Local setup

```bash
cp .env.example .env          # then edit
uv sync                       # install dependencies from uv.lock
make db-create                # role, database and pgvector (needs superuser, once)
make migrate                  # build the schema
make seed                     # reference data - idempotent, safe to re-run
make create-admin email=you@example.com
make dev                      # http://localhost:8000
```

`make db-create` installs pgvector into `template1` rather than only into
the application database. Creating an extension requires superuser, and
doing it once in `template1` means every database created afterwards —
including the throwaway test database — already has it, so migrations run
as the unprivileged application role. It also grants `CREATEDB` to that
role for the test suite; **do not grant `CREATEDB` in production**.

macOS via Homebrew:

```bash
brew install postgresql@17 pgvector redis
brew services start postgresql@17
brew services start redis
```

Alternatively `docker compose up` runs Postgres, Redis, the API, the Celery
worker and beat together.

## Common commands

| Command | Purpose |
|---|---|
| `make dev` | Run the API with autoreload |
| `make test` | Run the test suite |
| `make lint` / `make fmt` | Ruff check / format |
| `make typecheck` | mypy |
| `make openapi` | Export `openapi.json` for the frontend's codegen |
| `make migrate` | Apply Alembic migrations |
| `make revision m="..."` | Create a migration |
| `make worker` / `make beat` | Celery worker / scheduler |
| `uv run python scripts/run_job.py reindex-faq` | Run the FAQ index now |
| `uv run python scripts/run_job.py purge-chat-logs` | Run the retention purge now |

## Architecture notes

**Permissions are enforced here, never in the frontend.** The frontend's
role-aware UI is a convenience. Every role check and every client-data scope
lives in `app/core/permissions.py` and `app/core/deps.py`, and is covered by
`tests/test_permissions.py` and `tests/test_client_isolation.py`.

**CORS is an explicit allowlist** (`CORS_ALLOWED_ORIGINS`), never a wildcard.
The frontend is a separate origin and sends credentialed requests, so a
wildcard would be both unsafe and rejected by browsers.

**Configuration vs. settings.** Deploy-time values (database URL, API keys,
CORS origins) are environment variables in `app/core/config.py`. Values
SmartAWARE staff must change at runtime (chat retention window, invite expiry,
notification recipients, escalation threshold) live in the `settings` database
table and are read via `app/core/settings_service.py`. Content — FAQ, services,
About Us copy, form fields, wizard questions — is database-driven and editable
from the Admin Portal. None of it is hardcoded.

**Wise payments (spec Section 12).** We construct an Open Payment Link URL from
invoice data and redirect. There is deliberately no Wise API credential and no
code path that calls the Wise API — programmatic payment-link creation is
unsupported by Wise and must not be built.

## Smart AI and background jobs

The chatbot needs `OPENAI_API_KEY` in `.env`. Without it the chat endpoint
returns 503 with a plain message rather than a fabricated answer, and the
re-index job exits with a clear error instead of a traceback.

Two jobs run nightly under Celery beat:

| Job | Schedule | Purpose |
|---|---|---|
| `faq.reindex` | 02:30 UTC | Incremental FAQ embedding (spec 4.4) |
| `chat.purge_logs` | 03:30 UTC | Delete transcripts past the retention window (spec 4.5) |

The re-index is strictly incremental: it embeds only entries whose `updated_at`
is newer than their `indexed_at`, removes embeddings for soft-deleted or
unpublished entries, and leaves everything else untouched. It runs every night
even when nothing changed — spec 4.4 requires a no-op run rather than a skipped
one, so a late edit cannot sit unindexed.

Both jobs are plain functions in `app/jobs/`, with the Celery tasks as thin
wrappers, so they can be run by hand and the scheduler stays replaceable.

After seeding or editing FAQ content, run the index once rather than waiting
for the nightly job:

```bash
uv run python scripts/run_job.py reindex-faq
```

## Keeping the frontend in sync

After adding or changing any endpoint:

```bash
make openapi                                        # in this repo
cd ../smartaware-frontend && npm run gen:api        # in the frontend repo
```

CI in the frontend repo regenerates the client and fails on a diff, so a
backend change that the frontend hasn't picked up is caught at build time.
