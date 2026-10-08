# EnterpriseOS — Roadmap Stage 3.2 v0.1.0

**Дата:** 08.10.2026 · **Статус:** предварительный план на review.
Общий этап остаётся PARTIAL по существующей основе Supply; новые слайсы ниже
не считаются реализованными. [Supply Roadmap](ROADMAP_STAGE_3_SUPPLY_v0.1.0.md)
содержит укрупнённую точку входа; здесь находится подробная последовательность 3.2.
[Спецификация](STAGE_3_2_PRODUCT_KNOWLEDGE_AND_PRODUCTION_SPEC.md),
[архитектура](STAGE_3_2_ARCHITECTURE.md),
[вопросы](STAGE_3_2_OPEN_QUESTIONS.md),
[разведка](STAGE_3_2_PRODUCTION_RECONNAISSANCE_PLAN.md) задают зависимости.

## 1. Последовательность и запрет параллельного производства

```text
Review документов
 → R0: отдельная read-only production reconnaissance
 → K1: минимальный каталог и карточка
 → K2: управление ассортиментом и история
 → K3: цены по точкам
 → K4: фото и локальные знания
 → K5: ТТК и проверка себестоимости
 → K6: повторная синхронизация и эксплуатационная приёмка
 → Gate K: база реализована и business-verified
 → P0: детализация производственной части
 → P1 → P2 → P3 → P4 (предварительно, после P0)
```

Все R/K/P ниже — предлагаемые слайсы, а не прежние обозначения 3.2A–3.2E.
После R0 границы K1–K6 уточняются по реальным контрактам и объёму данных.
Себестоимость/ТТК могут потребовать отдельных слайсов; их реализацию не объявлять
окончательно оценённой до разведки. Производственный код, даже «инфраструктура
на будущее», не разрабатывается параллельно K1–K6.

## 2. Общие проверки и deployment (T/D)

Эти правила относятся к будущей реализации; на текущем задании не выполняются.

**T — обязательные проверки слайса:** targeted backend tests; frontend tests для
изменённого поведения, production build и ESLint изменённых файлов; `git diff
--check` и полный review diff/status. Полный backend suite обязателен при models/
migrations, permissions, worker/outbox/callback/auth изменениях либо подготовке
deployment. Не исправлять посторонние baseline ESLint errors AuthContext.
Миграции: изолированный PostgreSQL upgrade/downgrade/upgrade с реальными FK,
unique/check, конкурентными транзакциями и существующим immutable audit trigger.
Browser/business smoke отдельно: mock tests не являются бизнес-приёмкой.

**D — порядок deployment:** отдельное разрешение → current HEAD/Alembic/status
preflight → verified backup + recovery path → build только затронутых services →
новая additive migration (если есть) → совместимые API/worker → ограниченный
ручной sync и проверки → frontend → browser/business acceptance → включение
нового расписания. Не останавливать и не пересоздавать persistent volumes.
Точный compose/image/feature-disable способ фиксируется в implementation plan
слайса по текущей инфраструктуре; этот документ не вводит инфраструктурные настройки.

**Rollback D:** выключить новое расписание/действие, дождаться/безопасно завершить
in-flight запуск, вернуть совместимые images; сохранить EOS статусы, дополнения,
историю и audit. Не откатывать данные к backup с потерей новых бизнес-изменений.
Downgrade только если доказана безопасность и отдельно разрешён; destructive
downgrade не штатный путь. Для каждого слайса сохранять проверенный runbook.

## 3. R0 — фактические контракты и решения

- **Цель/результат:** карта реальных возможностей iiko и годности данных, чтобы
  бизнес и разработка не основывались на предположениях.
- **Зависимости:** review пакета и отдельное задание на разведку.
- **Scope:** P01–P08 из плана; version/rights/catalog/prices/media/ТТК/cost/delta/load.
- **Backend/frontend:** код не меняется; используемые readers изучаются, новые
  проверки только по утверждённому allowlist. UI нет.
- **Миграции:** нет; никаких writes в EOS business tables или iiko.
- **Тесты/приёмка:** каждый endpoint получает доступность и evidence ID; заполненность
  посчитана по полному каталогу, спорные случаи перечислены; независимая сверка
  iikoOffice приложена либо явно missing. Ни 200, ни одинаковые API-ответы не
  заменяют business verification.
- **Deployment/rollback:** нет; прекращение read-запросов и закрытие API-сессии.
- **Бизнес-проверка:** владелец ассортимента и шеф подписывают набор изделий/
  примеры данных; закрываются Q03/Q07/Q08 и вопросы, необходимые K1.

## 4. K1 — первый рабочий каталог и карточка

- **Цель/результат:** пользователи находят подтверждённые изделия сети и открывают
  карточку; есть один внутренний продукт и стабильный UUID iiko.
