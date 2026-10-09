# Stage 3.2 / K5B — интеграция технологических карт iiko

Дата: **09.10.2026**, Asia/Yekaterinburg. **Локальная реализация на review**.
K5A принят владельцем в задании. Основа — [отчёт K5A](STAGE_3_2_K5A_REPORT_2026-10-09.md)
и его [evidence](evidence/STAGE_3_2_K5A_2026-10-09.json). Предшествующие
датированные статусы не переписаны. Commit, push, deployment не выполнены.

## Результат и границы

Реализован backend-контур для existing EOS product knowledge UUID, с bounded
пилотом и последующим явным batch до 141 изделий. Новые изделия/сырьё в каталоге
или Supply не создаются. K0–K4 source/local fields, цены, фотографии, Sales и
Supply business logic не изменяются. Frontend не изменён.

Нормы/выход/технологические тексты/фильтры и исходные интервалы версий сохраняются
из iiko дословно. Decimal парсится непосредственно из JSON number и сохраняется
точной строкой в JSON; float и округление до фиксированных знаков отсутствуют.
`amountIn/Middle/Out` остаются в mainUnit ингредиента; act-development поля,
outputComment, unitWeight, package и размерные коэффициенты не подменяют нормы.
Денежная себестоимость и производственные/сырьевые расчёты не реализованы.
Из reference products сохраняется allowlist без price/cost полей.

**Не выполнено:** live-пилот на реальных EOS UUID и первичная загрузка всех 141
изделий. Локальный пилот использует synthetic fixtures с вложенной картой,
границей версии 31.05/01.06, малыми Decimal и неполными ответами. Это проверка
реализации, не повторный K5A live audit и не независимая iikoOffice приёмка.
Псевдонимы `key:…` из evidence не используются как UUID или mapping.

## Чтение источника и Automation Core

`IikoServerClient.get_recipe_charts` использует подтверждённые K5A read endpoints:
getTree, getAssembled, getPrepared, getHistory; byId доступен для адресного
исторического чтения, штатный batch его не вызывает. Read-only reference requests:
products/list (UUID batches ≤50, includeDeleted), MeasureUnit, productScales
(≤50 UUID). История запрашивается также для вложенных изделий, кэшируется внутри
одного collection; справочники покрывают текущие и исторические ingredient UUID.

Используются существующие auth, TLS, timeout/retry, request lock и logout.
Запросы внутри клиента последовательные. Ответ ограничен 16 MiB, root batch —
141, дерево/история на изделие — 200 карт, dependency/reference UUID — 2000.
getAll/delta cursor не внедряются: K5A не подтвердил реальные update/deletion
события delta, и rolling date baseline не подменяется cursor предыдущей даты.

Новый **TECHNICAL_ADMIN-only** endpoint `POST /products/recipes/refresh` возвращает
202 («поставлено в очередь») и создаёт existing execution + transactional outbox,
без внешнего I/O в request path. Action: `products.sync_iiko_recipes`.
Existing local worker выполняет collection вне DB connection; после I/O проверяет
владение claim, terminal execution guard и неизменность source/catalog scope.
Запись observations/versions/audit и terminal success — одна транзакция.
Результат содержит counts по качеству, observation IDs для технической проверки
и `ready_for_production=false`. Success означает завершённое наблюдение, а не
готовую ТТК. Expected API-конфликты переведены в безопасную русскую ошибку.

Первый запрос допускает ≤5 source product UUID. Для batch 6–141 требуется
`pilot_observation_id` того же tenant/source/department со статусом UNCONFIRMED
(структурно полный). Это намеренное ручное расширение collection, **не** разрешение
на производство и не закрытие Gate K. Source_id проверяется с current settings
и existing source row; root identity — только tenant/source/iiko UUID.

Schedule не создаётся, action не добавлен в каталог регламентов; schedule contract
отклоняет его. Повторные обновления запускаются тем же endpoint вручную.
Новые scheduler, outbox, retry, callback или n8n workflows не создаются.
Глобальная сериализация нескольких API-сессий разных worker не добавлена;
подтверждена existing последовательность внутри клиента.

## Хранение, версия и качество

Миграция **20261009_0078**, parent **20261009_0077**, добавляет только:

- `product_recipe_versions`: tenant/source/chart UUID/kind/content hash + original
  payload. SOURCE и PREPARED — разные виды; исправление под тем же UUID создаёт
  новую EOS content version. Source dateFrom/dateTo, включая sentinel/null,
  остаются в payload; EOS не изобретает конец интервала.
- `product_recipe_observations`: existing EOS product FK, source FK, execution,
  effective_on, observed_at, status и report. Report содержит раздельные source
  responses, references, зависимости и manifest ролей TREE/ASSEMBLED/HISTORY/PREPARED
  с EOS version UUID и content hashes. Manifest hash учитывает source scope,
  references/units/packages/scales и зависимости данного root, а не других изделий batch.

Обе таблицы append-only через PostgreSQL triggers: UPDATE/DELETE запрещены.
Downgrade отказывается удалять заполненную историю. Source row lock сериализует
publication cooperating writers; unique execution/product и content constraints
обеспечивают идемпотентность. Новое execution создаёт новое observation даже при
неизменном source content. Старые версии, observations и manifests сохраняются.
Пустой ответ следующего observation не удаляет предыдущие карты.

Разрешены только **INCOMPLETE / CONFLICT / UNCONFIRMED**, без READY.
Проверяются отсутствующие проекции, ingredient/unit resolution, mainUnit root
против unchanged EOS identity, даты `[from,to)`, неположительная база,
нечисловые/отрицательные нормы, неоднозначная версия, history/tree/assembled и
tree/prepared consistency, cycles и недостижимые узлы. Cycle guard различает
цикл пути и общую заготовку в разных ветках. Missing карты у GOODS не заменяются
ручным рецептом. Неполные успешные envelopes сохраняются как наблюдения с issues;
невалидный JSON/envelope или HTTP error завершает попытку через existing retry,
без частичной записи batch. Техническая история ошибки остаётся в Automation Core.

