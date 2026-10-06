# EnterpriseOS

Единое рабочее пространство компании; EOS владеет бизнес-данными, состоянием,
правилами, расчётами и аудитом. Проект развивается поэтапно.

## Документация

- [Project Charter](docs/PROJECT_CHARTER_v1.1.md) — ограничения и миссия.
- [Blueprint](docs/BLUEPRINT_v0.0.2.md) — бизнес-модель.
- [Roadmap](docs/ROADMAP_v0.12.0.md) — общая последовательность.
- [Supply roadmap](docs/ROADMAP_STAGE_3_SUPPLY_v0.1.0.md) — текущие задачи,
  production baseline и CURRENT / TEMPORARY / TODO / DEFERRED.
- [Codex Context](docs/CODEX_CONTEXT.md) — краткий контекст для работы.

## Репозиторий и стек

- `backend/api` — FastAPI, SQLAlchemy, Alembic, Python 3.12; локальные команды через uv.
- `frontend` — React, TypeScript, Vite; [frontend commands](frontend/README.md).
- `docker/compose/docker-compose.yml` — Docker Compose, PostgreSQL, Nginx,
  automation worker и отдельный локальный n8n.
- `print_agent` — Windows PDF Print Agent; [контракт](print_agent/README.md).
- `docs` — существующие authoritative project documents.

n8n — скрытый сменный исполнитель за AutomationProvider, без доступа к EOS PostgreSQL.
Внутренние business actions выполняются локальными EOS handlers через общий outbox/worker.
