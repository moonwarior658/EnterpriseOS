# Stage 3.2 / K5A — исследование ТТК и себестоимости iiko

Дата: **09.10.2026**, timezone **Asia/Yekaterinburg**. Статус: **на review**.
Только исследование и документация. K5B–K5D ниже — предложения, не реализованный
scope. Производственные планы, каталог, цены, конфигурация и production data
не изменялись; commit/push/deployment не выполнялись.

## 1. Вывод для review

1. ТТК, ингредиенты, нормы, технологические комментарии и история доступны через
   iikoServer API. Повторно проверены семь read-методов `assemblyCharts`, включая
   получение старой карты по ID и выбор версии на реальной границе дат.
2. Среди **141 UUID K1–K4** текущая карта найдена для **128**. У **100 из этих 128**
   есть непосредственный ингредиент, для которого в текущей выборке также есть
   карта. Все 13 UUID без карты имеют source type **GOODS**; это не доказательство
   необходимости ручного рецепта или готовности изделия к производству.
3. Денежные поля `ProductCostBase.ProductCost` и `ProductCostBase.OneItem`
   доступны в SALES OLAP. Они относятся к проданным позициям за выбранный период.
   **Прямой источник подтверждённой стоимости текущей ТТК/карточки не установлен.**
4. Существующие EOS UUID сохраняются. Корневой рецепт связывается через
   `(tenant_id, source_id, iiko_product_id)`; ингредиенты требуют отдельной source
   projection и явных nullable Supply links, без добавления сырья в ассортимент.
5. Рекомендуется отдельно реализовать K5B — версии и качество рецептур,
   K5C — подтверждение денежного источника, K5D — защищённый просмотр и независимую
   приёмку. Расчёт выпуска/сырья и изменения Sales KPI остаются вне K5.

Q05 (денежный метод) и Q06 (бизнес-проверка рецептур) **не закрыты**. Если источник
денег не подтвердится, исключение Q15 требует отдельного решения владельца.

## 2. Основания, архитектура и актуальность документов

Проверены Charter/Blueprint и профильные разделы main/Supply roadmap, Supply spec,
ADR-001, `CODEX_CONTEXT.md`, пакет Stage 3.2, отчёты R0 и K1–K4. Порядок остаётся
`база продукции → K6/Gate K → производственная часть P0–P4`.

В задании владелец подтверждает реализацию K0–K4. Датированные документы ещё
содержат «K3 локально», «K4 на review», старые Git/Alembic baseline и R0 «history
по одной версии». Это исторические записи, не текущий live статус. Они здесь
не переписываются, завершение K0–K4 не переаудируется; актуальные наблюдения K5A
приведены отдельно. Поведение K5 не конфликтует с утверждёнными границами.
Деление K5 на B/C/D в текущей roadmap не определено: это предлагаемая декомпозиция.

| Существующий компонент | Подтверждённое назначение / применение в K5 |
|---|---|
| [`IikoServerClient`](../backend/api/app/integrations/iiko/client.py), [`IikoProvider`](../backend/api/app/integrations/iiko/provider.py) | Auth, TLS, последовательные запросы внутри одного клиента, безопасные ошибки, logout; каталог/единицы/остатки/OLAP/цены уже есть. Публичных recipe reader/DTO нет |
| [`ProductKnowledgeProduct`](../backend/api/app/models/product_knowledge.py) | EOS identity, unique tenant/source/iiko UUID, базовая единица, nullable Supply FK, publication/local content; recipe/cost модели отсутствуют |
| [`snapshot.collect`](../backend/api/app/product_knowledge/snapshot.py), [`bootstrap`](../backend/api/app/product_knowledge/bootstrap.py) | Source lock, существующая UUID identity, source observation и подтверждённая публикация |
| [`price_refresh`](../backend/api/app/product_knowledge/price_refresh.py) | Образец bounded collection, immutable observation, atomic publication; K5 не должен писать в price tables |
| [`service`](../backend/api/app/product_knowledge/service.py), [`routes`](../backend/api/app/api/routes/product_knowledge.py) | Каталог/detail читают EOS DB; cost/recipes исключены из публичной проекции. Manage-only подтверждение новых UUID отдельно читает iiko — этот путь не используется для выдачи ТТК |
| [`authorization`](../backend/api/app/core/authorization.py) | READ/MANAGE базы не означают разрешение денег/полной ТТК; нужны отдельные field/capability guards |
| [`local_actions`](../backend/api/app/automation/local_actions.py), [`dispatch`](../backend/api/app/automation/dispatch.py) | K3 уже использует existing schedules/execution/outbox/local worker; будущий recipe refresh должен расширить этот seam, без второго scheduler |

