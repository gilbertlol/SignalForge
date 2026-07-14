# SignalForge

SignalForge is a local-first, AI-powered revenue operating system. It is being built to hunt
for business opportunities via configurable Hunt Profiles, search pluggable sources, collect
evidence, deduplicate organizations and contacts, score prospects, centralize communications
and tasks, and coordinate human and AI operators — all while running on a developer laptop
first and remaining deployable to a private server later.

This repository implements **GOR-233 — Bootstrap the local-first Django platform**,
**GOR-234 — Model organizations, contacts, opportunities, evidence, and scoring**,
**GOR-242 — Build reusable hunt profiles and opportunity criteria engine**, and
**GOR-235 — Build lead discovery, enrichment, and daily hunting runs**, plus the backend
security foundation for **GOR-244 — secure accounts, workspaces, and role isolation**, and the
backend foundation for **GOR-243 — local and cloud AI model gateway**: the technical
foundation, the core revenue-domain model with a deterministic scoring engine, a versioned
criteria engine for defining what SignalForge should hunt for, and a resumable pipeline that
actually discovers, deduplicates, enriches, and scores candidates end to end. It intentionally
does not yet contain messaging, a frontend, or AI integration; see
[Deferred work](#deferred-work) below.

## Current implemented scope

- Django + Django REST Framework project (`config/`) with environment-based settings
  (`local`, `test`, `production`) that share one `base.py`.
- A modular-monolith layout under `apps/`: `core`, `accounts`, `organizations`, `contacts`,
  `opportunities`, `evidence`, `scoring`, `hunting`, `discovery`, `tasks`, `audit`,
  `integrations`.
- A custom user model (`apps.accounts.User`) so the project never depends on Django's
  built-in `auth.User`.
- A `Workspace` model and `WorkspaceScopedModel` abstract base (`apps.core`) so business
  models are tenant-scoped from the start. Full multi-tenancy (multiple workspaces, per-user
  membership) is GOR-244; until then, the API operates against a single ensured default
  workspace — see [Domain model, evidence, and scoring](#domain-model-evidence-and-scoring).
- **Organization**, **Contact**, and **Opportunity** models with merge-safe deduplication
  (`apps.organizations`, `apps.contacts`, `apps.opportunities`), plus a REST API
  (serializers, viewsets, filtering) for each.
- **Evidence** (`apps.evidence`): provenance records (source, reliability, verification
  status, observed date) attachable to an Organization or Opportunity.
- **Scoring** (`apps.scoring`): a deterministic rule engine producing immutable
  `ScoreSnapshot`s across three independent families (prospect quality, score confidence,
  post-contact opportunity score), with an explain endpoint proving the "why" behind every
  score.
- **Hunting** (`apps.hunting`): reusable, versioned `HuntProfile`s with a recursive AND/OR/NOT
  criteria tree, a dry-run mode that evaluates a profile against real local Organizations, and
  a create/clone/activate/pause/archive lifecycle — see
  [Hunt profiles and the criteria engine](#hunt-profiles-and-the-criteria-engine).
- **Discovery** (`apps.discovery`): a resumable discover → normalize → deduplicate → enrich →
  collect evidence → score pipeline, a demo lead-source provider proving the whole path works
  end to end, manual entry, CSV import, and daily scheduled runs — see
  [Lead discovery, enrichment, and scheduled runs](#lead-discovery-enrichment-and-scheduled-runs).
- A minimal `AuditLogEntry` model and `record()` service (`apps.audit`) — a base for future
  auditing, not the complete audit system.
- A `ProviderAdapter` interface seam (`apps.integrations.adapters`) for future lead sources,
  messaging providers, and AI models. No real provider is wired up yet.
- PostgreSQL, Redis, Celery, and Celery Beat, all orchestrated through Docker Compose.
- `/health/live` and `/health/ready` endpoints.
- Structured JSON application logging.
- Automated tests (pytest + pytest-django + factory_boy), Ruff, mypy, and pre-commit.
- Workspace memberships, built-in roles with granular overrides, invitations,
  tracked/revocable sessions, scoped API keys, login throttling, and security audit events.
- Encrypted AI-provider credentials, OpenAI-compatible and mock adapters, privacy-aware model
  routes, ordered fallback, usage budgets, circuit breaking, schema validation, and invocation logs.
- Canonical email/SMS conversations, approval-gated outreach, explainable eligibility checks,
  suppression and consent enforcement, reply classification, sequences, and mock transports.

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
make setup
make up
make migrate
make ensure-workspace
docker compose run --rm web python manage.py bootstrap_owner
```

`setup` copies `.env.example` to `.env` (if missing) and builds images. `up` starts db, redis,
web, worker, and beat in the background. `migrate` applies database migrations.
`ensure-workspace` idempotently creates the single default Workspace the API operates against
(see below) — run it once after the first `migrate`. Optionally follow with `make seed-examples`
to create four example Hunt Profiles (see
[Hunt profiles and the criteria engine](#hunt-profiles-and-the-criteria-engine)).

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

## Domain model, evidence, and scoring

- **Organization / Contact / Opportunity** (`apps/organizations`, `apps/contacts`,
  `apps/opportunities`) are the core revenue-domain entities. `POST /api/v1/organizations/`
  and `POST /api/v1/contacts/` are dedup-aware: creating an org/contact with a
  domain/email that already exists in the workspace returns the existing record rather than
  a duplicate (`apps.organizations.services.find_or_create_by_domain`,
  `apps.contacts.services.find_or_create_by_email`). Records without a known domain/email
  simply aren't deduplicated.
- **Evidence** (`apps/evidence`) attaches provenance to an Organization or Opportunity via a
  generic relation: `POST /api/v1/organizations/{id}/evidence/` and
  `POST /api/v1/opportunities/{id}/evidence/`. Freshness is never stored as a field (a static
  "freshness" value goes stale the moment time passes) — it's the `age_days` computed
  property, read live by the scoring engine.
- **Scoring** (`apps/scoring`) evaluates configurable `ScoringRule`s against a subject
  (and its evidence) to produce an immutable `ScoreSnapshot` for one of three families:
  `prospect_quality`, `score_confidence`, `opportunity_score`. A matched hard-disqualifier
  rule forces the score to `0` regardless of other positive points. Every rule's
  match/no-match outcome is recorded in the snapshot's `components`, so:
  - `POST /api/v1/organizations/{id}/scores/{family}/recompute/` — runs the rules and
    persists a new snapshot.
  - `GET /api/v1/organizations/{id}/scores/{family}/explain/` — returns the latest snapshot
    verbatim (no recomputation), which is exactly "why this score was calculated."
  - The equivalent `opportunities/{id}/scores/{family}/...` endpoints exist too.
  - Snapshots can never be edited after creation (`apps.scoring.exceptions.ImmutableRecordError`
    on any second `.save()`), so historical explanations stay accurate even if rules change later.
- **Single default workspace**: GOR-244 (multi-user auth, workspace membership) doesn't exist
  yet, so every API endpoint operates against one workspace ensured by
  `make ensure-workspace` / `apps.core.services.get_default_workspace()` — there is no
  `workspace_id` in the API. When GOR-244 lands, this becomes real per-user workspace
  resolution without a schema change to the models above.

## Hunt profiles and the criteria engine

- A **Hunt Profile** (`POST /api/v1/hunt-profiles/`) is a reusable business-acquisition
  thesis. Its criteria are a recursive AND/OR/NOT tree of leaf conditions (`{"field", "op",
  "value"}` — the same shape `apps.scoring.ScoringRule` uses, via the shared
  `apps.core.conditions` primitive), submitted as JSON and validated against a JSON Schema
  (the `jsonschema` package) before anything is written.
- **Versioned and immutable**: `POST /api/v1/hunt-profiles/{id}/versions/` builds an entirely
  new `HuntProfileVersion` from scratch — there is no "edit criteria in place" endpoint.
  Nothing under a version is ever updated afterward, so once GOR-235 records which version a
  discovery run used, that run stays reproducible forever.
- Leaf-level semantics beyond plain AND/OR/NOT (documented here because the source ticket
  names these concepts without fully specifying how they interact): a matched
  `is_hard_disqualifier` leaf excludes the candidate outright regardless of the rest of the
  tree; every `is_required` leaf must match regardless of which branch of the tree it's in;
  `weight` sums across matched non-disqualifier leaves into a total compared against the
  version's `ResultThreshold.min_total_score`.
- **Dry-run** (`POST /api/v1/hunt-profiles/{id}/dry-run/`) evaluates the criteria tree against
  real local Organizations (all of them by default, or a specific `organization_ids` list) —
  the same evaluation function (`apps.hunting.services.evaluate_candidate`) a live discovery
  run's score phase calls per candidate (see the next section), so dry-run and a real run
  agree by construction. Results include matched/failed criteria with reasons, total weight,
  evidence count, the latest `score_confidence` snapshot when one exists, and a
  `recommended_next_action` (`review_queue` / `excluded` / `below_threshold`).
- **Lifecycle**: `activate`, `pause`, `archive`, and `clone` actions on
  `/api/v1/hunt-profiles/{id}/...`. Cloning copies the current version's entire tree into a
  new draft profile's version 1.
- `make seed-examples` creates four draft example profiles (automation agencies, local
  professional services, SaaS companies, businesses hiring CRM/automation roles) — idempotent,
  safe to run repeatedly, and doubles as a working example of the version-creation payload
  shape (`apps/hunting/management/commands/seed_hunt_profile_examples.py`).
- **Not built** (see [Deferred work](#deferred-work)): the natural-language AI-assisted
  profile builder (GOR-243) and a guided configuration UI (GOR-241).

## Lead discovery, enrichment, and scheduled runs

- **The pipeline** (`apps.discovery.services.execute_run`) runs six phases against a specific
  `HuntProfileVersion` in order: discover → normalize → deduplicate → enrich → collect evidence
  → score. It's one resumable orchestrating task, not a multi-task Celery chain — idempotency
  comes from each phase only touching `SourceRecord`s still at that phase's entry status, so
  calling it again on an already-completed (or partially-completed) run just finds nothing left
  to do in the phases that already finished. `POST /api/v1/discovery-runs/` starts one (against
  a `hunt_profile`'s current version) and runs it via Celery immediately.
- **Providers are looked up by key, never hard-coded** — `apps.integrations.registry` resolves
  a `source_key` string (e.g. `"demo"`) to a concrete adapter. `apps.integrations.providers.demo`
  ships one working `LeadSourceAdapter` and one `TechnologyDetectionAdapter` so the whole
  pipeline is exercisable without any real credentials; `SourcePolicy.source_key` (from
  GOR-242) is what a `HuntProfileVersion` uses to configure which sources run, with
  `max_records`/`budget_cents` enforced per source. A version with no `SourcePolicy` rows at
  all falls back to the demo source; a version with an explicit
  `[{"source_key": "demo", "is_enabled": false}]` runs no automatic discovery at all
  (manual entry / CSV import only) — that distinction is deliberate, not an oversight.
- **Partial failure is isolated per provider**: each source's `search()` call is wrapped so one
  provider raising doesn't touch another's results — the run ends `partial` (some
  `ProviderResult`s failed, at least one succeeded) rather than `failed` (all of them did).
- **Deduplication reuses GOR-234's existing service** (`find_or_create_by_domain`) rather than
  reinventing one — re-running the same source, even from a brand-new `DiscoveryRun`, resolves
  to the same Organizations. `SuppressionEntry` (a domain blocklist, deactivate rather than
  delete to explicitly allow rediscovery again) is checked first and blocks org creation.
- **Manual entry and CSV import**: `POST /api/v1/discovery-runs/{id}/source-records/manual/`
  and `POST .../source-records/import-csv/` (multipart) both feed the same pipeline from
  `normalize`/`deduplicate` onward — they're just different ways candidates enter it.
- **The review queue is just a filter**: `.../source-records/` with `?status=qualified` —
  nothing in this project sends messages or contacts anyone automatically (GOR-236 doesn't
  exist yet), so "produce a review queue rather than contacting prospects automatically" is
  true by construction, not by a safeguard that could be bypassed.
- **Scheduled runs**: one static hourly Celery Beat entry
  (`discovery.dispatch_scheduled_discoveries`) queries `SchedulePolicy(frequency="daily",
  is_enabled=True)` for active profiles that haven't had a scheduled run yet today — not
  `django-celery-beat`'s dynamic per-profile scheduling, which would be a new dependency for
  what one query already does.
- **Not built** (see [Deferred work](#deferred-work)): real (non-demo) provider adapters, a
  generic rate-limiter (the demo adapter needs none), and hard Celery-level task cancellation
  (`cancel` is cooperative — checked between phases, not a kill signal).

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

- **GOR-237** — Work-item / task-assignment models and the human + AI operator execution
  system (the `tasks` app is currently an empty skeleton).
- **GOR-241** — The guided hunt-profile configuration UI (and any frontend at all — this
  repository currently uses REST endpoints and Django Admin for operational configuration).
- Fuzzy/near-duplicate resolution for organizations and contacts — dedup today is exact-match
  on normalized domain/email only.
- Any real (non-demo) lead-source, enrichment, or messaging provider — `EmailVerificationAdapter`
  and `WebsiteAnalysisAdapter` are interfaces only (no implementation, demo or otherwise);
  `LeadSourceAdapter` and `TechnologyDetectionAdapter` each have one demo implementation
  proving the seam, not a real one.
- A production deployment target (reverse proxy, TLS termination, process manager beyond
  `gunicorn`/`celery`) beyond what `config/settings/production.py` and
  `requirements/production.txt` already prepare.

## Other developer commands

Run `make help` (or just `make`) to list every available command, including `make logs`,
`make shell` (Django shell), and `make dbshell` (psql against the local database).
