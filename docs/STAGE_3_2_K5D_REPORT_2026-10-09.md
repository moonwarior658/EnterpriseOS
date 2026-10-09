# Stage 3.2 / K5D — интерфейс технологических карт

> Исходный implementation review ниже сохранён как исторический snapshot.
> Отдельная подготовка release описана в последнем разделе.

09.10.2026, Asia/Yekaterinburg. **Локальная реализация на review. Без commit, push и deployment.**

## Основа и границы

По сообщению владельца K5B развёрнут на production; первый live-run сохранил три
ТТК: две UNCONFIRMED и одну INCOMPLETE. Это owner-reported факт. В рамках K5D
нет подключения к production, повторной live-загрузки или проверки iikoOffice.
Используются существующие K5B ProductRecipeVersion / ProductRecipeObservation,
source UUID и Automation Core. Второй справочник изделий не создаётся.

Карточка ТТК встроена в существующий `/products/:productId`. Цены, фотографии,
ассортимент, Sales, Supply, monetary cost и производственные расчёты не изменяются.
Новый UI не пишет в iiko и не включает расписания или массовую загрузку.

## Реализовано

- Исходные ингредиенты: брутто `amountIn`, нетто `amountMiddle`, выход `amountOut`,
  единица из source product `mainUnit`; выход карты `assembledAmount` отображается
  отдельно как база норм. Decimal остаётся строкой, без float, округления или
  подмены нулевого значения альтернативной нормой. Неизвестные данные явно отсутствуют.
- Раскрываемые nested SOURCE/TREE полуфабрикаты; циклы, неоднозначность и глубина
  защищены. Нормы вложенного полуфабриката показываются на **его** исходный выход,
  без умножения на потребность родителя: производственного расчёта здесь нет.
- PREPARED/writeoff — отдельная раскрываемая проекция с колонкой «Списание»;
  не подставляется вместо брутто/нетто/выхода. Отдельная история версий iiko.
- Версия EOS, исходный период действия (exclusive dateTo), выбранная дата рецептуры,
  последнее получение, страничная история наблюдений с переходом к старым нормам.
  Неизвестный dateTo отличён от явно полученного null. История не удаляется.
- Русские статусы «Требует проверки», «Неполные данные», «Конфликт» и причины
  качества. Технологический текст выводится обычным текстом с защитой от HTML/XSS.
- Контекст подразделения выбирается **только из наблюдений того же tenant/source**;
  human label использует explicit `olap_department_id → EOS Department` mapping,
  а не имя или подстановку другого iiko ID. Контексты источника используются и
  для первичной загрузки отдельного existing изделия. Неизвестные склад/размер
  остаются неизвестными. При отсутствии подтверждённого контекста обновление заблокировано.
- Кнопка «Обновить из iiko»: явная дата, одно existing source UUID, existing
  enqueue/outbox/worker/retry; статусы ожидания, начала, выполнения, повторной попытки,
  успеха/ошибки/timeout/cancel. Нет сетевого iiko I/O в HTTP request path.
  UI poll каждые 2.5 s работает только при активном execution, останавливается
  после terminal/error/unmount; ранее сохранённое наблюдение доступно при ошибке.
  При смене selection старые нормы не показываются под новым контекстом.

## Разрешения и подтверждение

Добавлены независимые backend capabilities `PRODUCT_RECIPE_READ`,
`PRODUCT_RECIPE_CONFIRM`, `PRODUCT_RECIPE_REFRESH`. Первоначальный allowlist каждой:
ADMIN, HEAD_OF_PRODUCTION, CHEF_CONFECTIONER. Existing Human/active employee/roles
и production department context guards сохранены. Остальным ролям, в том числе
SELLER, DIRECTOR, NETWORK_MANAGER, CONFECTIONER и BAKER, защищённые routes отвечают
403. Чтение public карточки не возвращает нормы/technology/raw manifest; additive
`recipe_access` показывает доступность раздела. UI flag не заменяет backend guard.

Подтверждение — **сверка конкретного SOURCE/TREE/PREPARED snapshot с iikoOffice**.
Нужны явная отметка сверки и содержательный результат/evidence. Автор, employee,
дата, observation ID, manifest hash, все version IDs, source/context и evidence
фиксируются в existing immutable AuditEvent. Observation/Version не меняются.

Разрешено только последнее UNCONFIRMED наблюдение выбранного контекста. INCOMPLETE,
CONFLICT, удалённое изделие, неверный hash, чужое наблюдение, устаревшая версия и
активное обновление блокируют подтверждение. Новый observation не наследует старое
подтверждение даже при тех же version IDs; старый автор/сверка видны в истории.
Checkbox связан с observation ID: новая версия требует нового явного подтверждения.

Подтверждение исходной версии **не означает допуск к производству**. K5B quality
остаётся неизменной; UI отдельно показывает подтверждение сотрудника. Неизвестные
warehouse/size/technology constraints остаются блокирующими; `ready_for_production`
всегда false. Gate K / количественные расчёты / массовая business acceptance не закрыты.

## API / транзакции / БД

- `GET /products/{id}/recipes`: защищённая allowlisted DTO, context selection,
  selected observation, history offset/limit (20 по умолчанию, максимум 100),
  server allowed_actions и безопасная проекция состояния Automation Core.
- `POST /products/{id}/recipes/confirm`: observation_id, manifest_hash,
  office_evidence; возвращает защищённую карточку.
- `POST /products/{id}/recipes/refresh`: context_key, effective_on, request_id;
  202 означает получение команды, результат определяется terminal execution.