iiko — источник внешних фактов. EOS владеет идентичностью, проверкой качества,
правами, публикацией, историей и последующими бизнес-расчётами. UI читает EOS DB.
Для этого reader подходит existing local action; новый workflow n8n не нужен.
Если adapter n8n понадобится, сохраняется AutomationProvider/API/callback boundary,
без доступа n8n к EOS PostgreSQL.

## 3. Live-проверка и границы доказательств

Production и local HEAD: `a5a02823906ac467bceb8f98ad971377a5f31d6e`.
Production Alembic: `20261009_0077`. Production HEAD/status до и после одинаковы.
Сохранились прежние untracked `'2026-09-01'`, `M`, `backup/`, `output/` и файл
с именем `dockercomposedocker-compose.yml` с дополнительным Unicode-символом.
Они не читались и не менялись.

EOS DB читалась через `BEGIN READ ONLY` с rollback; business sync, run-now,
import/save/process, миграции и restart не вызывались. Исследовательские Python
фрагменты выполнялись в памяти API-контейнера, без записи production-файлов;
настроенные credentials читались существующим settings object, не выводились.
Использованы три короткие API-сессии, запросы внутри каждой последовательные,
TLS включён, timeout 30 s, retries=0. Во второй и третьей сессиях logout отдельно
вернул HTTP 200; в первой выполнен existing `aclose`, статус logout отдельно
не записан. SSH закрыт.

Первое наблюдение — **13:12:57**, подробное — **13:15:52** местного времени.
Всего **36 data/report запросов**: 10 первоначальных + 19 подробных + 7 для scope
comparison; auth/logout отдельно. Все наблюдаемые data/report ответы — HTTP 200.
Два day-scoped getAll выполнены потому, что второй проход дополнял coverage,
единицы и version-boundary evidence. Стресс-тест и глобальная сериализация со
штатными Sales/shifts readers не выполнялись.

Сохраняемые [обезличенные свидетельства](evidence/STAGE_3_2_K5A_2026-10-09.json)
содержат подробный проход и scope comparison: **26 запросов**, JSON-примеры,
контекст OLAP и результаты проверок. Первые 10 запросов представлены результатами
в этом отчёте, полный console transcript не сохраняется. Hash evidence:
`92bd43e58cc51994580b160db1e770a2e02c5e171e3d7a5f58f764a220c47342`.

`key:<16 hex>` — псевдоним UUID по SHA-256, **не UUID для API и не mapping**.
Из evidence удалены реальные UUID/названия/технологические тексты, credentials,
URL источника и токены. Decimal в подробном evidence сериализованы строками;
в реальном JSON они числа. Примеры ниже сокращены и обезличены, числовые значения
и даты получены live, не придуманы. Raw ответы обрабатывались только в памяти.

Точная версия удалённого iikoServer и локального iikoOffice не установлена.
Константа `_BACK_VERSION` клиента и ранее обнаруженная версия BackOffice
9.2.7014.0 не являются доказательством сборки сервера. Официальные определения
ниже прочитаны для iikoOffice 9.2; применимость и настройки требуют сверки.

## 4. Подтверждённые методы iikoServer API

Пути относительно настроенного `/resto`. Все методы таблицы — GET, кроме OLAP
report POST, который только строит отчёт и не меняет бизнес-данные.

