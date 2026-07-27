# Codex Context

## Current stage

Stage 3 Supply.

Automation Core is completed. Stage 3.0 — preparation and acceptance of the
Supply domain model — completed at 100%. The current sub-stage is Stage 3.1A.

## Current state

- Основной рабочий документ: `docs/ROADMAP_STAGE_3_SUPPLY_v0.1.0.md`.
- Утверждённая спецификация этапа: `docs/eOS_STAGE_3_SUPPLY.md`.
- Эксплуатационный `WorkRequest` MVP развёрнут, но не закрывает этап 3.
- ADR-002 принят владельцем проекта 27 июля 2026 года.
- Stage 3.1A начат: первый backend-срез Supply Request Foundation завершён
  и развёрнут.
- Срез включает справочники подразделений и направлений, заявки и строки,
  создание черновика, списки и карточки, отправку `DRAFT → SUBMITTED`,
  серверную нумерацию, tenant isolation и административный доступ.
- Production подтверждён: API health OK, database health OK,
  `automation-worker` и scheduler работают.
- Baseline: `main`, commit `12358a3` (`feat(supply): add request foundation`).
- Миграции применены до `20260727_0007`.
- PostgreSQL migration integration test прошёл цикл `0006 → 0007 → 0006 →
  0007`; перед миграцией создан и проверен backup.
- WorkRequest MVP и старые публичные URL сохранены без изменений.
- Следующий срез: базовый товарный справочник и единицы измерения.

Перечисленные выше результаты отражают зафиксированное состояние production
и migration-проверок для текущего backend-среза.

## Architecture

Execution flow:

EnterpriseOS  
→ AutomationProvider  
→ transactional outbox  
→ automation worker  
→ n8n  
→ callback  
→ EnterpriseOS

Rules:

- EnterpriseOS is the source of truth.
- Business logic stays inside EnterpriseOS.
- n8n is an execution orchestrator only.
- Reuse the existing dispatch and transactional outbox flow.
- Do not duplicate scheduler, dispatch, outbox, retry, worker, or callback logic.

## Automation Core completion

- Automation schedule CRUD.
- Scheduler and timing engine.
- Automation execution model.
- Transactional outbox.
- Persistent automation worker.
- Retry, timeout recovery, and protected idempotent callback flow.
- Idempotency-key protection for external side effects.
- Execution history and safe user-facing statuses and errors.
- Audit log and platform-admin diagnostics.
- Automation type catalog.
- End-to-end `smoke_test` through the importable n8n workflow.
- Health checks for n8n and n8n-postgres.
- n8n backup/restore tooling and retention.

## Known limitations

- Two pre-existing ESLint errors remain in `frontend/src/contexts/AuthContext.tsx`.
- Visual polish for tables and selects and broader responsive UI work are
  intentionally assigned to the future design stage and are not Automation
  Core debt.

## Deferred

- PWA.
- Web Push.
- Notification center.
- Apple Calendar.
- Table, select, and responsive UI polish (roadmap design stage).
- Mascots.
- Light and dark theme.

## Working rules

- Work only on the requested task.
- Do not update roadmap or documents unless explicitly requested.
- Do not modify `.env`, secrets, or infrastructure credentials.
- Do not commit or push unless explicitly instructed.
- Run only relevant tests during development.
- Keep the final report concise.