- Старый технический `POST /products/recipes/refresh` сохранён без изменения
  контракта и ADMIN authorization. Enqueue service переиспользуется.
- Tenant/product/source filters обязательны; DTO не возвращает raw source_responses,
  execution IDs, provider/error_message, outbox, цены или неожиданные source поля.
  GET и команды имеют Cache-Control no-store.
- Publication / confirmation / refresh используют существующую source row lock.
  Двойное подтверждение создаёт одну immutable запись, повтор request_id — тот же
  execution; повтор request_id с другой командой отклоняется. Активный запуск
  того же product/context/date переиспользуется, другая дата блокируется до завершения.
  Потеря ответа не должна запускать второй outbox. Terminal states не изменяются.
- Контексты выбираются через DISTINCT scope fields, history pagination и current
  observation — в БД; все старые raw ТТК не загружаются в память при каждом poll.
- **Новых моделей/миграций нет**, head остаётся `20261009_0078`. Existing audit
  достаточен для version-specific immutable подтверждения. Чистый schema upgrade
  не является частью K5D.

## Проверки

- 8 новых backend tests: все 13 ролей, safe reads/no-store, nested/Decimal/history,
  confirmation/idempotence/new version, incomplete/conflict/stale/hash guards,
  unknown context/cross tenant/product/SERVICE account, single existing product,
  rollback после enqueue failure и безопасный terminal progress.
- 2 новых isolated PostgreSQL tests: concurrent confirmation/refresh и гонка
  publication → stale confirmation. Вместе с 3 K5B PostgreSQL tests: **5 PASS**.
  Временный PostgreSQL 17.10, disposable localhost DB, миграция existing head;
  production не использовался. Временный cluster остановлен и данные удалены.
- Full backend suite: итог и hash лога в [evidence](evidence/STAGE_3_2_K5D_2026-10-09.json).
  Для repair upload используется временный WORK_REQUEST_UPLOAD_DIR; optional PG
  tests в общем запуске skipped, профильные PG проверки выполнены отдельно.
- Frontend full suite: **210 PASS**. После финальной selection правки 4 профильных
  UI tests повторно PASS. JSDOM: Decimal, SOURCE/nested/PREPARED/history, XSS,
  approval, double click, Core polling, failed load/retry и stale selection.
- `npm run build` PASS; ESLint изменённых TS/TSX и нового test PASS.
  Existing Vite bundle-size warning сохранён; вне scope.
- `git diff --check` и проверка whitespace новых файлов PASS.
- Настоящий browser/visual review не выполнен: CUA не обнаружил доступных browsers.
  Temporary Vite/fixture page остановлены/удалены. JSDOM не является visual acceptance.

## Review и будущая бизнес-приёмка

1. После отдельного deployment решения открыть три live K5B изделия под шефом:
   нормы/единицы/выход совпадают с сохранённым source DTO; nested раскрываются,
   PREPARED отделён, SPECIFIC/null показывает «Неполные данные» и нет confirm.
2. Под SELLER и остальными исключёнными ролями ТТК не видна; прямые GET/POST
   защищённых routes также запрещены. Catalog/photo/price/Supply поведение прежнее.
3. Шеф сверяет **то же** изделие/source UUID, department, дату, склад/размер,
   каждую норму, единицу, nested версии и технологию с iikoOffice. Фиксирует
   результат проверки. API-vs-API не заменяет независимую сверку.
4. На структурно полной карте подтвердить исходную версию; автор/дата/версия
   видны. Производственный допуск не появляется. Обновить одно изделие вручную:
   UI показывает движение execution, repeat не дублирует запуск, новая observation
   не наследует confirm, старые нормы/автор сохраняются в истории.
5. Проверить desktop/mobile layout, горизонтальную прокрутку, keyboard navigation,
   error/empty/loading, исторические даты и missing technology на реальном браузере.

## Файлы и handoff

Backend: `core/authorization.py`, `product_knowledge/recipes.py`, новый
`product_knowledge/recipe_portal.py`, `product_knowledge/service.py`,
`api/routes/product_knowledge.py`, `schemas/product_knowledge.py`, новый
`schemas/product_recipes.py`, новые `test_product_recipe_portal.py` и
`test_product_recipe_portal_postgres.py`.

Frontend: `ProductKnowledgePage.tsx`, `services/productKnowledge.ts`, новые
`services/productRecipes.ts`, `productKnowledge/ProductRecipes.tsx/.css`,
`tests/productRecipes.test.ts`. Документы: этот отчёт/evidence, две roadmap.

HEAD остаётся release K5B `a254d75c51fbf7a3eb2210c8b59016cc414e66f1`.
Изменения K5D unstaged; исходные два untracked K5A файла сохранены без изменений.
**Commit, push и deployment не выполнялись. Остановка на review.**

## Подготовка release — следующий проход 09.10.2026

Владелец отдельно разрешил commit/push только K5D в origin/main; production
по-прежнему запрещён. Финальный diff проверен; 18 исходных task files совпадают
с SHA-256 прошедшей тесты реализации, test log hashes подтверждены. Source models
и Alembic не изменены: head 0078, новая migration не нужна. Добавлен
[короткий Windows runbook](STAGE_3_2_K5D_RELEASE_RUNBOOK_2026-10-09.md).
Release package — 20 файлов K5D, без двух исходных untracked K5A файлов.
Точный SHA передаётся после commit/push и проверки remote ref. Эта запись
не подтверждает deployment, visual/business acceptance или новый live-run.
