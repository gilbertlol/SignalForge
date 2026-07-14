# SignalForge

SignalForge is a local-first, AI-powered revenue operating system. It is being built to hunt
for business opportunities via configurable Hunt Profiles, search pluggable sources, collect
evidence, deduplicate organizations and contacts, score prospects, centralize communications
and tasks, and coordinate human and AI operators — all while running on a developer laptop
first and remaining deployable to a private server later.

This repository implements **GOR-233 — Bootstrap the local-first Django platform**: the
technical foundation the rest of SignalForge is built on. It intentionally does not yet
contain business logic; see [Deferred work](#deferred-work) below.

## Current implemented scope

- Django + Django REST Framework project (`config/`) with environment-based settings
  (`local`, `test`, `production`) that share one `base.py`.
- A modular-monolith layout under `apps/`: `core`, `accounts`, `organizations`, `contacts`,
  `opportunities`, `tasks`, `audit`, `integrations`.
- A custom user model (`apps.accounts.User`) so the project never depends on Django's
  built-in `auth.User`.
- A `Workspace` model and `WorkspaceScopedModel` abstract base (`apps.core`) so future
  business models can be tenant-scoped without a later migration overhaul. Full multi-tenancy
  and auth are GOR-244.
- A minimal `AuditLogEntry` model and `record()` service (`apps.audit`) — a base for future
  auditing, not the complete audit system.
- A `ProviderAdapter` interface seam (`apps.integrations.adapters`) for future lead sources,
  messaging providers, and AI models. No real provider is wired up yet.
- PostgreSQL, Redis, Celery, and Celery Beat, all orchestrated through Docker Compose.
- `/health/live` and `/health/ready` endpoints.
- Structured JSON application logging.
- Automated tests (pytest + pytest-django + factory_boy), Ruff, mypy, and pre-commit.

## Prerequisites

- Docker and Docker Compose (v2 `docker compose` syntax).
- No local Python installation is required — the app, tests, linter, and type checker all run
  inside the `web` container.

## Environment setup

```bash
cp .env.example .env
```

Edit `.env` if you want non-default credentials. For anything beyond local development,
generate a real `DJANGO_SECRET_KEY`:

```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

`.env` is git-ignored and must never be committed. `.env.example` contains placeholders only.

## Starting the stack

```bash
make setup   # copies .env.example -> .env (if missing) and builds images
make up      # starts db, redis, web, worker, beat in the background
make migrate # applies database migrations
```

The API is then reachable at `http://localhost:8000`. PostgreSQL and Redis are **not**
published to the host by default — reach them via `make dbshell` or `docker compose exec`.

## Stopping the stack

```bash
make down
```

## Running migrations

```bash
make migrate           # apply migrations
make makemigrations    # generate new migrations after model changes
```

## Running tests

```bash
make test
```

This runs `pytest` inside the `web` container against real Postgres and Redis (`db`/`redis`
must be running — `make up` starts them). Tests use `config.settings.test`
(`CELERY_TASK_ALWAYS_EAGER=True`, fast password hasher).

## Linting and type checks

```bash
make lint       # ruff check
make format     # ruff format (applies fixes)
make typecheck  # mypy, with django-stubs / djangorestframework-stubs
```

`make check` runs lint, format-check, typecheck, `manage.py check`, a migration-consistency
check, and the test suite in one pass — the same checks required before this ticket is
considered done.

## Celery worker and scheduler

`make up` starts both `worker` (`celery -A config worker`) and `beat`
(`celery -A config beat`) alongside the web process. To watch their logs:

```bash
docker compose logs -f worker beat
```

There is one demonstration task, `apps.core.tasks.debug_task`, used to prove the Celery →
Redis → worker wiring; it has no business meaning.

## Health endpoints

- `GET /health/live` — always returns `200 {"status": "ok"}` if the process can respond.
  Confirms liveness only; checks no dependencies.
- `GET /health/ready` — returns `200` with `{"status": "ok", "checks": {"database": "ok",
  "redis": "ok"}}` when both PostgreSQL and Redis are reachable, or `503` with
  `"unavailable"` per failed check otherwise. Responses never include exception text, stack
  traces, or configuration values.

## Configuration

- `config/settings/base.py` holds every setting shared across environments.
- `config/settings/{local,test,production}.py` each `from .base import *` and override only
  what differs for that environment (`DEBUG`, allowed hosts, secret key handling, password
  hasher, static-file storage, `CELERY_TASK_ALWAYS_EAGER`, secure-cookie/HSTS flags).
- All configuration is environment-variable driven via `django-environ`; see `.env.example`
  for the full list. PostgreSQL and Redis are configured with discrete variables
  (`POSTGRES_*`, `REDIS_*`) rather than a combined URL, so the Postgres container's own
  required environment and Django's database config can never drift out of sync.
- `DJANGO_SETTINGS_MODULE` defaults to `config.settings.local` in `manage.py`; Docker Compose
  sets it explicitly per service.

## Creating the first local owner account

There is no seeded administrator account or default password anywhere in this repository.
Create your own local account interactively:

```bash
make superuser
```

This runs Django's standard `manage.py createsuperuser`, which prompts for email and password
and never stores a default credential.

## Deferred work

The following are intentionally **not** implemented in this ticket and belong to later Linear
issues:

- **GOR-234** — Real domain models for `organizations`, `contacts`, and `opportunities`
  (currently empty app skeletons), plus evidence collection, deduplication, and scoring.
- **GOR-237** — Work-item / task-assignment models and the human + AI operator execution
  system (the `tasks` app is currently an empty skeleton).
- **GOR-243** — A concrete local/cloud AI model gateway. Only the `AIModelAdapter` interface
  exists today (`apps/integrations/adapters.py`), with no implementation.
- **GOR-244** — Full authentication, multi-user accounts, workspace membership, and role-based
  permissions. Today there is only a minimal custom `User` model and a standalone `Workspace`
  model with no membership relationship between them yet.
- Any real lead-source or messaging provider integration — `apps.integrations.adapters` only
  defines the seam (`LeadSourceAdapter`, `MessagingAdapter`), not an implementation.
- A production deployment target (reverse proxy, TLS termination, process manager beyond
  `gunicorn`/`celery`) beyond what `config/settings/production.py` and
  `requirements/production.txt` already prepare.

## Other developer commands

Run `make help` (or just `make`) to list every available command, including `make logs`,
`make shell` (Django shell), and `make dbshell` (psql against the local database).
