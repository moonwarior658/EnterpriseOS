# EnterpriseOS — repository instructions

## Product and sources of truth

EnterpriseOS is the company's digital operating system: one workspace and
source of truth for business processes, designed to remove routine work while
leaving decisions to people. It is not an ERP and should deliver practical
value incrementally.

Read project context in this priority order:

1. `docs/PROJECT_CHARTER_v1.1.md` — mission and governing constraints.
2. `docs/BLUEPRINT_v0.0.2.md` — business and product model.
3. `docs/ROADMAP_v0.8.0.md` — current scope and delivery sequence.
4. `docs/ADR-001_AUTOMATION_ARCHITECTURE.md` — accepted automation decision.

Do not silently resolve contradictions between these documents. Report them
and align documentation before implementing conflicting behavior. Do not skip
Roadmap stages: finish the current stage as a working result before starting
the next.

## Repository map

- Backend: `backend/api` (FastAPI, SQLAlchemy, Alembic, Python 3.12).
- Frontend: `frontend` (React and TypeScript).
- Docker Compose: `docker/compose/docker-compose.yml`.
- Project documents: `docs/`.
- Database migrations: `backend/api/alembic/versions/`.
- Backend tests: `backend/api/tests/`.

## Automation boundary and infrastructure

EnterpriseOS owns business data, state, rules, calculations, audit, and user
experience. Business logic belongs only in EnterpriseOS. n8n is a replaceable,
hidden execution adapter behind `AutomationProvider`; it performs technical
integration steps and returns results through versioned API/webhook contracts.
An accepted HTTP request means command receipt, not business success.

The target production topology requires EnterpriseOS and its dedicated n8n
instance to run locally on the company's main server. `N8nProvider` must call
that local n8n instance. The existing NL VPS and its n8n are a temporary,
separate legacy contour for the Telegram bot, proxy, and already-running
processes. New critical EnterpriseOS processes must not depend on the NL VPS;
it is expected to be retired after internal chats and processes move to
EnterpriseOS.

n8n, including the local instance, must never access EnterpriseOS PostgreSQL
directly or become the source of business state. Communication is only through
authenticated APIs and webhooks. Every automation execution requires a unique
`execution_id`, idempotent handling, transactional outbox delivery, and a
callback whose result is persisted by EnterpriseOS.

## Local development and checks

Use Python 3.12 and `uv` for local backend work:

```bash
cd backend/api
uv venv --python 3.12
uv pip install --python .venv/bin/python -r requirements.txt
uv run python -m unittest discover -s tests -v
```

Run targeted backend tests during development and the full command above
before handoff. Frontend has no test script currently; available checks are:

```bash
cd frontend
npm run lint
npm run build
```

## Database and operational safety

Create a new Alembic revision for every schema change; never edit an existing
or previously applied migration. Review generated SQL and upgrade/downgrade
logic. Do not generate or apply migrations unless the task requires it.
Before any production migration, create a verified backup and confirm the
recovery path.

Never run `docker compose down -v`, delete Docker volumes, reset PostgreSQL, or
remove databases, backups, or other persistent data unless the user explicitly
requests the exact destructive action. Never commit secrets, credentials,
tokens, `.env` files, database dumps, or local development artifacts.

## Change discipline and Definition of Done

Work on a focused feature or chore branch based on current `main`. Inspect
`git status`, the complete diff, and `git diff --check`; stage only task files.
Commit, push, merge, and production deployment only when explicitly included
in the task.

A change is done when relevant checks and tests pass, migrations and data are
safe, no unrelated changes are included, and the final report clearly lists
files, decisions, validation results, and remaining risks. Prefer a working,
tested result over extra documents, speculative abstractions, or refactoring
outside the requested scope.
