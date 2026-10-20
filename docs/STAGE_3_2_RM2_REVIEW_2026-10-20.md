# R-M2 «Последняя закупочная цена» — локальный review, 20.10.2026

База: production R-M1 `ee9d7a20755bf8d8cdfed53f50e6f33b222f43de`, Alembic `20261020_0080`.
Ветка: `feature/raw-materials-rm2`. Main `b0126cb` с промежуточным K5C не используется.
Владелец отдельно разрешил эту ветку/worktree и локальный commit, подтвердил валюту **RUB**.
Push, deployment, production migration, расписание и запись бизнес-данных production не выполнялись.

## Реализованное поведение

- Реестр и карточка читают последнюю сохранённую метрику EOS. Кнопка карточки создаёт команду Core
  `materials.sync_iiko_purchase_price`; существующие outbox/worker/retry/ownership/terminal guards сохраняются.
  Во время iiko I/O нет открытой DB-транзакции; результат, аудит и завершение execution публикуются одной транзакцией.
- Склад строго `1c22edc0-7ded-41c9-b781-0389462c7247`, источник строго
  `244d6eaf9c7c106993d10feb0ff9883dbdb73101cd3a2ab6852c9ba5b9907401`.
  Только включённая активная карточка, существующие CONFIRMED product/unit mappings; текущие source reference UUID/units перепроверяются.
- Выгружаются семь ограниченных месячных интервалов: шесть полных месяцев и текущий месяц до дня сбора.
  На 20 октября: `[2026-04-01, 2026-10-21)`. В iiko передаются включительные даты окончания каждого окна.
  Manifest содержит границы, число документов, hash и fetched_at. Повреждённый/неполный контракт и неизвестная пагинация — failure.
- Только PROCESSED, точный item.store либо defaultStore. Непроведённые/отменённые,
  внутренние represents_store и точный технический сахарный приход
  `5bf2b1c7-8c91-b774-01a0-ae4cafa53ba1` исключаются с причиной. Префикс EOS сам по себе не исключает закупку.
  Неизвестный контрагент, is_employee, сумма/количество/НДС или дата блокируют потенциальную последнюю закупку.
- Формула одного документа: `Σsum / ΣactualAmount`; actualAmount должен быть положительным и равным amount.
  НДС включён в sum; discount повторно не вычитается, округлённый price не участвует.
  Суммы/количества суммируются Decimal с precision 80, деление — precision 38; исходные значения сохранены,
  форматирование цены в UI до четырёх десятичных знаков. Нет неявного пересчёта PCS/KG или containerId.
- По явному требованию владельца несовместимые единицы **в любом приходе выбранного окна** блокируют текущую цену,
  даже если последняя строка уже KG. Это консервативная политика R-M2; нельзя обойти историческую проблему старой/новой ценой.
  Равная последняя дата нескольких документов, конфликт ревизий одного UUID или неоднозначные строки — BLOCKED.
- `READY`, `BLOCKED`, `NO_DATA` различимы; failure не создаёт пустой snapshot и не затирает историю.
  UI показывает «Нет данных», «Требуется проверка», дату, единицу, НДС, ход обновления и документ-основание.
- Денежное чтение и запуск: ADMIN, SUPPLY_MANAGER, DIRECTOR, DEPUTY_DIRECTOR, ACCOUNTANT.
  Производственные роли сохраняют знания/фото без цены, refresh, sources или денежной истории. Сортировки по цене нет.
  Generic provider callback не может завершить этот локальный action в обход snapshot-транзакции.
- Daily execution архитектурно использует тот же Core action и вычисляемые на дату запуска окна;
  schedule contract намеренно запрещён до отдельной бизнес-приёмки. Ни одного schedule не создаётся.

## Пилот: реальные карточки владельца, расчёт локально

Production Git/schema/health и десять включённых карточек прочитаны read-only. Таблица получена из свежего
read-only incomingInvoice export и supplier references iiko; вычисления выполнены локально тем же evaluate.
Текущие source product/baseUnit и имена учётных единиц отдельно сверены read-only: **10/10 совпадений**; несовместимая историческая единица подтверждена как «шт».
Production snapshots/executions не создавались, карточки не создавались повторно, mappings не изменялись.
Это проверка источника и кода, **не независимая сверка первичных документов/iikoOffice и не бизнес-приёмка**.

