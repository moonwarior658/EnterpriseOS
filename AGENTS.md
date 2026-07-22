# EnterpriseOS — repository instructions

## Product and sources of truth

EnterpriseOS is the company's digital operating system: one workspace and
source of truth for business processes, designed to remove routine work while
leaving decisions to people. It is not an ERP and should deliver practical
value incrementally.

Read project context in this priority order:

1. `docs/PROJECT_CHARTER_v1.1.md` — mission and governing constraints.
2. `docs/BLUEPRINT_v0.0.2.md` — business and product model.
3. `docs/ROADMAP_v0.12.0.md` — current scope and delivery sequence.
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

## Codex execution rules

These rules apply to every Codex task in this repository unless the user explicitly overrides them.

### Scope

- Work only on the explicitly requested task.
- Do not expand the task into adjacent features, refactoring, design polishing, documentation updates, or technical debt cleanup unless requested.
- Prefer the smallest coherent implementation that fits the existing architecture.
- Reuse existing services, schemas, components, utilities, and patterns instead of duplicating logic.
- Inspect only the files relevant to the requested task and their direct dependencies.
- Do not read the full roadmap for routine implementation tasks.
- Read the roadmap only when:
  - the task changes project scope;
  - the task updates completion status;
  - the user explicitly requests roadmap work.

### Architecture

- EnterpriseOS is the governing core and the single source of truth.
- Business logic, validation, calculations, permissions, and state transitions must remain inside EnterpriseOS.
- n8n is a hidden execution orchestrator only.
- Preserve the `EnterpriseOS -> AutomationProvider -> n8n` boundary.
- Do not give n8n direct access to the EnterpriseOS PostgreSQL database.
- Do not create a separate n8n workflow for every user-created schedule unless explicitly required.
- Reuse the existing transactional outbox and dispatch flow for automation execution.
- Do not duplicate execution, outbox, retry, callback, or scheduling logic.

### Safety and repository changes

- Do not modify `.env`, secrets, credentials, production data, Docker volumes, or infrastructure access settings.
- Do not expose secrets, tokens, passwords, webhook credentials, internal payloads, or stack traces.
- Do not delete or reset databases, volumes, migrations, user data, or production configuration.
- Never run destructive commands such as `git reset --hard`, `git clean -fd`, `docker compose down -v`, or equivalent unless the user explicitly requests them.
- Do not modify project documents, roadmap files, ADRs, Blueprint, Project Charter, or `AGENTS.md` unless the task explicitly requires it.
- Do not commit, push, merge, rebase, create pull requests, or change branches unless explicitly instructed.
- Preserve the existing `Smoke test` / `smoke_test` technical artifact unless the task explicitly targets it.

### Frontend

- Follow the existing EnterpriseOS visual system and component patterns.
- Prioritize working functionality over general design polishing.
- Do not introduce a new UI library or dependency when the task can be completed with the existing stack.
- Do not expose technical automation internals to ordinary users or administrators.
- Translate expected backend errors into safe and understandable Russian messages.
- Do not show stack traces, webhook URLs, provider internals, raw payloads, or execution identifiers in normal user-facing screens.
- Keep API-derived values, such as `next_run_at`, authoritative on the backend.
- Preserve keyboard navigation, loading states, disabled states, and protection from duplicate form submission.
- Do not fix the two pre-existing ESLint errors in `frontend/src/contexts/AuthContext.tsx` unless the task explicitly targets them.

### Backend

- Use existing schemas and contracts whenever possible.
- Do not change an API contract unless the task requires it.
- Keep database mutations transactional.
- Reuse existing service-layer functions instead of implementing business logic directly in API routes.
- Add database migrations only when the data model genuinely changes.
- Preserve callback idempotency and terminal execution-state protection.
- Return safe, explicit HTTP errors without leaking implementation details.

### Testing and verification

During implementation, run only the tests directly related to the changed functionality.

Before reporting completion, run:

- relevant backend tests;
- relevant frontend tests;
- frontend production build when frontend code changed;
- ESLint for changed frontend files;
- `git diff --check`.

Run the full backend test suite only when:

- shared automation infrastructure changed;
- database models or migrations changed;
- dispatch, outbox, worker, callback, authentication, or permissions changed;
- the user explicitly requests a full test run;
- the task is being prepared for deployment or stage completion.

Do not repeatedly run the same expensive test suite when no relevant code changed.

### Final report

Keep the final report compact and include:

1. What was implemented.
2. Changed files.
3. API or database changes, if any.
4. Tests and checks executed with results.
5. `git status`.
6. Known limitations or deferred work.

Do not repeat the full task description in the report.
Do not include large diffs unless requested.
Clearly state when commit and push were not performed.

Read `docs/CODEX_CONTEXT.md` before routine implementation tasks.