| Метод | Параметры / форма ответа | Доказательство K5A |
|---|---|---|
| `/api/v2/assemblyCharts/getAll` | `dateFrom`, `dateTo`, `includeDeletedProducts=true`, `includePreparedCharts=false`; `ChartResultDto` | День `[09.10,10.10)`, 5 684 карты, 10 486 227 bytes |
| `/api/v2/assemblyCharts/getTree` | `productId`, `date`, optional `departmentId`; `assemblyCharts` + `preparedCharts` | Три K UUID; деревья 9/6/5 карт. Один UUID дополнительно проверен union и по трём точкам |
| `/api/v2/assemblyCharts/getAssembled` | `productId`, `date`, optional `departmentId`; `ChartResultDto` с исходной картой | 31.05 и 01.06: разные действующие UUID карты и нормы |
| `/api/v2/assemblyCharts/getPrepared` | Тот же product/date/department; `ChartResultDto`, а не голый массив | Три пилота; дополнительный `tree.preparedCharts == getPrepared.preparedCharts` для одного UUID по каждой из трёх точек |
| `/api/v2/assemblyCharts/getHistory` | `productId`, optional department scope; массив исходных карт | 1/1/2 версии; реальные интервалы и изменённая норма |
| `/api/v2/assemblyCharts/byId` | `id` карты; голый `AssemblyChartDto` | Историческая карта до 01.06 получена по её UUID |
| `/api/v2/assemblyCharts/getAllUpdate` | `knownRevision` из getAll с **теми же** параметрами | HTTP 200, revision 16 367 310, пустые changes/deletions. Реальное изменение/удаление через delta не проверено |
| `/api/v2/entities/products/list` | Повторяемые `ids`, `includeDeleted=true`; массив продуктов | 191 requested UUID / 191 received, четыре batch ≤50 IDs; ассортимент не импортировался |
| `/api/v2/entities/list` | `rootType=MeasureUnit`, `includeDeleted=true`; массив единиц | Все единицы запрошенных продуктов разрешены |
| `/api/v2/entities/products/productScales` | Повторяемые `productId`, `includeDeleted=true`; object UUID → шкала/null | Для трёх пилотов null, в том числе для SPECIFIC; наличие реальной шкалы/размеров этим sample не доказано |
| `/api/v2/reports/olap/columns?reportType=SALES` | Object field → metadata | MONEY cost total/one item, PERCENT cost/markup и MONEY profit доступны |
| POST `/api/v2/reports/olap` | `reportType=SALES`, `buildSummary=false`, 6 output fields, day/department filter; `data` | 51 product/unit/department строка за `[08.10,09.10)`, 50 K UUID, null cost=0, zero cost=1 |

