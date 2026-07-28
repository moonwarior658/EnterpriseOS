# Codex Context

## Current stage

Stage 3 Supply.

Automation Core is completed. Stage 3.0 — preparation and acceptance of the
Supply domain model — completed at 100%. Stage 3.1A is completed at 100%,
deployed to production, and manually verified. After several days of real
operation and collection of factual issues, the next sub-stage is Stage 3.1B.

## Current state

- Основной рабочий документ: `docs/ROADMAP_STAGE_3_SUPPLY_v0.1.0.md`.
- Утверждённая спецификация этапа: `docs/eOS_STAGE_3_SUPPLY.md`.
- ADR-002 принят владельцем проекта 27 июля 2026 года.
- Stage 3.1A завершён на 100%: публичная Supply-форма, реестр заявок,
  упрощённое исполнение, частичное исполнение и долги, Dashboard и отдельный
  реестр долгов работают в едином контуре.
- Supply-циклы автоматически открываются и закрываются actions Automation
  Core; дни недели, время и параметры периода настраивает администратор.
- Выполнен UX-polish сценариев Supply и Repair.
- Legacy warehouse-контур удалён из активного API и интерфейса; старый
  публичный URL временно перенаправляет на Supply-форму. Repair-контур
  сохранён.
- `PARTIALLY_FULFILLED` считается завершённой заявкой; дальнейшая работа с
  незакрытым объёмом ведётся через долг подразделения.
- Stage 3.1A развёрнут в production, основной сценарий проверен вручную.
- Локальный baseline: `main`, commit `12186e2`
  (`fix(dashboard): exclude fulfilled supply requests from attention`).
- Локальный Alembic head: `20260728_0017`.
- Следующий шаг: несколько дней реальной эксплуатации, сбор фактических
  проблем, затем переход к Stage 3.1B.

Обработка заявок Stage 3.1A остаётся ручной, но жизненный цикл периодов заявок
автоматизирован. В backlog отложены таймеры, edit lock,
пользовательское уточнение неизвестной единицы, очередь mapping candidates,
настройка кодов подразделений. iiko относится к Stage 3.1B; реальные остатки,
supplier aliases, фасовки и альтернативные единицы, поставщики и закупочные
документы относятся к последующим подэтапам.

## Architecture

Execution flow:

EnterpriseOS
→ transactional outbox
→ automation worker
→ local EnterpriseOS handler для внутренних бизнес-действий
или
→ AutomationProvider → n8n → callback для технических интеграций

Rules:

- EnterpriseOS is the source of truth.
- Business logic stays inside EnterpriseOS.
- n8n is an execution orchestrator only.
- Internal Supply state transitions run in EnterpriseOS and do not use n8n.
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
- Local action handlers for idempotent internal business operations.
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