- **Зависимости:** R0; решения Q01–Q03/Q07/Q08; начальная read/access политика.
- **Scope:** утверждённая классификация, initial staging/projection, минимальный
  профиль и компактная таблица семи колонок; отсутствующие цена/фото/cost честно
  обозначены. Показать вес/тип только если подтверждены. Первичную публикацию/
  назначение статуса решает Q01; production forms в этом слайсе отсутствуют.
- **Backend:** расширить existing iiko reader/DTO только подтверждёнными полями;
  согласованный current pointer/manifest, ID-only links, GET list/detail и field
  guards; safe errors/quality. Не менять Supplier/Sales contracts.
- **Frontend:** раздел «Продукция», таблица/поиск/фильтры/пагинация/карточка,
  существующие route/form/table patterns. Статус read-only до K2.
- **Миграции:** профиль и observation/projection — по Q07; потенциальное изменение
  name uniqueness только как согласованный целевой scope. No fake units/backfill.
- **Тесты:** T; повторный UUID, разные UUID с одинаковым именем, конфликт связей,
  отсутствующая единица, tenant isolation, missing fields, partial snapshot,
  A→B→A pointer; запрет сети в UI request path, скрытие sensitive fields.
- **Приёмка:** все утверждённые для пилота изделия видны без дублей; UUID/названия/
  единицы совпадают с evidence; неготовые source записи не публикуются молча;
  открытие карточки и поиск работают; нет нового раздела «Номенклатура».
- **Deployment:** D; API/schema → пилотный импорт/сверка → frontend; расписание
  массового импорта пока не включать. Rollback — отключить новые routes/action,
  вернуть совместимый код, сохранить импортированные данные.
- **Бизнес-проверка:** продавец и шеф находят репрезентативный набор, включая
  порционные/весовые и одинаковые имена; протокол расхождений.

**Рекомендация:** K1 — первый функциональный слайс после R0. Он приносит рабочую
таблицу и карточку, проверяет identity/классификацию и не зависит от недоказанного
денежного cost API. R0 — обязательный предварительный шаг, не разработка.

## 5. K2 — статус ассортимента и неизменяемая история

- **Цель/результат:** ассортимент управляется EOS и не теряется после resync.
- **Зависимости:** K1, Q01/Q02; Q13 для требований будущего production gate.
- **Scope:** два статуса, вывод/возврат с причиной, scoped история; без изменения
  iiko/Supply archive и без создания производственных заявок.
- **Backend:** transactional transition + AuditEvent/ActionContext,
  expected_version/idempotency, разрешённые действия и отдельная eligibility
  проверка для будущего production consumer; resync не пишет локальный статус.
- **Frontend:** dropdown, сохранение/disabled/error, причина, human-readable history.
- **Миграции:** только отсутствующие поля версии/статуса; не второй audit store.
- **Тесты:** T; concurrent status/sync, повтор команды, unauthorized/foreign tenant,
  out→resync→out→in, audit в той же транзакции, отсутствие вызовов iiko write,
  отсутствие физического удаления и изменений старых продаж.
- **Приёмка:** D02–D06 выполняются; два человека видят конфликт версии безопасно;
  audit сохраняется и не выдаёт seller стоимость/полную ТТК.
- **Deployment:** D; backend guard/audit → frontend; rollback скрывает действие,
  сохраняет статусы/audit. Производственная интеграционная проверка повторяется P1.
- **Бизнес-проверка:** владелец выводит контрольное изделие, запускает read-only
  sync EOS и возвращает в продажу; подтверждает неизменность iiko отдельно.

## 6. K3 — действующие цены по точкам

- **Цель/результат:** таблица показывает применимую цену, карточка — её контекст.
- **Зависимости:** K1–K2, P03/Q04 и подтверждённые department mappings.
- **Scope:** read-only price reader, dated price versions; не writeback и не маржа.
- **Backend:** provider/client/schema расширение, precedence после evidence,
  current price resolver по point/date/unit; null/conflict явно, no silent fallback.
- **Frontend:** точка/дата, компактная цена и сведения в карточке.
- **Миграции:** price versions с unique/context/interval constraints после R0.
- **Тесты:** T; different points, future/cancelled orders, boundary/timezone,
  no price, zero source price, overlapping conflicts, unit/currency, role scope.
- **Приёмка:** выбранная цена и дата совпадают с iikoOffice по каждой пилотной
  точке; цену нельзя получить по чужому scope или из среднего чека.
- **Deployment:** D; API/reader → ограниченная загрузка цен → independent сверка →
  UI → bounded schedule; rollback выключает prices action, сохраняет историю,
  показывает неизвестное/устаревшее вместо ошибочной цены.