Цена — RUB с НДС за указанную учётную единицу. Для BLOCKED принятой цены нет;
дата/документ в таблице показывают последнего кандидата для разбора, а не принятую цену.

| SupplyProduct UUID | Сырьё | Цена с НДС | Ед. | Дата кандидата | Накладная | Качество / причина |
|---|---|---:|---|---|---|---|
| `7a13b478-d039-41b2-acef-d2bfa336b936` | Крем  на растительных маслах (Шантипак,Белария ) | 294.9 | л | 2026-10-05 | №4661 · `d9a74c6f-709e-421a-b952-8e9c7807a6f4` | READY |
| `92d401a2-b2ae-4b83-929b-e2b439a4bfc3` | Маргарин | 240.7 | кг | 2026-10-05 | №4662 · `d4cd2536-b17f-8981-01a1-0ccc519c93e2` | READY |
| `2ab59f97-2291-4f64-8e7b-d74511aa493f` | Масло сливочное | 716.5 | кг | 2026-10-14 | №4801 · `1faded9a-9cda-47b1-9510-3c5ad368f683` | READY |
| `18c3849d-b882-4de5-a14f-a9cbbc009f4f` | Молоко для коктейлей и кухни | 97.95 | л | 2026-10-14 | №4802 · `d5c59f4f-ff79-9e05-01a1-3c826d9558b4` | READY |
| `be7c1ced-755e-4fa3-b7e9-cc7851c3c07d` | Мука пшеничная в/с | 43.9 | кг | 2026-10-10 | №4773 · `c640c5f8-a253-4eeb-01a1-336466c13717` | READY |
| `d5b79f17-c09f-4496-a9fd-c64a135f94bc` | Сахар песок | 84.5 | кг | 2026-10-10 | №4773 · `c640c5f8-a253-4eeb-01a1-336466c13717` | READY |
| `21fe689f-a2d0-41d4-8c6a-29b73b24e01f` | Сливки 33 % | — | кг | 2026-09-27 | №4563 · `ee378b63-d67c-4d8d-b658-45bb6d4590c6` | BLOCKED: исторические PCS/KG, пересчёт не подтверждён |
| `b52ea50f-d5a8-48b7-892c-5151fe884c8e` | Сыр Маскарпоне | — | кг | 2026-09-25 | №EOS-IN-20260925-F9ADF0F66F8A · `91fbd726-881e-6081-01a0-d21447fbc5dc` | BLOCKED: исторические PCS/KG, пересчёт не подтверждён |
| `3050e500-0781-49ff-a1fa-773047454baa` | Сыр творожный | — | кг | 2026-10-14 | №4801 · `1faded9a-9cda-47b1-9510-3c5ad368f683` | BLOCKED: исторические PCS/KG, пересчёт не подтверждён |
| `b417a565-9361-42e2-a761-b413aa7b7e8b` | Шоколад | 1022.7 | кг | 2026-09-15 | №4411 · `cdbaee39-fd2d-40d7-9250-3aa2d19ba2f2` | READY |

Для сливок проблемные накладные №0000-000001 (21.04) и №0000-000167 (10.07);
для маскарпоне №0000-000099 (29.05) и №0000-000234 (18.08);
для творожного сыра №0000-000001 (21.04), №0000-000136 (24.06), №0000-000167 (10.07).
UUID несовместимой единицы: `cd19b5ea-1b32-a6e5-1df7-5d2784a0549a`; основная KG:
`7ba81c3a-8de5-8f9d-fb9f-e39efcbc57cc`. Исходные строки доступны в защищённой расшифровке snapshot.
Точные суммы/количества и hashes сохраняются в EOS при разрешённом запуске; приватные live exports не включены в Git.

## API и миграция

- POST `/raw-materials/{id}/metrics/refresh`: только `request_id` UUID, 202 означает постановку в Core, не успех.
  Повторный request_id возвращает прежний запуск, конкурентные запросы объединяются в активный execution.
- GET `/raw-materials/{id}/metrics?offset=0&limit=25`: защищённая история snapshots и безопасный статус обновления.
- GET `/raw-materials/{id}/metrics/{snapshot_id}/sources`: tenant/product-bound документ, поставщик,
  строки/НДС/исходные единицы, исключения, policy/mapping/source hashes и manifest. Cache-Control no-store.
