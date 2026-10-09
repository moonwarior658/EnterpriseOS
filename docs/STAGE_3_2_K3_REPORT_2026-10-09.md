# Stage 3.2 / K3 — реальные цены продукции

09.10.2026. **Обычные цены готовы локально к публикации после review.**
K3 полностью не закрыт: приоритеты пересекающихся SCHEDULED и browser acceptance
не подтверждены. Production публикация, включение расписания и deployment не
выполнялись. Commit/push/merge/смена ветки не выполнялись.

## Результат повторной разведки

Старые R0/K1 CSV не требуются: iiko прочитан повторно через existing production
IikoServerClient/config. EOS SELECT выполнялись в transaction READ ONLY с rollback;
iiko — GET/auth/logout. Credentials/config не копировались и не сохранялись.

Production HEAD до/после: `067a99111944e720db9e41152700419131225c32`.
Alembic до/после: `20261009_0075`. Четыре прежних untracked entries, включая backup,
не изменились; никаких файлов production не записано. K2 deployed подтверждён
владельцем, HEAD/migration проверены live; это не повторная бизнес-приёмка K2.

141 published EOS product UUID; source fingerprint совпадает с текущей
конфигурацией. Все 141 main unit UUID/name совпали с текущими catalogue/MeasureUnit.
Текущие three RETAIL_POINT mappings подтверждены ID-only:

| Точка | EOS Department UUID | iiko price department UUID (= OLAP mapping в текущем runtime) |
|---|---|---|
| Матросова 15 | a29ac646-322f-47ab-8d31-d3d41fe1a510 | b6ecb8bc-d67b-4cc1-8c75-0cada5e0a248 |
| Матросова 35 | 246a46d1-6ad8-4894-a039-d3756b10b4b2 | ddad7418-dcf0-4116-b565-b9785e936c45 |
| Игарская 25В | 8a1f09e8-8948-40e8-bdaf-b04f94375be8 | 674a60af-a265-4233-adc6-02d1bd883c61 |

Новый reader/collector/preview также запущен **в памяти** контейнера через stdin:
только SELECT/iiko reads, без миграции, snapshot publication и deployment.
Последний collected snapshot: 2026-10-09T06:11:08.460065+00:00 UTC,
**11:11:08 Asia/Yekaterinburg**, окно **[08.09.2026, 10.11.2026)**.
Все три точки дали revision **16367080**.

| На дату 09.10.2026 | Количество |
|---|---:|
| EOS изделия × три точки | 423 |
| Возвращённые price contexts для EOS UUID | 413 |
| Effective intervals во всём окне | 713 |
| Подтверждённые ordinary цены | **363** |
| Исключены из обычного прейскуранта | **50** |
| Контекст отсутствует | **10** |
| Product-size contexts пилота | 0 |
| SCHEDULED contexts пилота | 0 |

Изначальный более узкий fresh read [01.10,01.11) дал 443 intervals; число 713
относится к финальному 63-дневному snapshot, а не к увеличению ассортимента.
В первом fresh read дополнительно прочитаны 19 referenced menuChange/byId:
все PROCESSED, без schedule. Повторный запрос глобального SCHEDULED API нашёл
6 контекстов на другой, неподтверждённой точке. Они **не включены** в snapshot
EOS и не доказывают приоритет на пилотных точках.

## Контракт, единицы и независимое подтверждение

Прочитаны официальные документы:

- [v2/price](https://ru.iiko.help/article/api-documentations/tseny-zadannye-prikazami?cm=1&ds=1&gc=1): effective intervals `[dateFrom,dateTo)`, BASE/SCHEDULED,
  included, schedule, category overrides, department/product/size IDs, revision.
- [Приказы](https://ru.iiko.help/article/api-documentations/prikazy?cm=1&ds=1&gc=1): NEW/PROCESSED/DELETED, dateIncoming/dateTo, department items и расписание.
- [Периоды действия](https://ru.iiko.help/article/api-documentations/periody-deystviya?cm=1&ds=1&gc=1): weekdays 1–7, полуинтервалы HH:mm.
- [Ценовые категории](https://ru.iiko.help/article/api-documentations/tsenovye-kategorii?cm=1&ds=1&gc=1): отдельные категории и pricing strategies.
- [Прейскурант iikoOffice](https://ru.iiko.help/article/iikooffice-9-1/goods-and-service-pricelist?cm=1&ds=1&gc=1): приказ перекрывает цену карточки в период действия;
  удалённый/распроведённый приказ не учитывается; категории/расписание задают контекст.

v2/price не передаёт валюту и unit цены. Source unit ID подтверждён API, а
семантика цены/RUB/ordinary context подтверждена владельцем в текущем чате:
«да всё ок и это в рублях. Приказов посмотреть нельзя». Агент сам iikoOffice
визуально не осматривал. Подтверждение относится к запрошенным controls:

| Изделие / артикул | Матросова 15 | Матросова 35 | Игарская 25В | Единица |
|---|---:|---:|---:|---|
| Горячий шоколад / 00667 | 150 | 120 | 120 | RUB / порц |
| Тесто дрожжевое / 01016 | 350 | 350 | 350 | RUB / кг |
| Заказной Торт Наслаждение / 74615 | 2500 | 2500 | 2500 | RUB / кг |

Эти суммы совпали и в финальном snapshot. Категории «Яндекс»/«Зал GH» и другие
контексты не назначаются обычной цене. API fields включённости/цены категории
сохранены отдельно; обычный прайс использует included/price без category selection.

BASE берётся из уже рассчитанных effective intervals v2/price: EOS не восстанавливает
приоритет raw приказов по UUID/номеру/порядку ответа. Изменение, отмена и истечение
приказов поступают через очередной полный bounded snapshot; отсутствие нового
контекста не заменяется старой ценой, defaultSalePrice или выручкой Sales.

**Конкретное ограничение SCHEDULED:** date-only API/UI не задаёт время, а цена
может меняться внутри дня. Официальный price response не даёт явного поля
приоритета между пересекающимися расписаниями. Office evidence недоступен,
на pilot нет natural scheduled samples. Поэтому при применимом расписании,
неизвестной overnight/zero-width семантике или нескольких BASE resolver скрывает
сумму и возвращает TIME_DEPENDENT/CONFLICT. В UI — «Цена требует проверки».
Полный arbitrary SCHEDULED precedence не реализован и не объявлен проверенным.

Если такие приказы появятся, минимальный следующий контроль: конкретный product
UUID/артикул, point UUID, дата и время до/на/после границы HH:mm, оба document IDs,
их PROCESSED/dateTo, обычная/category цена, included и выбранный Office effective
результат на пересечении. Для текущих 363 ordinary цен этот blocker отсутствует.

## Реализация

- Typed bounded reader `IikoServerClient.get_prices`: Decimal, строгий envelope,
  required fields, point mismatch/oversize guards, includeOutOfSale=true, existing
  auth/retry/session. Нет iiko writes и нет network в portal GET.
- Collector выбирает только published UUID source в EOS. Каталог/единицы
  проверяются по ID; результат для новых UUID выбрасывается до persistence.
  При изменении unit/mappings/catalog membership между collect/review/publication
  требуется recollect. Source network выполняется без открытой DB session.
- Ordinary resolver: date/point/base unit, полуоткрытые effective intervals;
  included=false и missing → null; подтверждённый zero отображается; конфликты
  скрывают сумму. Статус ассортимента EOS при source exclusion не меняется.
- Новая additive таблица `product_knowledge_price_snapshots`, миграция **0076**:
  tenant/source FK, unique review hash, interval check и lookup index. Снимки
  неизменяемые; нет seed/backfill. Downgrade с сохранённой историей блокируется.
- Source preview/publish требуют ADMIN/review hash; source row lock, AuditEvent,
  идемпотентность и stale revision guard. Существующий manual `prices-preview` /
  `prices-import` из первого прохода сохранён. Его storage не перезаписывается.
- GET list/detail предпочитают последний полный snapshot, покрывающий дату.
  Отсутствие/исключение в нём подавляет старый manual price. Предыдущие snapshots
  сохраняют историю. Поля K2, version, verification и локальные знания не меняются.
- `products.sync_iiko_prices` через existing scheduler/outbox/local executor:
  company scope, interval **60 минут**, approved explicit policy source/points/
  currency/evidence; network outside transaction, snapshot/audit/terminal outbox
  success в одной транзакции после claim guard. New n8n workflow не создаётся.
  Production schedule не создан и не включён.
- UI показывает confirmed цену, единицу, период и время наблюдения. API additive
  поле `price_conflict_points` скрывает amounts конфликтных доступных точек.
  Roles/permissions Supply/Sales/K2 не расширены. Existing Smoke test сохранён.

Обновление делает full bounded reread за today−31…today+32 в business timezone
Sales source. Не зависит от delta/tombstone assumptions. Сбой чтения/валидации
оставляет последний успешный snapshot с его observed_at. Таблица и карточка
показывают «Ценовой снимок устарел» при возрасте >2 часов (backend UTC),
«Последнее обновление цен завершилось ошибкой» для последнего FAILED/TIMED_OUT/
RETRYING после успешного получения и дату последнего успешного снимка, даже
если цена отсутствует. `price_health` — additive per-point API поле; source,
execution IDs, payload и текст технической ошибки не выдаются. Новый успешный
снимок снимает прежнюю ошибку. Используются существующие snapshots/executions,
дополнительной миграции нет. Hourly snapshot не гарантирует мгновенное
отражение изменения между синхронизациями.

## Артефакты и публикация после review

Сохранены только нормализованные fields, без credentials/raw catalogue/OLAP:

- [source snapshot](../output/stage3_2_k3/source_snapshot.json);
- [policy](../output/stage3_2_k3/policy.json) — owner-confirmed RUB/ordinary controls и explicit points;
- [review report](../output/stage3_2_k3/review_report.json);
- [resolution review](../output/stage3_2_k3/resolution_review.json) — все 423 point/product outcomes;
- [summary](../output/stage3_2_k3/summary.json) и [SHA-256 manifest](../output/stage3_2_k3/manifest.json).

Reviewed live plan hash:
`4a55e7609971d085482e87b48a9b2110e69f174ccbb58acc6d1fa29ca908952d`.
Он привязан к tenant, source snapshot и актуальному EOS unit/product/mapping scope.
При изменении данных scope между review и publish сервер требует новый collect.

CLI из `backend/api` в отдельном разрешённом runtime:

```text
uv run python -m app.product_knowledge.cli prices-collect --tenant eclair --source SOURCE_ID --actor-id ADMIN_ID --report POLICY_JSON --snapshot SOURCE_SNAPSHOT_JSON
uv run python -m app.product_knowledge.cli prices-source-preview --tenant eclair --source SOURCE_ID --actor-id ADMIN_ID --snapshot SOURCE_SNAPSHOT_JSON --report REVIEW_JSON
uv run python -m app.product_knowledge.cli prices-source-publish --tenant eclair --source SOURCE_ID --actor-id ADMIN_ID --snapshot SOURCE_SNAPSHOT_JSON --expected-hash REVIEWED_HASH
```

Для имеющегося snapshot повторный collect не обязателен; preview повторно проверяет
текущий EOS scope. После отдельного разрешения production: backup/recovery →
совместимый API/worker + 0076 → preview/review → snapshot publish → company hourly
schedule с policy payload → read-only portal smoke. Этот отчёт не разрешает и
не выполняет эти write/deployment шаги.

## Проверки

- Полная backend suite с temporary WORK_REQUEST_UPLOAD_DIR: **1173 tests OK,
  40 optional PG tests skipped**. Первые два failures устранены: expected head
  обновлён до0076; repair upload перенаправлен env в scratch dir, код Repairs не менялся.
- Последний K3 reader/resolver/collector/refresh/scheduler/stale-revision прогон:
  **8 tests OK**. K1/K2/manual import и automation regression также прошли.
- Live новый collector/preview в памяти production: **OK**, 141 existing UUID,
  413 contexts, consistent revision, unit guard и live scope/review hash.
- Отдельный PostgreSQL 17.10: full upgrade **OK**; цикл 0075→0076→0075→0076 **OK**;
  concurrency retry/constraint test **1 OK**; populated downgrade отклонён и HEAD76
  сохранён. Upgrade SQL просмотрен. Production DB не использовалась для тестовых writes. Временный cluster остановлен
  и удалён после проверок.
- Frontend live + management: **2 tests OK**; production build **OK**, changed-file
  ESLint **OK**; существующий bundle warning сохранён. `git diff --check` **OK**.
- Browser/production UI acceptance не выполнялась; SCHEDULED Office controls
  не получены. Full K3/Gate K не закрыты.

## Файлы и Git

Backend implementation: `integrations/iiko/{client,prices}.py`,
`product_knowledge/{prices,price_refresh,price_resolver,service,cli}.py`,
`models/{product_knowledge,__init__}.py`, `schemas/{product_knowledge,automation}.py`,
`automation/{catalog,local_actions,schedules}.py`, Alembic 0076.
Tests: product knowledge/manual prices/price refresh/PG, automation catalog/API,
expected head в test_requests_api. Frontend: ProductKnowledgePage.tsx,
services/productKnowledge.ts и productKnowledgeLive.test.ts.
Docs: spec, architecture, roadmap K3 и этот отчёт; output K3 six artifacts.

Исходные 12 K3 файлов первого прохода сохранены и дополнены; история R0/K1/K2
не переписана. Ветка main сохранена; staging/commit/push/deployment отсутствуют.
Git status содержит только K3 implementation/docs/tests/artifacts. После отчёта
работа остановлена: ordinary real prices готовы к review/publication, SCHEDULED
limitation явно сохранён.


## Release review владельца — 09.10.2026

Обычные цены приняты к релизу. Добавлены индикаторы устаревания/ошибки с
сохранением даты успешного получения. Полный Gate K3 **не закрыт**; неизвестные
SCHEDULED-приоритеты по-прежнему fail closed. Финальный diff проверен, backend
1173 tests OK (40 optional skips), frontend 2 tests OK, changed-file ESLint и
production build OK (existing chunk-size warning). На изолированном PostgreSQL
17 проверены empty upgrade, 0075→0076→0075→0076, concurrency/idempotence,
health JSON query и отказ populated downgrade с сохранением head 0076.
Browser/production проверка после обновления остаётся оператору.

[Production runbook](STAGE_3_2_K3_PRODUCTION_RUNBOOK_2026-10-09.md) содержит
backup/restore check, миграцию, совместимое обновление трёх сервисов, preview,
публикацию принятого hash и включение hourly schedule после проверки.
Commit/push разрешены владельцем; deployment не выполняется.


Price payloads в `output/stage3_2_k3` остаются локальными release artifacts,
не входят в commit/push. Автоматическая approval-проверка отклонила их
публикацию на GitHub как внутренние production данные. Runbook предусматривает
прямую передачу оператором на production и проверку manifest; агент передачу
не выполнял. Репозиторий содержит реализацию, тесты и документацию.
