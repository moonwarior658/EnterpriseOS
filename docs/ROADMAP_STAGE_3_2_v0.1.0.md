# EnterpriseOS — Roadmap Stage 3.2 v0.1.0

**Актуализация:** 09.10.2026 · **Статус:** K1 развёрнут, 141 позиция загружена
по подтверждению владельца; K2 реализован локально и передан на review.
K2 production deployment и browser/business acceptance не выполнялись.
Общий этап остаётся PARTIAL по существующей основе Supply; новые слайсы ниже
не считаются принятыми. K0 не завершает gate K. [Supply Roadmap](ROADMAP_STAGE_3_SUPPLY_v0.1.0.md)
содержит укрупнённую точку входа; здесь находится подробная последовательность 3.2.
[Спецификация](STAGE_3_2_PRODUCT_KNOWLEDGE_AND_PRODUCTION_SPEC.md),
[архитектура](STAGE_3_2_ARCHITECTURE.md),
[вопросы](STAGE_3_2_OPEN_QUESTIONS.md),
[разведка](STAGE_3_2_PRODUCTION_RECONNAISSANCE_PLAN.md) задают зависимости.

## 1. Последовательность и запрет параллельного производства

```text
Review документов
 → R0: read-only production reconnaissance (отчёт подготовлен)
 → K0: портал «Продукция» на изолированных демоданных → review владельца
 → K1: контролируемое наполнение по сентябрьским продажам EOS
 → Подключение хранения и интеграций по согласованным контрактам K1–K6
 → K2: управление ассортиментом и история
 → K3: цены по точкам
 → K4: фото и локальные знания
 → K5: ТТК и проверка себестоимости
 → K6: повторная синхронизация и эксплуатационная приёмка
 → Gate K: база реализована и business-verified
 → P0: детализация производственной части
 → P1 → P2 → P3 → P4 (предварительно, после P0)
```

R0 выполнен; K0 сохранён как dev demo; K1 развёрнут по подтверждению владельца;
K2 развёрнут по подтверждению владельца от 09.10.2026. K3 обычные real prices
и regular action приняты владельцем к релизу; SCHEDULED precedence
и browser acceptance остаются непроверенными. K4–K6 и P ниже —
предлагаемые слайсы, а не прежние обозначения 3.2A–3.2E.
После R0 границы K1–K6 уточняются по реальным контрактам и объёму данных.
Себестоимость/ТТК могут потребовать отдельных слайсов; их реализацию не объявлять
окончательно оценённой до закрытия соответствующих вопросов R0. Производственный код, даже «инфраструктура
на будущее», не разрабатывается параллельно K1–K6.

## 2. Общие проверки и deployment (T/D)

T применяется к текущему K0 в части frontend. D требует отдельного разрешения;
в K0 deployment, backend-изменения и миграции не выполняются.

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

## 3a. K0 — портал «Продукция» до наполнения базы

- **Scope:** основной пункт меню `/products`, семь колонок в согласованном порядке,
  поиск по названию/артикулу, фильтры, точка/дата цены, пагинация и карточка с разделами
  базы знаний. Только изолированные вымышленные данные; Supply не используется.
- **Управление:** формы добавления, редактирования, фото и статуса предусмотрены;
  неподключённое сохранение/загрузка/удаление явно недоступны. Нет localStorage,
  реального сохранения, iiko-вызовов, миграций или изменений Supply.
- **Проверки:** frontend-тесты, build, lint изменённых файлов и `git diff --check`;
  снимки таблицы/карточки и проверка адаптивности. Общий lint имеет существующие
  ошибки AuthContext, которые остаются вне scope K0.
- **Локальное открытие:** `cd frontend && npm run dev -- --host 127.0.0.1`, затем
  `http://127.0.0.1:5173/dev/products`. Dev-route доступен без backend только в
  dev-режиме; `/products` остаётся внутри обычной авторизации EOS.
- **Приёмка:** визуальная и функциональная проверка владельцем. Локальная реализация
  и автоматические проверки не означают приёмку. После review остановиться.

### Следующий слайс — наполнение по сентябрьским продажам