Department UUID — явный source scope. Warehouse/size UUID nullable и сохраняются
как заявленный контекст; их отсутствие не заполняется именами, торговой точкой
или guessed mapping. StoreSpecification null, пустой список и inverse не
нормализуются друг в друга. SPECIFIC/non-null size specification остаются
INCOMPLETE: подтверждённого non-null size resolver в K5A нет. При нескольких
действующих scoped history rows resolver fail closed, без выбора «первой».
Все observations имеют OFFICE_ACCEPTANCE_PENDING и PRODUCTION_STORE_UNCONFIRMED.
DIRECT не разворачивается EOS в списание или сырьевую потребность; prepared
сохраняется как projection iiko, а не как EOS производственное дерево расчёта.

## Файлы

- Reader: `backend/api/app/integrations/iiko/recipes.py`, method в `client.py`.
- Модели: `backend/api/app/models/product_recipe.py`, регистрация в `models/__init__.py`.
- Collection/publication/guards: `backend/api/app/product_knowledge/recipes.py`.
- Manual endpoint: `backend/api/app/api/routes/product_knowledge.py`.
- Existing seams: `backend/api/app/automation/local_actions.py`, `app/schemas/automation.py`.
- Миграция: `backend/api/alembic/versions/20261009_0078_product_recipes.py`.
- Тесты: `backend/api/tests/test_product_recipes.py`, `test_product_recipes_postgres.py`;
  single-head assertion в `test_requests_api.py` обновлён на 0078.
- Документация: данный отчёт, K5B evidence, подробная Roadmap 3.2 и Supply roadmap.

## Проверки

- 17 профильных local tests: PASS. Decimal parse/roundtrip, nested cycle/shared
  dependency, version date boundary и actual observation transition, missing
  units/projections/base/nested/scales, overlap, same-UUID correction, root unit
  conflict, audit rollback, idempotency, collector source scope, отсутствие денег,
  неизвестный root UUID, forbidden role и manual-only schedule contract.
- 2 профильных PostgreSQL tests: PASS на disposable PostgreSQL 17.10,
  localhost:55439 / eos_supply_migration_test. Concurrent retry, precision JSON
  roundtrip, immutable UPDATE/DELETE, downgrade populated guard, manual enqueue →
  worker finalization, повторный потерянный claim. Worker iiko I/O mocked; outbox
  claim выставлен fixture — не отдельная проверка claim_next алгоритма.
- Alembic empty cycle `0077 → 0078 → 0077 → 0078`: PASS на той же изолированной БД;
  новый кластер первоначально мигрирован от base. Production DB не используется.
- Full backend suite: **1216 tests, OK, skipped=44** (125.730 s).
  После последнего tightening prepared/unit validation повторно прошли
  17 local + 2 PostgreSQL профильных tests.
  Первое прохождение выявило только outdated single-head assertion (0077 вместо
  новой 0078); assertion исправлен в рамках миграции.
- Frontend tests/build/ESLint: не требуются, frontend не изменён.
- `git diff --check`: PASS; новые файлы дополнительно проверены на whitespace.
- Временный PostgreSQL остановлен; disposable кластер/БД удалены.
- Git: текущая ветка `main` сохранена, branch/stage/commit/push не выполнялись.
  Task changes: 8 modified tracked + 8 new files; ранее untracked K5A report
  и evidence сохранены без изменений.

## Runbook после review

1. Перед любым production migration — отдельная авторизация, backup и проверенный
   recovery path. Этот проход production migration не выполняет.
2. Определить реальные existing source product UUID пилота, source_id,
   source Department UUID, effective_on и подтверждение scope. Использовать
   реальные EOS mappings/данные источника; не псевдонимы K5A evidence.
3. TECHNICAL_ADMIN отправляет JSON в `/products/recipes/refresh`:
   `source_id`, `product_ids` (1–5 UUID), `department_id`, `effective_on`,
   `scope_evidence`; `warehouse_id`/`size_id` только если известны, иначе null.
4. Проверить execution outcome и observations в технической истории/БД: отдельно
   current SOURCE, история, dependency manifest, единицы и PREPARED. Сверить пилот
   независимо с iikoOffice, включая nested recipe и обе стороны смены версии.
5. Повторить ручной запуск, проверить новый observation и reuse content versions;
   проверить случаи отсутствия ТТК, неизвестного размера, DIRECT и store filters.
6. Только после review пилота явно расширить batch со ссылкой на его observation
   и зафиксировать coverage 141 UUID. 13 GOODS без карты — INCOMPLETE, без угадывания.
   Не интерпретировать UNCONFIRMED как разрешение производства.

Rollback операции — прекратить новые ручные запуски и не использовать новые
observations. История не удаляется. Денежный источник K5C, полный защищённый UI
K5D, business verification Q06, K6/Gate K и P0–P4 остаются отдельными шагами.

## Следующий запрос — подготовка production release

Отдельный проход после локального review: [release review](STAGE_3_2_K5B_RELEASE_REVIEW_2026-10-09.md)
и [Windows runbook](STAGE_3_2_K5B_PRODUCTION_RUNBOOK_2026-10-09.md).
Предыдущие результаты выше сохранены как датированная локальная проверка.
Новый проход готовит commit/push и ограниченный пилот; deployment/live outcomes
и независимая Office acceptance не объявляются выполненными.