- List/detail: `last_purchase_price`, без этого поля для пользователя без денежного capability.
- Миграция **`20261020_0081` после `20261020_0080`** создаёт только material_purchase_snapshots,
  индексы, FK/unique/check constraints, immutable и execution-scope triggers. Business seeds/backfill/schedules отсутствуют.
  Downgrade с накопленной историей запрещён; rollback релиза сохраняет данные, не откатывает production БД поверх Supply.

## Проверки

- Полный backend: `WORK_REQUEST_UPLOAD_DIR=<temporary directory> python -m unittest discover -s tests -v`:
  **1270 tests, OK, 56 skipped** (опциональные окружения, включая PG-проверки, запускаемые отдельно).
  Supply/«Продукция», Core, RBAC/auth/callback regression входят в suite.
- Целевые R-M2: **10 tests OK** — Decimal, склады/status/exclusions, конфликты, единицы, неизвестный новый приход,
  no-data, идемпотентность, actual Core retry, terminal/ownership, callback guard, source drill-down, все роли и tenant isolation.
  Полный синтетический путь включает настоящий collector с fake read-only iiko transport и семь окон;
  сохранение/чтение результата и документа идут через API/worker, без production fixtures в Git.
- Изолированный PostgreSQL 17 UTF-8: **6 уникальных тестов OK** (3 R-M1 + 3 R-M2), включая
  `0079 → 0080 → 0081 → 0079 → 0081` на пустой БД, concurrent refresh/publication,
  immutable history, tenant/execution/status/amount constraints, audit rollback, populated downgrade guard.
- Frontend: **216/216 tests OK**, production build OK, ESLint изменённых файлов OK.
  Полный ESLint: ровно две прежние ошибки AuthContext.tsx; файл не изменён.
  Component smoke: кнопка → pending/running → сохранённая цена → накладная → ошибка обновления с сохранением цены.
- Браузерный smoke **не выполнен**: runtime сообщил `apps: [], browsers: []`.
  JSDOM/API тесты не объявляются браузерной приёмкой.
- `git diff --check` OK. Main, исходный release и посторонние production untracked файлы сохранены.

## Ограничения и изолированный выпуск

R-M2 готов к техническому review из отдельной ветки на R-M1; K5C из main не переносится.
Перед будущим выпуском отдельно потребуются актуальный preflight, verified backup/recovery,
применение только 0081 и rebuild API/worker/frontend. Разрешения на выпуск сейчас нет.
Браузерная и независимая первичная/iikoOffice приёмка остаются незавершёнными.
Три позиции заблокированы: коэффициенты/исторические конверсии — отдельная подтверждаемая работа R-M4;
отсутствующее подтверждение сотрудника-контрагента также нельзя снять догадкой.
R-M3 (средняя/расход), R-M4 (версии конверсий/резервы), R-M5 (независимая приёмка/эксплуатация)
не реализованы этим релизом. Планировщик, iiko full-sync, массовое включение и калькулятор ТТК не запускаются.

## Изменённые файлы

- `backend/api/alembic/versions/20261020_0081_material_purchase_snapshots.py`
- `backend/api/app/api/routes/automation.py`
- `backend/api/app/api/routes/raw_materials.py`
- `backend/api/app/automation/catalog.py`
- `backend/api/app/automation/local_actions.py`
- `backend/api/app/core/authorization.py`
- `backend/api/app/integrations/iiko/client.py`
- `backend/api/app/models/__init__.py`
- `backend/api/app/models/raw_material.py`
- `backend/api/app/raw_materials/purchase_refresh.py`
- `backend/api/app/raw_materials/purchases.py`
- `backend/api/app/raw_materials/service.py`
- `backend/api/app/schemas/automation.py`
- `backend/api/tests/test_automation_catalog.py`
- `backend/api/tests/test_automation_schedules_api.py`
- `backend/api/tests/test_material_purchases.py`
- `backend/api/tests/test_material_purchases_postgres.py`
- `backend/api/tests/test_raw_materials.py`
- `backend/api/tests/test_raw_materials_postgres.py`
- `backend/api/tests/test_requests_api.py`
- `docs/STAGE_3_2_RM2_REVIEW_2026-10-20.md`
- `frontend/src/components/MaterialPurchase.tsx`
- `frontend/src/pages/RawMaterialsPage.tsx`
- `frontend/src/services/rawMaterials.ts`
- `frontend/tests/materialPurchase.test.ts`
- `frontend/tests/rawMaterials.test.ts`