После приёмки K0 определить согласованный период сентября 2026 и проверить полноту
продаж в EOS DB. По подтверждённым product/iiko IDs подготовить кандидатов
ассортимента; продажи не назначают автоматически статус, класс или связь по имени.
Владелец подтверждает набор изделий и решения Q01/Q02/Q03/Q07. Чтение данных,
хранение и загрузка потребуют отдельного задания; текущий K0 их не выполняет.
Следом подключаются цены, фото, знания, ТТК и эксплуатационная синхронизация.
Производство начинается только после отдельной бизнес-приёмки базы и gate K.

## 4. K1 — наполнение каталога по сентябрьским продажам

- **Цель/результат:** пользователи находят подтверждённые изделия сети и открывают
  карточку; есть один внутренний продукт и стабильный UUID iiko.
- **Зависимости:** review K0, R0, полнота согласованного сентября 2026 в EOS DB;
  решения Q01–Q03/Q07/Q08; начальная read/access политика.
- **Scope:** подтверждённый владельцем набор кандидатов по сентябрьским продажам
  EOS DB с ID-only связями, утверждённая классификация и минимальный профиль и компактная таблица семи колонок; отсутствующие цена/фото/cost честно
  обозначены. Показать вес/тип только если подтверждены. Первичную публикацию/
  назначение статуса решает Q01; production forms в этом слайсе отсутствуют.
- **Backend:** использовать существующие продажи EOS DB для согласованного
  сентябрьского набора, ID-only links, GET list/detail и field guards; missing
  metadata не угадывать. После наполнения отдельно подключить existing iiko
  reader/DTO, staging/projection и current pointer/manifest по подтверждённым
  контрактам. Не менять Supplier/Sales contracts.
- **Frontend:** подключить принятый портал K0 к EOS API; поиск/фильтры/пагинация
  переходят на backend. Демо не смешивается с реальными записями. Статус read-only до K2.
- **Миграции:** профиль — по Q07; observation/projection относится к последующему
  подключению источника. Потенциальное изменение
  name uniqueness только как согласованный целевой scope. No fake units/backfill.
- **Тесты:** T; повторный UUID, разные UUID с одинаковым именем, конфликт связей,
  отсутствующая единица, tenant isolation, missing fields, partial snapshot,
  A→B→A pointer; запрет сети в UI request path, скрытие sensitive fields.
- **Приёмка:** все утверждённые для пилота изделия видны без дублей; UUID/названия/
  единицы совпадают с evidence; неготовые source записи не публикуются молча;
  открытие карточки и поиск работают; нет нового раздела «Номенклатура».
- **Deployment:** D; API/schema → контролируемое наполнение из согласованной
  сентябрьской выборки EOS → сверка → frontend; импорт iiko и его расписание
  подключаются отдельно после наполнения. Rollback — отключить новые routes/action,
  вернуть совместимый код, сохранить импортированные данные.
- **Бизнес-проверка:** продавец и шеф находят репрезентативный набор, включая
  порционные/весовые и одинаковые имена; протокол расхождений.

**Текущий порядок:** сначала визуальная и функциональная приёмка портала K0,
затем контролируемое наполнение по сентябрьским продажам, далее интеграции K1–K6.
Денежный cost API не является условием разработки K0; его подтверждение или
явное исключение Q15 остаётся условием приёмки базы. R0 не является разработкой.

## 5. K2 — управление продукцией EOS и локальная история

**CURRENT 09.10.2026:** реализован локально; deployment и бизнес-приёмка pending.
Текущий запрос расширяет прежний K2 текстовыми полями из K4. Это явное решение
владельца; фото/цены/ТТК/производство в scope не добавлены.

- Редактирование названия/категории/описания/характеристик/состава/аллергенов/
  хранения/материалов, два EOS статуса, отдельное удаление/восстановление.
- Ручное добавление только через выбор конкретного UUID iiko и повторную проверку
  checksum; повторное добавление восстанавливает ту же identity и историю.
- Проверка сотрудником/дата, unverified filter, progress рабочего каталога;
  изменения снимают отметку. Scoped human-readable AuditEvent history.
