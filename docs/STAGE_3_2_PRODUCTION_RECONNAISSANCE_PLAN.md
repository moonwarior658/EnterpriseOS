# EnterpriseOS — Stage 3.2: план production reconnaissance

**Версия:** 0.1.0 · **Дата:** 08.10.2026 · **Статус:** только план на review.
**Разведка НЕ выполнена. Ни одного production API-запроса в этом задании нет.**
Запуск возможен отдельным заданием после согласования документации. Все поля,
HTTP verbs, права и результаты новых API сейчас неизвестны.

Связи: [spec](STAGE_3_2_PRODUCT_KNOWLEDGE_AND_PRODUCTION_SPEC.md),
[architecture](STAGE_3_2_ARCHITECTURE.md),
[Q/A/R registry](STAGE_3_2_OPEN_QUESTIONS.md),
[R0 и дальнейшие слайсы](ROADMAP_STAGE_3_2_v0.1.0.md).

## 1. Цель, ограничения и ответственные

Получить факты о реально установленном iiko, coverage данных и доступности
read-only методов, чтобы утвердить небольшой первый слайс базы. Не выполнять
синхронизацию в EOS, backfill, mapping confirm, schedule run, миграции, deployment,
restart или изменения iiko. Не использовать EOS `POST sync` и `run-now`:
чтение iiko внутри них сопровождается записью EOS.

Предлагаемые участники: ADMIN/оператор доступа (без передачи credentials в отчёт),
разработчик, владелец ассортимента/NETWORK_MANAGER, CHEF_CONFECTIONER и ACCOUNTANT
для независимой проверки значений. Имена и время назначить в отдельном задании.

Read-only допускает необходимую аутентификацию/logout и локальное сохранение
обезличенных результатов исследований, но не business writes. Credential/token
не печатать, не хранить в repository/logs; использовать текущую конфигурацию,
не менять `.env`, API-account permissions, настройки доступа или инфраструктуру.

## 2. Безопасный порядок и stop conditions

1. Read-only preflight EOS production: git HEAD/status, configured integration
   shape без secrets, текущий Alembic revision read, sources/worker topology,
   last existing sync metadata. Не запускать контейнер/миграцию ради preflight.
2. Зафиксировать используемую версию/API и официальные контракты. До вызова
   неизвестного пути установить, что операция read-only, включая HTTP POST,
   если такой verb официально требуется для чтения. Не пробовать guessed RPC.
3. Одна API-сессия и последовательные запросы. Сначала минимальный известный
   reader; каталог полностью, фото/ТТК — bounded sample. Всегда logout/close
   в finally, учесть license slots.
4. Стартовый лимит **предложение для согласования:** concurrency=1, timeout
   ≤30 секунд, не более двух повторов transient ошибки с backoff; не увеличивать
   лимиты сервера, не выполнять burst/нагрузочный тест. Полные каталог/price
   reads — только в согласованный бюджет запроса/времени; потолки body/media
   уточнить по официальному контракту перед скачиванием.
5. При 401/403 не повышать права и не повторять перебором: отметить unavailable.
   При 429, license contention, росте нагрузки/latency или влиянии на текущие
   sync — остановить batch и согласовать новый budget. 5xx/timeout не трактовать
   как пустой справочник. При неизвестной операции/формате или риске write — stop.
6. Production UI iikoOffice проверять только просмотром; не сохранить цену/ТТК,
   не создать/провести документ. Никаких create/update/delete/process/import API.
7. Закончить отчётом и предложениями; не начинать реализацию по результатам
   разведки без отдельного задания.

## 3. Проверки и требуемые артефакты

### P01 — архитектура, версия и права (Q02/Q08)

- Read-only просмотреть существующий EOS deployment/adapter config shape,
  current iiko sync/sales sources и authenticated reader seams. Отметить локальный
  EOS handler или AutomationProvider/n8n path; не перестраивать интеграцию.
- Зафиксировать версию iikoServer/iikoOffice/API, tenant/source и organization
  boundaries, права аккаунта на catalog/prices/images/assembly/cost reports;
  доступы можно подтвердить безопасным read либо просмотром permission metadata.
- Сверить реально установленный API с официальной документацией этой версии:
  base-path, verbs, mandatory params, format, pagination, date/timezone и лимиты.
