# K3: ручной запуск регламента цен — 09.10.2026

## Подтверждённая причина

Production ID 13: type `products.sync_iiko_prices`, enabled=true, company,
interval=60, Asia/Yekaterinburg. Сохранённый payload прошёл existing strict
validation/scope: три подтверждённые точки, RUB, source и office evidence.
Проверенный ActionContext — ADMIN / TECHNICAL_ADMIN capability.

Read-only reproduction на production коде вернул 422 с точным detail:
`Automation type does not support manual run`. В catalog у K3 было
`supports_manual_run=False`, поэтому dispatch останавливался до создания
execution/outbox/audit; execution_count для ID 13 = 0. UI не переводил этот
конкретный detail и не учитывал catalog capability у кнопки «Запустить».
Это несовпадение ожидаемой функции K3 и зарегистрированного контракта,
а не ошибка payload или полномочий пользователя.

## Исправление и границы

- Только `products.sync_iiko_prices` получает `supports_manual_run=True`.
  Ручной запуск использует existing dispatch → execution/outbox → local handler.
  HTTP 201 означает постановку в очередь, не успешное обновление цен.
- Перед enqueue проверяются сохранённая company scope и существующий strict
  K3 contract: interval=60, source, active confirmed point mappings, RUB,
  office evidence. Ошибка возвращается безопасным 422 до создания execution.
- ADMIN/ActionContext, disabled schedule guard (409), unsupported-type guard,
  audit, transactional outbox и worker claim/terminal/retry checks сохранены.
- UI переводит unsupported manual run / ADMIN access / K3 configuration errors
  в конкретные русские сообщения. Кнопка учитывает authoritative catalog flag,
  enabled state и текущую отправку; неизвестный тип не запускается.
- Плановое выполнение использует прежний scheduler и local executor; новый
  отдельный scheduler, n8n workflow или bypass не создаётся.
- ID 13 используется как существующий регламент. Второго расписания нет;
  конфигурация/next_run_at вручную не меняются. Цены/локальные поля продукции
  не редактируются этим исправлением. Неизвестные SCHEDULED приоритеты остаются
  fail closed, Gate K3 этим проходом не закрывается. Миграция не требуется.

## Регрессии

Manual API 201 → pending execution + outbox с сохранённым payload; AuditEvent
RUN_REQUESTED; тот же LocalAutomationActionExecutor успешно обрабатывает run
на fixture data без n8n. Следующий плановый запуск не сдвигается вручную.
Плановая регрессия проверяет payload execution/outbox, hourly next_run_at и
успешный local worker. Invalid saved payload/company/interval → 422, disabled
→ 409, реальный non-admin ActionContext → 403; execution/outbox отсутствуют.
Frontend tests проверяют диагностические сообщения, catalog availability и
duplicate-submit guard; существующие регрессии создания K3 сохранены.

## Production и Git

Последняя фраза владельца разрешила исправление production; последующее сообщение
разрешило Git update по итогам. В main включаются также предыдущий hotfix создания
регламента, его тесты и отчёт. Production preflight: `cb4176a`, Alembic 0076,
ровно пять tracked изменений предыдущего hotfix; diff просмотрен. Все прежние
untracked files и локальные price artifacts сохраняются; payload artifacts в
GitHub не отправляются.

До синхронизации сохранены backup БД (custom dump, pg_restore --list check),
архив девяти implementation files и прежний hotfix diff:
`C:\eos\backup\eos-k3-manual-before-20261009.dump`,
`eos-k3-manual-code-before-20261009.tar`,
`eos-k3-manual-pre-sync-20261009.patch`.
Обновляются только API/worker/frontend, схема остаётся 0076. Production smoke
ручного enqueue выполняется во внешней rollback-транзакции: worker не видит
тестовый execution, опубликованные цены не пересобираются. Действительный
ручной запуск с обновлением цен остаётся действием пользователя.

## Результаты проверки и установки

Backend full suite: **1176 tests OK, 40 optional skips**; targeted dispatch/
catalog/K3 tests: 29 OK. Frontend creation/manual-run regressions: **21 OK**;
ESLint для изменённых файлов и production build OK (existing chunk-size warning).
`git diff --check` OK. Новых миграций нет.

Production API/worker/frontend пересобраны и обновлены. Live HTTP catalog
подтвердил supports_manual_run=true для K3; frontend HTTP отдаёт исправленную
логику запуска. ID 13 через production route + реальный ADMIN ActionContext
в изолированной внешней транзакции: 201/pending, execution/outbox payload
равны сохранённому payload, schedule audit RUN_REQUESTED присутствует.
Транзакция откатилась, worker не обрабатывал тестовый запуск.

Контрольные hashes **всех колонок** tenant product rows, manual price rows,
source snapshots и сохранённого регламента ID 13 одинаковы до/после.
Второе расписание не создавалось. После проверки действительный manual run
с обновлением снимка остаётся кнопке пользователя; визуальный browser smoke
не заявляется. Для проверки владельцем: обновить страницу, открыть ID 13,
«Запустить» → запись «Ожидает запуска», затем дождаться результата worker.
Ошибку последующего iiko чтения не считать ошибкой enqueue (201 ≠ price success).

Девять production implementation files входят в общий commit вместе с предыдущим
hotfix формы, его тестами и обоими отчётами. Git update разрешён владельцем;
production sync выполняется после push с резервной копией предыдущего diff.
Внутренние payload artifacts из `output/` остаются вне Git.