- **Бизнес-проверка:** продавцы и управляющий сравнивают действующие и будущие цены.

## 7. K4 — фотографии и локальная база знаний

- **Цель/результат:** узнаваемые изделия и проверенная информация для продавцов.
- **Зависимости:** K3; P04/Q09, Q02/Q10. Если price API задерживается, изменение
  порядка K3/K4 допустимо только зафиксированным решением после R0, без части II.
- **Scope:** cache фото, характеристики/описание/состав/аллергены/хранение/учебные
  сведения по фактической доступности; без системы тестирования сотрудников.
- **Backend:** read-only images, защищённая выдача, limits/hash/version,
  local fields отдельно от source, audited edits и content responsibility.
- **Frontend:** фото в таблице, расширенные поля в карточке, формы разрешённых
  дополнений; no raw recipe for SELLER, keyboard/disabled states.
- **Миграции:** media metadata и недостающие local/provenance fields.
- **Тесты:** T; bad MIME/oversize/path traversal/SSRF, tenant/file access,
  missing/changed image, sync not overwriting local data, safe composition fields.
- **Приёмка:** фото соответствует изделию; нет iiko credential URL в браузере;
  отсутствующие аллергены не показывают «не содержит»; published content проверен.
- **Deployment:** D; проверить persistent media path/backup → API/cache → пилот →
  UI; rollback сохраняет local content и files, отключает downloader/edit controls.
- **Бизнес-проверка:** шеф подтверждает безопасный состав/хранение, продавец
  находит ответ в карточке; отсутствующие сведения занесены в реестр.

## 8. K5 — ТТК и независимое решение о себестоимости

- **Цель/результат:** прослеживаемая рецептура изделия и честный cost contract.
- **Зависимости:** K4; P05/Q06 и P06/Q05. Финальные границы зависят от R0.
- **Scope:** версии ТТК/история/tree/prepared, read-only chef card; денежные
  значения только при подтверждённом источнике, иначе missing + решение Q15.
  Расчёт производственных планов не включать.
- **Backend:** расширить reader/DTO, хранить output/unit/ingredient links и
  effective version; проверить циклы/конверсии, cost observations условно по Q05.
- **Frontend:** разрешённая технологическая карточка, dated cost/method/context;
  SELLER не получает денежный cost/полную рецептуру через API.
- **Миграции:** recipe versions; cost schema только после выбора метода.
- **Тесты:** T; dated/changed recipe, nested semifinished/cycles, incomplete
  ingredients/units, tree/prepared consistency, no procurement-cost substitution,
  sensitive fields/history/API isolation.
- **Приёмка:** пилотные ТТК сверены независимо с iikoOffice; все ошибки качества
  видны; cost либо подтверждён, либо явно отсутствует по решению владельца.
- **Deployment:** D; ограниченный batch → chef/accountant comparison → UI → schedule;
  rollback выключает readers/просмотр новых sections, сохраняет версии.
- **Бизнес-проверка:** шеф сверяет выход/ингредиенты/версию; бухгалтер или владелец
  подтверждает смысл денежного метода. Наличие endpoint не является приёмкой.

## 9. K6 — эксплуатационная проверка всей базы

- **Цель/результат:** база работает при повторных sync, сбоях и ежедневной работе.
- **Зависимости:** K1–K5, P07/P08/Q08/Q09; решения исключений зафиксированы.
- **Scope:** measured schedule, freshness/quality, recovery/current pointer,
  source disappearance, нагрузка и regression; не общий iiko redesign.
- **Backend:** новый automation action/catalog/schedule schema только в существующем
  Core; lease/retry/recovery и ограничения reader blocks. Delta только по P07.
- **Frontend:** безопасные freshness/error states и доступный ADMIN run outcome;
  ordinary UI без execution IDs/raw payload.
- **Миграции:** только доказанные недостающие operational fields/indices.
- **Тесты:** T и полный backend suite; timeout/401/403/429/5xx, partial reads,
  interrupted run/cursor recovery, concurrent runs, A→B→A, повтор callbacks
  если используется provider, regression Sales/Supply identity and permissions.
- **Приёмка:** утверждённые SLO и load budget P08 соблюдены; stale не выдаётся
  как fresh; локальный статус/контент переживают retries; восстановление проверено.
- **Deployment:** D; ручные bounded executions → наблюдение → enable schedule →
  business protocol. Rollback выключает только новый schedule/action,
  не затрагивает существующие sales/shift/supply automations.
- **Бизнес-проверка:** пользователи проходят полный список gate K ниже.

## 10. Gate K — разрешение перейти к проектированию реализации части II

Все условия подтверждаются отдельным протоколом; автоматического перехода нет:

- Утверждённое правило отбора, полный охват согласованного набора изделий;
  неразобранные записи перечислены, не скрыты. UUID/единицы не угадываются.