[Официальный контракт ТТК](https://ru.iiko.help/article/api-documentations/tekhnologicheskie-karty?cm=1&ds=1&gc=1),
[каталог](https://ru.iiko.help/article/api-documentations/elementy-nomenklatury?cm=1&ds=1&gc=1),
[справочники](https://ru.iiko.help/article/api-documentations/spravochniki?cm=1&ds=1&gc=1),
[шкалы/размеры](https://ru.iiko.help/article/api-documentations/rabota-so-shkaloy-i-razmerami?cm=1&ds=1&gc=1),
[OLAP v2](https://ru.iiko.help/article/api-documentations/olap-otchety-v2?cm=1&ds=1&gc=1).
Страницы прочитаны через опубликованный `/article/...` reader: динамическая
оболочка `/articles/` текста контракта не даёт.

Документация `getHistory` одновременно отмечает departmentId как обязательный
и описывает отсутствие фильтра; R0 ранее подтвердил omission live. В K5A задан
конкретный departmentId. Это неоднозначность документации, не основание менять
права/параметры вслепую. Save/delete методы известны из документации, **не вызывались**.
HTTP 200 не доказывает весь набор прав API-account или бизнес-приёмку.

## 5. Состав, нормы, единицы и выход

### 5.1 Контракт норм

- `assembledProductId` — UUID корневого изделия, `id` — UUID версии карты;
  это разные сущности. `assembledAmount` — норма/база приготовления в основных
  единицах изделия, не автоматически его вес в kg.
- `items.productId` — UUID ингредиента; его `mainUnit` разрешается по каталогу и
  MeasureUnit. `amountIn` — брутто для базы карты; `amountMiddle` — нетто,
  `amountOut` — выход строки. Все три значения в **базовых единицах ингредиента**.
- `amountIn1/Out1` … `amountIn3/Out3` — показатели актов проработки в kg.
  Они не заменяют действующие нормы `amountIn/Middle/Out`.
- `unitWeight` — kg на одну базовую единицу конкретного продукта.
  `packageTypeId`/фасовки, size coefficient и unitWeight не взаимозаменяемы.
- `outputComment` — строковый суммарный выход. Без утверждённой единицы строки
  нельзя превращать «290», «75», «100» в вес в kg/граммах.
- `technologyDescription`, `description`, `appearance`, `organoleptic` —
  технологические текстовые поля источника; не безопасный состав для SELLER.

Потери можно вывести как отношения норм строки после проверки контекста:
`1 − amountMiddle/amountIn`, `1 − amountOut/amountMiddle`. При нулевом знаменателе
показатель неизвестен; это derived EOS value, не отдельное подтверждённое поле
процентов iiko. Для неоднородных единиц суммировать исходные количества нельзя.
Вес готового изделия K1 не равен автоматически сумме выходов строк или outputComment.

### 5.2 Реальный фрагмент исходной карты

`getTree` для K product key `5fcc771dd5101343`, EOS key `09f6848bcc0202df`,
базовая единица изделия «шт», дата 09.10, point key `a8e0fe727d8767fd`:

```json
{
  "id": "key:fedff96e2cb44f8a",
  "assembledProductId": "key:5fcc771dd5101343",
  "dateFrom": "2026-08-28",
  "dateTo": null,
  "assembledAmount": 1,
  "productWriteoffStrategy": "ASSEMBLE",
  "productSizeAssemblyStrategy": "COMMON",
  "outputComment": "290",
  "items": [{
    "productId": "key:7bed85eff66bab7c",
    "amountIn": 0.15,
    "amountMiddle": 0.15,
    "amountOut": 0.1,
    "amountIn1": 0.084,
    "amountOut1": 0.084,
    "productSizeSpecification": null,
    "storeSpecification": {
      "departments": ["key:a8e0fe727d8767fd"], "inverse": false
    }
  }]
}
```

У этого ингредиента source type PREPARED, mainUnit «кг», unitWeight=1:
0,15 kg закладки на одну базовую единицу изделия. Другая строка этой же карты
имеет ingredient type DISH, mainUnit «шт», unitWeight=0,13 и `amountIn=1`:
одна штука, не один kg. Есть GOODS-строка с unitWeight=0, действующей нормой 0
и проработкой `amountIn1=1`; подставлять 1 в действующий рецепт нельзя.
Эти наблюдения требуют проверки шефом, не автоматической правки данных.

### 5.3 Prepared и вложенность

Для пилотов `5fcc…`, `b223…`, `47d5…`: исходных root rows 6/5/6,
дерево содержит 9/6/5 карт, prepared — 17/14/13 строк. Это численность sample,
не гарантия полной проверенной рецептуры всех 128 изделий.

Сокращённый реальный `getPrepared` первого изделия:

```json
{
  "knownRevision": -1,
  "assemblyCharts": null,
  "preparedCharts": [{
    "id": "key:5e7de8e4ec99176a",
    "assembledProductId": "key:5fcc771dd5101343",
    "dateFrom": "2026-08-28",
    "dateTo": null,
    "productSizeAssemblyStrategy": "COMMON",
    "items": [{
      "productId": "key:7d7a6c7f0dd058aa",
      "productSizeSpecification": null,
      "storeSpecification": null,
      "amount": 0.0013
    }]
  }],
  "deletedAssemblyChartIds": null,
  "deletedPreparedChartIds": null
}
```

Prepared amount — на **одну базовую единицу изделия**, в базовой единице конечного
ингредиента. Денег в DTO нет. Вложенная карта имеет свою норму базы:
для простого COMMON разложения множитель включает отношение `amountIn/assembledAmount`
на каждом уровне. Однако документация прямо рекомендует запрашивать prepared:
справочная формула округления не покрывает все размеры и может быть неточной.
Live amount имеет до 9 знаков после запятой; округлять всё до трёх знаков нельзя.

Нужно различать граф технологического состава и списание со склада:
DIRECT заготовка может быть конечным складским узлом, несмотря на собственную
ТТК. Её дальнейшее разложение для производства — отдельная бизнес-политика,
а не следствие наличия nested recipe. В трёх пилотных деревьях все DTO strategy
ASSEMBLE; поведение реально DIRECT-вложенного узла в K5A не проверено.

Важная проверка scope: union effectiveDirectWriteoffStoreSpecification у первого
изделия — `inverse=true`, excludes key `4590e79908b53614`; scoped ответы по
трём торговым точкам содержат соответствующий point с `inverse=false`, но всё
равно возвращают 17 prepared ingredient rows. **Сам факт наличия prepared rows
не отменяет effectiveDirect scope и не доказывает списание сырья на точке.**
Нельзя присвоить производственному цеху рецепт торговой точки без подтверждённого
UUID Department/Store и сверки метода списания в Office.

SPECIFIC-пилот `47d5…` возвращает null size references; productScales для него
также null. Не заменять SPECIFIC на COMMON автоматически. Реальные non-null
sizes, их смена/удаление и коэффициенты остаются отдельной проверкой.

## 6. Версии, даты и изменение вложенной рецептуры

Live history для `47d5bdfb4b6f1aa7`:

| Source chart key | Действует с | До, исключительно | Одна изменённая норма amountIn |
|---|---|---|---|
| `984eeddca4392a8e` | 03.09.2025 | 01.06.2026 | 0,03 |
| `240e551c518867b2` | 01.06.2026 | null | 0,05 |

`getAssembled(date=2026-05-31)` вернул первую карту, `date=2026-06-01` — вторую.
`byId` вернул старую карту с прежними датами/нормами. Это подтверждённый реальный
version transition; сценарий source deletion или исправления «задним числом»
не проверен. Два других пилота имеют по одной версии.

Рекомендуемый resolver использует учётную дату `[dateFrom,dateTo)`, department,
size и source. Null end означает открытый интервал; наблюдаемую source дату,
включая sentinel dates, сохранять дословно и не изобретать окончание действия.

Версия итогового дерева зависит от **всех дочерних карт**, не только root UUID.
Если изменился полуфабрикат, root может остаться тем же. Поэтому сохранять
manifest root + dependency chart IDs/content hashes + units/packages + scope/date,
и observation time отдельно от effective date. Один revision не заменяет manifest.
Изменение source content под тем же chart UUID должно создавать новую EOS
observation/content version, сохраняя старое содержимое.

`getTree`/getAssembled/getPrepared известной ревизии для delta не дают
(`knownRevision=-1`). Cursor годен только для полного getAll/getAllUpdate того же
source/периода/options. Rolling date window требует нового baseline. При deleted
chart IDs нужны resolver и перечитывание прежней карты; source deletion не удаляет
EOS историю. Ограничения deletion replication старых iikoRMS указаны в документации;
их отсутствие на текущем сервере не доказано пустым delta.

StoreSpecification: `inverse=false` — включающий список, `inverse=true` —
исключающий. Null filter и пустой включающий список нельзя молча смешивать;
union/scoped формы хранить с request scope. Несколько подходящих версий/строк,
неизвестный размер, unresolved ingredient/unit, нулевая база или цикл должны
блокировать пригодность для расчёта. Для графа нужен path-based cycle guard:
повторение общей заготовки в разных ветках само по себе не цикл.

## 7. Денежная себестоимость: смысл и доступность

### 7.1 Как рассчитывает iiko

По [официальным определениям iikoOffice 9.2](https://ru.iiko.help/article/iikooffice-9-2/topic-3?cm=1&ds=1&gc=1):

| Показатель | Смысл / ограничения |
|---|---|
| ССС | Стоимость оставшихся запасов / их количество по конкретному складу на системную дату. Пересчитывается при приходах; отсутствие приходов допускает ручную оценочную стоимость |
| СПП | Стоимость последнего влияющего на запасы прихода. Это не обязательно закупочная накладная; без приходов значение неизвестно |
| ССН | Стоимость сырьевого набора по нормам ТТК и ССС ингредиентов; оценочный ингредиент делает итог оценочным |
| ССНПП | Сырьевой набор по последнему приходу; для ингредиентов без приходов возможен оценочный fallback. Метод по умолчанию отключён, настройка не проверялась и не менялась |
| ССН’ | Расчёт по ещё не сохранённым изменениям ТТК в Office; не опубликованная версия рецептуры |

Обычная «себестоимость» у товаров/готовых DIRECT позиций использует ССС, у
списываемых по ингредиентам — ССН. Это складской контекст, а не единая сумма на
все точки. Фактический режим, валюту и налоговую базу компании K5A не устанавливает.
`estimatedPurchasePrice` — ручная оценка, не подтверждённая фактическая стоимость.

### 7.2 Что возвращает доступный API

Live metadata SALES OLAP:

| Field | Source display name | Type |
|---|---|---|
| `ProductCostBase.ProductCost` | Себестоимость | MONEY |
| `ProductCostBase.OneItem` | Себестоимость единицы | MONEY |
| `ProductCostBase.Profit` | Наценка | MONEY |
| `ProductCostBase.MarkUp` | Наценка(%) | PERCENT |
| `ProductCostBase.Percent` | Себестоимость(%) | PERCENT |
| `ProductCostBase.PercentWithoutVAT` | Себестоимость без НДС(%) | PERCENT |

Все шесть доступны для aggregation, не grouping/filtering. В K5A запрошены только
первые два и количество; profit/percent значения не проверялись и в EOS KPI
не добавлялись. PERCENT не трактовать как готовые целые проценты без контракта.

Запрос: одна mapped точка, учётный день `[08.10,09.10)`, `buildSummary=false`;
group fields `DishId`, `DishMeasureUnit`, `Department.Id`, aggregates
`DishAmountInt`, cost total, cost per item — всего 6 полей. Без сырого account/token.
Сокращённая реальная строка:

```json
{
  "Department.Id": "key:a8e0fe727d8767fd",
  "DishId": "key:0532d212b77cbbeb",
  "DishMeasureUnit": "шт",
  "DishAmountInt": 6,
  "ProductCostBase.ProductCost": 720,
  "ProductCostBase.OneItem": 120
}
```

Эта строка доказывает доступность чисел в отчёте продаж, а не 120 RUB как текущую
ССН изделия. Валюта, VAT basis, склад списания, включение модификаторов/возвратов,
учётные корректировки и equality с выбранной колонкой Office не подтверждены.
Нет продажи — нет основания ждать current-cost row. Одно zero cost значение
сохранено как source fact, но не доказательство бесплатного сырья.

[Официальный balance/stores](https://ru.iiko.help/article/api-documentations/otchety-vv2?cm=1&ds=1&gc=1)
даёт `product/store/amount/sum` на timestamp с фильтрами department/store/product;
reader есть в EOS и был проверен в R0. В K5A отдельно не вызывался. `sum/amount`
для ненулевого остатка — возможный кандидат складской оценки; zero/negative stock,
source correction и метод требуют проверки. Это **не готовая ССН ТТК** и не
автоматический fallback в карточке. Incoming invoice price также не равно СПП
по всем типам приходов или ССС.

В рассмотренных официальных recipe/catalog/balance/OLAP контрактах не найден
доказанный отдельный endpoint, возвращающий одновременно current ССС/СПП/ССН/ССНПП
карточки с полным method/store/date/tax/estimate contract. Это граница исследования,
не утверждение об отсутствии такого метода во всех версиях или закрытых API iiko.
Недокументированные RPC cost методы не угадывались и не вызывались.

### 7.3 Источник, который требуется подтвердить

Для **current recipe cost** сначала нужны 3–5 независимых контрольных карточек
Office: точный UUID изделия, recipe date/version, подразделение и склад, базовая
единица/размер, название метода, сумма, валюта, VAT/выделение НДС, оценочность и
дата/время расчёта. Отдельно — historical sold cost report за тот же период/точку.
Бухгалтер подтверждает соответствие API полей и смысла показателей.

Если API для current cost не подтвердится: контролируемый экспорт iikoOffice
или документированный метод обслуживающей организации/вендора. Допустимый ручной
ввод — отдельная verified observation с evidence, автором, методом, scope и датой,
никогда обновление price/catalog и никогда «фактическая» без подтверждения.
Суммирование норм × закупочных цен возможно только как отдельно согласованный
**расчёт EOS**, с признаком оценки; такой расчёт не входит в K5A и не подменяет iiko.

## 8. Сопоставление со стабильными UUID K1–K4

Live source identity settings совпала с source_id всех 141 записей EOS.
Для 141 корней и ingredient/dependency UUID трёх деревьев прочитано **191**
уникальное значение; все 191 есть в каталоге, unresolved mainUnit=0,
конфликтов K unit UUID с текущим source mainUnit=0. Проверка не охватывает
все зависимости остальных 125 root recipes или Supply mappings всех ингредиентов.

Корневая связь:

```text
EOS ProductKnowledgeProduct.id
  → tenant_id + source_id + iiko_product_id
  → AssemblyChartDto.assembledProductId
  → source chart.id + effective date + scope + content observation
```

Recipe item productId связывать с external ingredient projection того же source,
а не с name/артикулом/local composition. По необходимости эта projection имеет
явную tenant-safe связь с существующим `IikoProductMapping`/SupplyProduct.
Неподтверждённая Supply связь остаётся NULL и блокирует будущую передачу сырья.
Не создавать SupplyProduct и не подтверждать mapping автоматически.

Ingredient может быть GOODS/PREPARED/DISH/MODIFIER и не обязан быть published
продуктом K1. Все разные source UUID сохраняют идентичность независимо от имени.
Рецепт отсутствующего ингредиента не заменяется пустым рецептом/нулём.
EOS soft deletion/ON_SALE/OFF_SALE, local content/photo, K3 price versions и
Sales nullable Supply FK не меняются от recipe sync.

134 EOS записей имеют `published=true` и `deleted_at IS NULL`; для них найдено
121 current chart, 13 missing. Остальные 7 записей сохранены в базе, но исключены
этим фильтром; это не основание удалять их рецептурную историю. 128 root charts
имеют strategy ASSEMBLE: 122 COMMON, 6 SPECIFIC. Coverage наличия карты не означает
проверку единиц, выхода и годности всех этих изделий.

## 9. Матрица доступности и пробелов

| Данные | Доступность сейчас | Что ещё нужно |
|---|---|---|
| Root UUID, chart UUID, даты/история | Live, включая переход версий и byId | Historical source deletion/correction; полнота nested history |
| Ингредиенты, брутто/нетто/выход строки | Live три дерева; 128 roots current coverage | Chef Office equality и quality для полного ассортимента |
| MainUnit и unitWeight | Live 191 UUID, links разрешены | Подтверждение переводов массы/фасовок, веса готового изделия |
| Текст суммарного выхода | Live строки «290»/«75»/«100» | Единица/смысл и numeric output, если нужен расчёт; ручное подтверждение шефа |
| Технология/appearance/organoleptic | Поля есть в контракте, запросы получены | Заполненность/актуальность бизнесом; текст не включён в сохраняемые evidence |
| Nested recipes | Live 9/6/5 узлов | Реальный DIRECT child, cycles, missing deps и production scope |
| Sizes/factors | Endpoint live, пилотные значения null | Non-null sample, смена/удаление шкал, size applicability |
| Sold cost total/per unit | Live SALES OLAP 51 строка | Office/accountant equality, налог/склад/возвраты/modifier semantics |
| Current ССС/СПП/ССН/ССНПП карточки | Не подтверждено | Другой documented source или экспорт/ручная verified observation |
| Estimated ingredient cost | Есть source атрибут; не выбран как money source | Оценочность, отдельный contract; никакой подмены фактической стоимостью |
| GOODS без текущей карты | 13 UUID, все published/nondeleted | Решение bought-goods/not-applicable vs missing recipe; не угадывать по типу |
| Production Department/Store и policy полуфабрикатов | В этом исследовании не подтверждены | Explicit UUID mapping + шеф; retail mapping не заменяет production |

## 10. Рекомендуемая архитектура K5B–K5D

Это **предложение на review**, без миграций/кода/новых grants сейчас.

### K5B — источник, версии и качество ТТК

Расширить existing iiko provider/client: typed recipes DTO, envelope validation,
read allowlist, bounded batch/body/timeout, Decimal без float-roundtrip. Раздельно
представлять assembled/tree/prepared/history/byId; getAll — bounded baseline,
а не full history по всей номенклатуре. Начать с подтверждённого пилота и production
scope, не импортировать всё дерево каталога в ассортимент.

Предлагаемые независимые сущности:

- Source ingredient projection: tenant/source/external product UUID, type,
  unit UUID, unitWeight/package/size observation; nullable confirmed Supply link.
- Immutable recipe observation/version: external chart UUID, root K product FK,
  effective interval, observed_at, scope/request/date, content hash, quality,
  source revision where applicable. Chart UUID и source content version различаются.
- Recipe item: external row/ingredient UUID, amountIn/Middle/Out, проработки,
  package/size/store specifications. Оригинальные ограничения сохраняются.
- Recipe dependency/prepared manifest: root+child versions, units/packages,
  date/department/size; отдельный checksum и immutable prepared observation.
- Publication/current selection: только полностью успешная observation,
  явные missing/conflict/stale/not_applicable и подтверждение владельца контента.

Collected/raw source representation защищена от обычных API; при retention
сохранять необходимые immutable historical dependencies. Дедуп по hash не
заменяет observation time и не делает A→B→A тем же событием. Курсор продвигать
в одной транзакции с полной публикацией того же scope. Partial/error не архивирует
продукцию, не удаляет прошлую версию и не заменяет действующий рецепт.

Будущий refresh action проходит existing execution/outbox/local worker с
идемпотентностью и terminal-state guards. Не копировать код price refresh целиком:
использовать его seams, recipe policy держать в product_knowledge service.
Периодичность и общий lease читателей согласовать в K6; расписание не включать.

**Приёмка K5B:** independent Office сравнение ≥3–5 изделий, включая nested,
версионный переход, mixed units и SPECIFIC/DIRECT; unresolved fields fail closed.
Проверки resolver, cycles, partial source, stale/deletion, same-ID correction,
tenant/source identity, повторная публикация и protected history.

### K5C — независимый денежный контракт

До схемы cost выбрать конкретный источник и метод. Хранить отдельно
`CURRENT_RECIPE_COST`, `HISTORICAL_SOLD_COST` и при отдельном решении `EOS_ESTIMATE`.
Не переносить sold cost в current pointer рецепта.

Минимальный proposed observation contract: tenant/source/product, тип показателя,
amount/null, currency, quantity basis/unit, method, warehouse/department/size,
effective_at или period_from/to, recipe/dependency basis где применимо,
VAT basis, estimated status, source observed_at, completeness/quality,
Office evidence и verifier. Неизвестные поля не получать из K3 цены или названия.

Если current source отсутствует — status `MISSING_SOURCE`, amount=NULL;
если метод/контекст не подтверждены — `UNVERIFIED`, без cost analytics.
Source zero сохраняется отдельно от missing и требует проверки смысла.
Manual observation/экспорт имеет свой provenance и не выдаётся за API snapshot.
Не менять Sales formulas, snapshots, report scheduler и существующие цены.

**Приёмка K5C:** бухгалтер/владелец подтверждает method/store/date/unit/tax/currency
и equality; повторная API-сверка недостаточна. Если отсутствует current источник,
зафиксировать Q15 отдельно; не закрывать K5C «по наличию OLAP endpoint».

### K5D — защищённая технологическая карточка и review

Расширить существующую карточку продукции, не создавать второй каталог.
Read-only recipe/date/scope/history, ingredient tree и отдельно prepared writeoff
projection; исходный outputComment и подтверждённые единицы видны с качеством.
Денежный блок появляется только по подтверждённому K5C contract и sensitive guard.
Safe composition K2/K4 не генерируется молча из полной ТТК; source технологический
текст и полный recipe не передаются SELLER.

Нужна утверждённая matrix full recipe/cost × role × scope. Existing
PRODUCT_KNOWLEDGE_READ/MANAGE не расширять до sensitive данных автоматически.
Backend guards действуют для detail/history/exports/caches, tenant-safe queries,
без raw payload/technical IDs в обычном интерфейсе. Audit фиксирует human review
версии/контекста; изменение iiko ТТК не доступно.

**Приёмка K5D:** шеф проверяет выход/нормы/версии, бухгалтер — деньги; browser и
negative role/tenant checks. Отключение reader сохраняет историю и показывает
stale/missing. После K5 остаётся K6 и Gate K; производственные планы/сырьевые
заявки здесь не реализуются.

## 11. Риски и решения до реализации

| Риск | Контроль / открытое решение |
|---|---|
| Prepared ошибочно принят за полную производственную рецептуру | Отдельные tree/writeoff projection, effectiveDirect scope, chef production mapping |
| Неверный вес/выход из amountOut, outputComment или шт→kg | MainUnit UUID, verified conversion, нулевой вес блокирует перевод; нет автоматических gram guesses |
| Изменился полуфабрикат, root ID прежний | Dependency version manifest, не только root hash |
| Потеря старой версии/ложное удаление при partial/delta | Immutable observations, atomic pointer, baseline по тому же scope, deletion reread |
| SPECIFIC/null sizes или inverse/null scope истолкованы неверно | Сохранить source DTO, отдельные quality cases, Office/vendor clarification |
| GOODS без карты искусственно превращён в производимое изделие | Explicit business applicability, missing не равно пустая ТТК |
| Sold/estimated cost принят за текущий фактический | Раздельные contracts, source method/store/date/tax, accountant verification |
| Name matching/автосоздание ingredients меняет каталог/Supply | Stable source UUID, отдельная projection, nullable explicit links |
| Раскрытие рецепта/денег через общую карточку или историю | Отдельные sensitive grants и backend projection; не полагаться на скрытую колонку |
| Reader мешает Sales/shifts и занимает license slot | Sequential bounded reads, stop на 429/license/timeout, обязательный logout; measured global concurrency в K6 |

[Официальные рекомендации iikoServer](https://ru.iiko.help/article/api-documentations/ogranicheniya-i-rekomendatsii?cm=1&ds=1&gc=1):
последовательные запросы, короткие периоды ≤месяца, OLAP без ненужных summary,
желательно ≤7 полей. Это не SLA/согласованная cadence. Текущий client lock локален
одной сессии; он не гарантирует отсутствие других читателей. Safe caps и нагрузочные
бюджеты будущего reader должны быть проверены до scheduled release.

На review нужны решения: pilot UUID и production department/store; policy DIRECT
полуфабрикатов/размеров; numeric output/units; sensitive role matrix; current cost
source и независимая accountant verification либо отдельное Q15 исключение.
Отсутствие этих решений не препятствует review отчёта и не разрешает реализацию.

## 12. Проверки и итоговое состояние

Проверены official contract pages, реальные read responses, UUID coverage,
unit links, historical boundary/byId, scoped tree/prepared equality, MONEY field
metadata и реальный day-scoped report. Сохранённый JSON разбирается; реальные
UUID/credentials в артефактах отсутствуют. Production Git HEAD/status до/после
не изменились. Это техническое API evidence, **не независимая Office/бизнес-приёмка**.

Изменены только новый отчёт и новый JSON evidence. `git diff --check` и whitespace
проверка новых файлов — OK. Backend tests/frontend lint/build не запускались:
исполняемый код, API EOS и схема DB не менялись. Local status: два новых untracked
файла; staging/branch/commit/push/deploy не выполнялись. **Остановка на review.**