- **Артефакт:** architecture/source map без host credentials + per-method
  contract/permission matrix: supported / forbidden / unsupported / not checked.
  404, 403, empty 200 и корректные данные — разные результаты.

### P02 — полный каталог и классификация (Q01/Q03/Q07/Q10)

- `/resto/api/v2/entities/products/list` через подтверждённый read contract;
  включить deleted, если supported. Получить все страницы, groups/categories/
  units/packages через существующие readers. Не фильтровать заранее «по названию».
- Проверить completion, total/unique UUID, duplicate/conflicting UUID, валидность
  units/group/category references, одинаковые названия при разных IDs.
- Для каждого типа и группы посчитать количество, долю missing/invalid веса,
  sale mode/source type, image reference, состава/аллергенов/сроков и прочих
  фактически присутствующих атрибутов. Отделять поле missing от null/zero/empty.
  Unknown source field не превращать в known EOS attribute.
- Владелец/шеф размечают готовые изделия, сырьё, полуфабрикаты, упаковку,
  модификаторы/услуги и спорные записи. Утвердить versioned rule и exceptions
  по IDs; `deleted/defaultIncludedInMenu` оставить отдельными source признаками.
- По существующим EOS данным read-only сверить SupplyProduct/iiko_id/mappings:
  confirmed links, collisions normalized_name, отсутствующие units. Не исправлять.
- **Артефакт:** counts/coverage с denominator + классификационная матрица всех
  source IDs (контролируемое хранение) + небольшой обезличенный sample по классам;
  proposed published subset и conflict list. Отдельное initial status решение Q01.

### P03 — цены по точкам (Q04)

- Исследовать `/resto/api/v2/price` только после P01. Согласовать параметры
  point/date/period/order; не угадывать внешнее подразделение по имени.
- На всех согласованных пилотных точках проверить действующие, будущие,
  истёкшие/отменённые приказы и крайние даты; различия цен одного UUID.
- Фиксировать currency/unit/tax/context если предоставляются, priority и
  intervals. Не выводить действующую цену из сортировки ответа без контракта.
- **Артефакт:** product UUID × point ID × date × order/context → price;
  independent iikoOffice screenshot/export с тем же контекстом, расхождения.
  Если источник/правила не доступны, Q04 остаётся открытым; fallback не выбирать.

### P04 — фотографии (Q09/Q10)

- `/resto/api/v2/images/load`: подтвердить identifier/verb/body/формат ответа,
  права и размеры до скачивания. Не следовать произвольным ссылкам payload.
- По каталогу считать наличие reference; bounded sample: есть/нет фото,
  устаревшая ссылка, разные размеры/форматы, повторная read загрузка.
- Проверить связь image→product UUID, actual MIME/decode/hash/content length,
  возможность version/etag/cache validation; не обещать incremental media.
- **Артефакт:** catalog reference coverage + download success coverage отдельными
  метриками, image contract, размер/latency sample, cache/storage рекомендации.
  Нет фото в выборке — не доказательство отсутствия метода.

### P05 — технологические карты (Q06)

- Последовательно проверить `/resto/api/v2/assemblyCharts/getAll`, `getTree`,
  `getPrepared`, `getHistory` с параметрами, подтверждёнными P01.
- `getAll`: выбрать актуальные/исторические версии, область действия, даты,
  product UUID, output quantity/unit; проверить coverage утверждённых изделий.
- `getTree`: сырьё/полуфабрикаты, recipe nodes, потери, output, циклы, references.
- `getPrepared`: конечные ингредиенты, количественные единицы, сравнение с
  ручным разложением tree; не считать tree/prepared денежным cost источником.
- `getHistory`: version IDs/revisions/effective intervals/deleted charts,
  изменившийся рецепт; оценить возможность dated immutable snapshot.
- **Артефакт:** availability по четырём методам, chart coverage, 3–5
  репрезентативных ручных сравнений (или согласованный другой sample), включая
  nested semifinished, missing ТТК/ingredient/unit; шеф сверяет с iikoOffice.
  Если отсутствуют API/единицы/даты, расчёт сырья остаётся заблокированным.

### P06 — фактическая денежная себестоимость (Q05/Q15)