- Backend grants строго по текущей матрице; ActionContext, tenant guards,
  expected_version/FOR UPDATE, retry без duplicate audit; локальные поля отдельно от source.
- Additive 0075 сохраняет опубликованную K1 batch, Sales/Supply и iiko. Soft deletion
  не меняет OFF_SALE/published. Production eligibility guard исключает deleted и OFF_SALE.
- Проверки: full backend suite, K1/K2 PostgreSQL migration cycle/constraints/
  concurrency/audit, frontend interaction tests/build/changed-file ESLint/diff check;
  результаты и оставшиеся review checks — [отчёт K2](STAGE_3_2_K2_REPORT_2026-10-09.md).
- Production handoff: current preflight/verified backup → upgrade 0075 → совместимый
  backend → frontend → smoke всех ролей и CRUD на контрольном UUID. Старый backend
  при rollback допускается только с закрытым `/products`, иначе проигнорирует deleted_at.
  Downgrade с K2 данными запрещён; статусы/контент/audit сохраняются.
- После review остановиться. K3 начинается по отдельному заданию; gate K остаётся открытым.

## 6. K3 — действующие цены по точкам

**09.10.2026: PARTIAL / ordinary prices приняты к релизу.** Read-only
collector повторно получил 413 contexts для 141 EOS UUID. 363 цены, 50 exclusions,
10 missing; валюта/контрольные единицы/цены подтверждены владельцем. Source snapshots,
review hash/audit/retry, date resolver и existing scheduler/outbox regular action
реализованы локально. SCHEDULED/date-only ambiguity fail closed; приоритеты
пересекающихся расписаний без Office evidence не реализуются. [Отчёт K3](STAGE_3_2_K3_REPORT_2026-10-09.md).
Deployment/publication/schedule enabling/Gate K не выполнены; browser приёмка ниже
и SCHEDULED controls остаются необходимыми для полного закрытия K3.

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
- **Scope:** cache фото; локальные характеристики/описание/состав/аллергены/хранение/учебные
  сведения уже включены в K2; в K4 остаются media/source evidence и бизнес-проверка
  контента по фактической доступности, без повторной формы и системы тестирования сотрудников.
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

## 12. Исторический результат K0 и точка остановки — 08.10.2026

R0 выполнен read-only: [отчёт](STAGE_3_2_R0_REPORT_2026-10-08.md).
K0 реализован локально на демонстрационных данных и передан на review; визуальная
и функциональная приёмка владельцем ещё не выполнена. Backend-контракты, реальные
права управления, хранение и интеграции K1–K6 этим результатом не подтверждаются.
Deployment не выполнялся. Следующий шаг после приёмки портала — отдельное задание
на наполнение по сентябрьским продажам; производство остаётся за gate K.


## K1 — фактический результат текущего задания

[Отчёт K1 от 08.10.2026](STAGE_3_2_K1_REPORT_2026-10-08.md): read-only сентябрьский
аудит — 141 UUID, 141 технически готов, 0 identity/mapping конфликтов; 30/30 дней
по трём подтверждённым точкам. Реализованы additive 0074/source-first model,
GET catalog/detail, backend filters/search/pagination, controlled bootstrap/retry/
unpublication и audit. Демо изолировано в dev; рабочий портал читает EOS API.
Текущее задание разрешило эти изменения; прежние ограничения документационного
и K0-проходов относятся только к тем проходам, не запрещают реализацию K1.

Вес подтверждён у 131, тип — у 141; confirmed effective prices/фото/ТТК/cost
не заполнены. Для цен есть 413 BASE-кандидатов на review; валюта/единица/Office
effective verification не подтверждены. Не менять семантику отсутствующих полей.
Категории EOS не назначаются из iiko категорий автоматически.

Историческая точка остановки K1 от 08.10.2026: на review, не DONE; требовались решения по стартовому статусу, ценам и
содержательная сверка всех sold types/deleted/одноимённых UUID. На том проходе производственная
часть и K2–K6 не были начаты. Текущий статус K1/K2 от 09.10.2026 указан вверху. Production migration/loading/deployment требуют отдельного
согласования; gate K и весь Stage 3.2 не закрыты.
