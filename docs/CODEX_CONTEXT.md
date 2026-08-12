# Codex Context

## Current stage

Stage 3 Supply.

Automation Core is completed. Stage 3.0 — preparation and acceptance of the
Supply domain model — completed at 100%. The required working contour of
Stage 3.1A is completed. Production verification was performed on 2 August
2026. Stage 3.1B начат: read-stock scope, authoritative document read-back и
verified PDF подтверждены в production; текущий срез — 5.5 Print Agent + print
queue. Весь Stage 3.1B не завершён.

## Current state

- Основной рабочий документ: `docs/ROADMAP_STAGE_3_SUPPLY_v0.1.0.md`.
- Утверждённая спецификация этапа: `docs/eOS_STAGE_3_SUPPLY.md`.
- ADR-002 принят владельцем проекта 27 июля 2026 года.
- Основной ручной контур Stage 3.1A работает: публичная Supply-форма, реестр
  заявок, рабочее место сопоставления, обязательные алиасы, серверный поиск
  товаров, `PLANNED` как «В работе», отдельное завершение, ввод факта,
  `FULFILLED` / `PARTIALLY_FULFILLED`, Dashboard и реестр долгов.
- Supply-циклы автоматически открываются и закрываются actions Automation
  Core; дни недели, время и параметры периода настраивает администратор.
- Выполнен UX-polish сценариев Supply и Repair.
- Legacy warehouse-контур удалён из активного API и интерфейса; старый
  публичный URL временно перенаправляет на Supply-форму. Repair-контур
  сохранён.
- `PARTIALLY_FULFILLED` считается завершённой заявкой; дальнейшая работа с
  незакрытым объёмом ведётся через долг подразделения.
- Production-проверка обязательного рабочего контура Stage 3.1A выполнена
  02.08.2026.
- Сверхвыдача работает: фактически отправленное количество может превышать
  запрошенное, при этом долг равен нулю.
- Долги создаются и отображаются в отдельном реестре и на Dashboard.
- Сопоставление предлагает товар по исходному названию автора заявки;
  подтверждённые алиасы участвуют в дальнейшем распознавании.
- Активный долг хранится по подразделению + товару EOS + единице. До Stage
  3.4 долги в разных единицах не сравниваются и не объединяются.
- Повторные долги считаются по циклам: первый цикл без тревоги, второй —
  жёлтый, третий и последующие — красные.
- Stage 3.1B / 4, 5.4A и 5.4B подтверждены в production. Текущий локальный
  срез 5.5 доводит verified PDF через persistent print job, Automation
  Core/outbox и n8n до Print Agent; `INTERNAL_TRANSFER` отложен.

В Stage 3.1B выполнено:

- read-only доступ к iikoServer и reference snapshot;
- чтение складов и остатков в staging-контур EOS;
- явный mapping товаров, единиц и складов iiko ↔ EOS;
- admin-only API/UI для mapping и аудит решений;
- безопасное создание первичного каталога EOS из iiko staging.

Также production-confirmed создание `OUTGOING_INVOICE`, authoritative
read-back и verified PDF. Print queue и Print Agent реализуются локально в
срезе 5.5; production deployment и физическая печать не выполнялись.
`INTERNAL_TRANSFER`, подтверждение передачи и signed-return остаются вне
текущего среза.

Обработка заявок Stage 3.1A остаётся ручной, но жизненный цикл периодов заявок
автоматизирован.

Незакрытый backlog 3.1A:

- админ-интерфейс подразделений и кодов;
- пользовательское уточнение неизвестных единиц;
- очередь mapping candidates;
- таймеры проверки 5/10 минут и предупреждения;
- полноценный временный edit lock;
- tooltip долгов.

Этот backlog не входит в текущий эксплуатационный критерий закрытия 3.1A и
не блокирует переход к Stage 3.1B.

Отдельное фактическое погашение долга относится к Stage 3.1B / 5: долг не
уменьшается до подтверждения фактической передачи и возврата подписанного
документа. Реальные остатки относятся к 3.1B / 4, перемещения, документы iiko,
PDF, печать и подтверждение получения — к 3.1B / 5, supplier aliases и
поставщики — к 3.1C.

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