- Отдельно от P05 исследовать официальные определения ССС, СПП, ССН, ССНПП,
  где они отображаются в используемом iikoOffice и какие read API/отчёты дают
  соответствующие значения. Endpoint для cost заранее не утверждать.
- Для каждого кандидата заполнить: метод/определение, фактический или оценочный,
  product/department/store, date/period, unit, currency/tax, версия/права,
  зависимость от периода и условий расчёта. Read-only построение отчёта только
  если подтверждено, что не меняет business state и входит в load budget.
- Сверить одну и ту же ТТК/дату/точку/единицу с iikoOffice; приложить значение
  и объяснение отличий. Не выдавать повторную API-сверку за независимую.
- **Артефакт:** comparison matrix четырёх кандидатов + рекомендуемый источник
  с ограничениями либо вывод «источник не подтверждён». Закупочная оценка не
  проходит эту проверку как фактический cost. Q15 — отдельное business решение.

### P07 — последующее обновление и полнота (Q08)

- По официальному контракту и повторным read-наблюдениям изучить updatedAt/
  revision/cursor/since, pagination stability, deleted, возврат ранее известного
  значения, изменения цен/ТТК/фото. Не создавать изменение iiko для эксперимента.
- Если в доступном интервале нет естественных изменений — честно отметить, что
  incremental/deletion не доказаны. Семантику сбоя/cursor проверять mock/offline,
  не прерывая production services и не изменяя сеть/права.
- Сверить полный vs candidate delta ID set на одинаковом source scope;
  предложить manifest/current pointer для unchanged observation/A→B→A.
- **Артефакт:** supported sync strategy по каждому блоку, evidence и unknowns;
  full-snapshot fallback/частота только при подтверждённом P08 budget.

### P08 — нагрузка и эксплуатация (Q08/Q09)

- Для разрешённых read calls измерить count/pages/bytes/duration, observed
  limits/rate errors, стоимость media и ТТК sample; не стресс-тестировать iiko.
- Read-only проверить существующие worker concurrency, sales/shift schedules,
  token/license lifecycle, DB/media volume shape и доступные capacity показатели.
- Предложить численные latency/freshness/batch/timeout/retention/quota budgets
  только из измерений и согласования с владельцем; не выдавать стартовые лимиты
  плана за доказанную безопасную production нагрузку.
- **Артефакт:** measured baseline + proposed initial cadence и stop thresholds;
  оценка full import/cache growth, disable/recovery и backup требований.

## 4. Формат evidence и итогового отчёта

Для каждого E-артефакта хранить: время (Asia/Yekaterinburg), source/версию,
Pxx/Qxx, путь/verb и безопасные параметры, scope и полноту выборки, HTTP outcome,
latency/count/bytes, фактические поля и missing, степень independent проверки,
hash обезличенного sample, вывод/ограничения. Полный сырой catalog/рецепты/цены
хранятся только в согласованном защищённом месте; в git — безопасные выводы,
не internal raw payload. Не сохранять auth headers, query tokens или secrets.

Шаблон строки (пустой, результатов сейчас нет):

| Evidence ID | P/Q | Source/version/time | Read contract/scope | Outcome/completeness | Measured fields/limits | Independent comparison | Decision/unknown |
|---|---|---|---|---|---|---|---|
| E-… | P… / Q… | заполнить при разведке | без credentials | not checked до выполнения | без догадок | iikoOffice либо missing | supported/blocked/needs check |

Итог разведки должен содержать: architecture map, capability matrix всех семи
методов, полный catalog classification/coverage, цену по точкам, фото/ТТК/cost
evidence, sync/load рекомендации, закрытые/открытые Q с причинами, пересмотр
K1 scope/migrations/API по фактам. Непроверенное не помечать available.

## 5. Exit gate R0

R0 завершён как исследование, если проверки имеют evidence или явный статус
невозможности с причиной; это не означает, что все API доступны. Для допуска K1
обязательно закрыть identity/classification/source/access/initial-publication
вопросы и подтвердить безопасный initial read path. Цена/ТТК/cost/media gaps
блокируют соответствующие последующие слайсы, а не маскируются фиктивными данными.
Документация обновляется по фактам, владелец утверждает K1 план. Производственная
часть остаётся за gate K независимо от успешности R0.