- Семь колонок, поиск/фильтры/карточка, цены по согласованным точкам/датам работают;
  отсутствующие фото/вес/тип имеют явно принятые исключения и ответственного.
- Статус EOS независим от iiko и Supply archive; вывод/возврат, resync,
  race/idempotency и audit прошли проверки без потери истории.
- Роли/fields/media/history защищены backend; продавец не получает full recipe/cost.
- ТТК и единицы пригодны для количественного расчёта репрезентативных изделий;
  непригодные изделия явно заблокированы для части II. Если пригодность не
  доказана, производство не начинается даже при хорошем каталоге.
- Себестоимость подтверждена либо Q15 имеет отдельное подписанное исключение
  с missing UI и запретом cost analytics. Никакого неявного исключения.
- Sync/freshness/recovery и rollback проверены; targeted/full required checks
  пройдены, browser smoke и независимая iikoOffice сверка зафиксированы.
- Владелец ассортимента, шеф и представители розницы приняли базу;
  блокирующие Q закрыты, остатки имеют owner/date. Владелец явно разрешил часть II.

## 11. Часть II — предварительные блоки после gate K

Окончательные статусы/API/migrations/formulas утверждает P0. Следующая таблица
описывает целевой объём, не разрешает начать его сейчас. Для всех P1–P4 применяются
T/D; после models/permissions/migrations — full backend и isolated PostgreSQL.

| Слайс | Цель и scope / зависимости | Backend / frontend / миграции | Проверки и критерий приёмки | Deployment / бизнес-проверка |
|---|---|---|---|---|
| P0 — согласование производства | Уточнить Q11–Q14, формы заявок, прогноз, остатки/поставки, версии/утверждение и факт; зависит от gate K | Только детальная спецификация и contracts review; миграций нет | Реальные примеры от продавца/шефа/Supply, ответственность и формулы утверждены, источники доказаны | Deployment нет; совместный разбор примера «точка → выпуск → сырьё → закупка» |
| P1 — рекомендация и заявки точек | Продажи EOS DB, объяснимый прогноз, подтверждённая заявка своей точки; зависит от P0 и Q11/Q12 | Reuse reconciled sales/completeness, новый demand snapshot/versions по решению P0; UI предложения/количества/причины; additive migrations вероятны | Неполные данные блокируют/маркируют прогноз по правилу; out-of-sale не проходит create/confirm, draft не меняет confirm, роль/точка/window защищены, повтор confirm идемпотентен | D: API/guards → пилот одной точки → UI → window schedule; rollback выключает только production window. Продавец сверяет рекомендацию и confirm→draft→close |
| P2 — план и шеф | Консолидация, пригодные остатки/ожидаемые поставки, версия плана, ТТК-расчёт и chef confirmation; зависит от P1 и Q06/Q13 | EOS calculation service с snapshots/версией алгоритма и ТТК, transactional approvals, UI шефа с diff/reasons; additive models/migrations | Единицы/выход/потери согласованы, нет двойного покрытия, неизвестный компонент блокирует confirm, concurrent corrections/version conflict безопасны | D: расчёт/guards → контрольный пример → UI шефа; rollback запрещает новые approvals, сохраняет утверждённые планы. Шеф вручную пересчитывает сырьё для набора изделий |
| P3 — Supply adapter | Только утверждённый дефицит сырья в canonical needs; зависит от P2/Q14 | Расширить source contract/FK/constraints существующего Supply либо утверждённый genuine request path; reuse collector/reservation, UI traceability; migration вероятна | Same plan/version не даёт дубль, пересмотр учитывает reserved quantities, confirmed→need→PurchaseRequest прослеживается; нет ложного REQUEST_LINE | D: schema/API adapter → dry preview → однократный пилот → Supply UI; rollback выключает новые handoffs, существующие needs/orders сохраняются. Шеф и снабжение сверяют один дефицит до закупки |
| P4 — план/факт | Выпуск/списание и причины отклонений; зависит от P3 и подтверждённого Q14 source | Read-only факт/аудируемый ручной ввод по решению P0, immutable revisions, comparison service, UI; migrations по контракту | Продажи не подменяют выпуск, fact version/unit/date подтверждены, correction append-only, old approved basis сохранён; ТТК автоматически не меняется | D: source/guards → независимая сверка → UI; rollback выключает new ingest, хранит факт/историю. Шеф/производство сравнивают сменный выпуск и списание с iikoOffice или согласованным первичным документом |

## 12. Результат текущего документационного задания

Готовность документации не меняет статус реализации слайсов. Разведка не
выполнена, source contracts не подтверждены, deployment не разрешён. После
review следующий шаг — отдельное задание R0, затем уточнение K1 implementation plan.
