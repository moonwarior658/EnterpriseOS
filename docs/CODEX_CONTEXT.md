# Codex Context

## Current production baseline

**CURRENT — 06.10.2026:** Git `eb59755cb0a6061b44fe7c8a56cae3232400a750`
(`eb59755`), Alembic `20261002_0068`; production baseline и синхронизация
Mac / origin / production предоставлены владельцем. Этот документационный
проход проверяет локальный код, не повторяет live production audit.

Stage 3 Supply: 3.0 DONE; operational 3.1A/3.1B/3.1C production/business verified;
Stage 3.1P **DONE и развёрнут**. 3.2 PARTIAL; весь Stage 3 не завершён.

## Sources of truth

1. [Project Charter](PROJECT_CHARTER_v1.1.md) — governing constraints.
2. [Blueprint](BLUEPRINT_v0.0.2.md) — business/product model.
3. [Main roadmap](ROADMAP_v0.12.0.md) — общая последовательность.
4. [Supply roadmap](ROADMAP_STAGE_3_SUPPLY_v0.1.0.md) — задачи и фактические
   статусы Stage 3; подробный backlog не дублируется в main roadmap.
5. [Supply spec](eOS_STAGE_3_SUPPLY.md) — CURRENT/TEMPORARY продуктовые правила.
6. [ADR-001](ADR-001_AUTOMATION_ARCHITECTURE.md) и
   [ADR-002](ADR-002_SUPPLY_DOMAIN_MODEL.md) — архитектурные границы.

[Employee/User](STAGE_3.1P_USERS_AND_RESPONSIBILITY_BUSINESS_SPEC.md),
[RBAC](ACCESS_CONTROL_AND_ROLE_HIERARCHY_v1.md),
[Repairs](REPAIR_WORKFLOW_BUSINESS_SPEC_v1.md) задают профильные правила.
[Audit 18.09.2026](STAGE_3_SUPPLY_AUDIT_2026-09-18.md) — исторический snapshot,
не текущий baseline. Противоречия не разрешать молча.

## Current system

- Employee — человек; User — access account. HUMAN/SERVICE разделены;
  Human account lifecycle через Employee card, `/users` — legacy route.
- 13 фиксированных ролей; backend allowed_actions / ActionContext authoritative.
  Immutable audit и human-readable UI; global Audit Explorer только ADMIN.
- Canonical Supply create `/supply/requests/new`; Seller cycle/direction/need date
  системные, окно настраивается через Regulatory Tasks. Изменение и повторное
  подтверждение сохраняют ту же заявку до закрытия окна. Детали — Supply spec.
- **TEMPORARY:** Seller SupplyRequest допускает выбор активной RETAIL_POINT
  без resolved shift/assigned department; остальные role/window/ownership/tenant
  guards остаются. Исключение не отменяет repair shift gate.
- Procurement needs/requests, allocations/orders, confirmation/documents/acceptance,
  iiko incoming receipt и payments/settlements работают. Предоплата может быть
  связана с order или быть авансом поставщику без order.
- iiko — внешний factual source, EOS — business state owner. Order ≠ Confirmation
  ≠ Document ≠ Acceptance ≠ Payment ≠ accounting fact.
- INTERNAL_TRANSFER при completion остаётся NEW; OUTGOING_INVOICE и incoming
  receipt имеют свои подтверждённые контракты. Не переносить status одного
  document type на другой.
- line.quantity — requested/planned quantity для stock calculation;
  send_quantity — actual fulfillment. Долг = max(planned - actual, 0).
- Repairs: HANDYMAN default, эскалация SUPPLY_MANAGER, ExternalContractor,
  specialization/visit_at, cost/INVOICE/ACT до/после close. Неполный completed
  external repair требует действий; payment из Repair автоматически не создаётся.
- Dashboard: «Требует внимания» и «Назначенные события» (upcoming contractor visits).
  Общие internal reminders — TODO; cards не доказывают delivery notifications.

## Architecture

EnterpriseOS → transactional outbox → automation worker → local EOS handler
для внутренних действий или AutomationProvider → local n8n → callback для
технических интеграций. EOS хранит business state/правила/расчёты/аудит.
n8n не получает доступ к EOS PostgreSQL. HTTP receipt не равен business success.
Не дублировать execution/outbox/dispatch/retry/callback/scheduling logic.
Regulatory Tasks — пользовательская configuration layer Automation Core;
smoke_test — технический артефакт, сохранять его.

## TODO / DEFERRED

- **TODO:** отдельный iiko contracts research: authoritative IDs,
  employee/location/department semantics, UI-managed mappings, затем EOS ↔ iiko
  redesign и пересмотр Seller work context. Linking/shifts/mappings работают;
  canonical identity не перепроектировалась; общая архитектура временная.
- **TODO 3.2:** ТТК-расчёт, chef confirmation, production plan/fact. Request window,
  canonical need collector и Supply plan/fact уже CURRENT/PARTIAL, не «с нуля».
  Seller confirmed snapshot сохраняется отдельно от draft; close фиксирует
  последний confirm и отбрасывает незавершённые правки (миграция `20261006_0069`,
  локальные проверки; production deployment отдельно).
- **DEFERRED:** Weighted Average и Substitutions по business decision.
- **DEFERRED:** DRIVER assigned transports без достоверного источника назначения;
  physical handover/signed-return и отдельное покрытие старого долга.
- **TODO:** общий reminders/checklists/reports contour, полный Dashboard exceptions,
  inbound supplier email, forecast и оставшиеся extensions 3.3/3.4 — см. roadmap.
- **DEFERRED:** PWA/Web Push/notification center, Apple Calendar, чаты,
  итоговая design/responsive polish, mascots/themes.

## Known limitations and working rules

- Два baseline ESLint errors в frontend/src/contexts/AuthContext.tsx не исправлять
  вне явного scope. Local/mock tests не заменяют browser/production acceptance.
- Работать только по запросу; сохранять dirty changes и не расширять scope.
- Код, документы, migrations, commit/push/deploy меняются только в разрешённом scope.
- Не изменять .env, secrets, credentials или persistent production data.
- Использовать существующие contracts/services/UI; frontend не является security boundary.
- Не угадывать external identity/mappings или неизвестную legacy атрибуцию.
- Relevant tests/checks и компактный отчёт с доказанными результатами и ограничениями.
