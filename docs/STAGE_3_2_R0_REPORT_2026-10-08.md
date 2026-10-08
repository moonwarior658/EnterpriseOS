# Stage 3.2 / R0 — production reconnaissance

Дата: **08.10.2026**, время наблюдений **10:47–11:10 Asia/Yekaterinburg**.
Основание: reviewed plan из `70b0cad8efedac33b2bba38c2fb67778c7f30526`.
Статус: **исследование завершено с явно указанными пробелами; gate K1 не закрыт**.

## Результат и границы

Полностью прочитан текущий каталог: **9 815 записей / 9 815 уникальных валидных UUID**.
Каталог, цены, изображения и все четыре метода ТТК доступны этому API-account.
Найден денежный OLAP-кандидат, но **источник фактической себестоимости текущей
карточки не подтверждён**. Независимых экспортов/скриншотов iikoOffice, проверки
шефа/бухгалтера и утверждённой бизнес-классификации нет.

Business writes не выполнялись: EOS DB читалась в транзакциях `BEGIN READ ONLY`
с rollback; full-sync, run-now, import/process/save, миграции, restart/deploy
не запускались. Использована одна iiko API-сессия, последовательные чтения,
timeout 30 секунд, retries=0. Аутентификация и logout — разрешённые планом
технические операции. `GET /api/logout` вернул 200; HTTP-клиент и SSH закрыты.
Код, конфигурация, production-файлы и существующая документация не изменены.
Созданы только этот отчёт и локальные обезличенные исследовательские артефакты.

Полный сырой каталог, названия, рецепты, денежные отчёты и фото обрабатывались
в памяти; credentials, tokens, auth headers и raw payload в артефактах отсутствуют.
`product_key`, `group_key`, `unit_key`, `normalized_name_key` — первые 16 hex
символов SHA-256 соответствующего UUID/нормализованного названия. Это псевдонимы,
не EOS ID и не утверждённые mappings. Матрица покрывает все source UUID, но для
бизнес-разметки потребуется контролируемая сверка с исходным каталогом.

Артефакты: [evidence.json](../output/stage3_2_r0/evidence.json),
[summary.json](../output/stage3_2_r0/summary.json),
[HTTP measurements](../output/stage3_2_r0/http_observations.csv),
[каталог: 9 815 строк](../output/stage3_2_r0/catalog_matrix.csv),
[коллизии названий](../output/stage3_2_r0/name_collisions.csv),
[coverage по группе и типу](../output/stage3_2_r0/group_coverage.csv),
[SHA-256 manifest](../output/stage3_2_r0/manifest.json).

## P01 — архитектура, версия, контракты и права

Production HEAD до/после: `a9c75d02e2e18db68f83e77a29f25b0863272eed`.
Alembic: `20261006_0073`. Локальный HEAD: `70b0cad`.
Production status до/после одинаков: untracked `'2026-09-01'`, `M`, `backup/`.
Эти файлы не изменялись. Установленный Windows **iikoChain BackOffice —
9.2.7014.0**, подтверждено registry DisplayVersion. Точная сборка удалённого
iikoServer и установленного iikoOffice отдельно **не подтверждена**; версия
BackOffice и константа адаптера не заменяют server-version evidence.

Карта: `EOS API / automation-worker → существующий IikoServerClient → HTTPS
iikoServer /resto`. TLS verification включена. В конфигурации один base URL,
`api_type=iiko_server`, RPC instance configured; в Supply один tenant, в Sales
один source. Fingerprint configured URL: `244d6eaf9c7c1069`. Это подтверждает
наблюдаемый contour, а не глобальное отсутствие других iiko sources.
Каталог: прямой reader; Sales и shifts: локальные background actions/loops;
`n8n` присутствует как отдельный AutomationProvider-контур. Reconnaissance
вызовы не проходили через EOS sync handlers и ничего не staged в EOS.

Официальные контракты найдены через [sitemap iiko](https://ru.iiko.help/sitemap.xml)
и опубликованный reader `/article/api-documentations/<slug>?cm=1&ds=1&gc=1`.
Динамическая оболочка `/articles/` сама по себе текста контрактов не предоставляла.

| Метод, HTTP GET | Контракт | Production outcome | Права / ограничения |
|---|---|---|---|
| `v2/entities/products/list` | includeDeleted, IDs/types/groups filters; весь список, без page/cursor | 200, полный JSON array, 9 815 | Чтение доступно; contract требует B_EN, отдельный permission export отсутствует |
| `v2/price` | dateFrom/dateTo, departmentId, includeOutOfSale, type, revisionFrom | 200, SUCCESS, 7 483 contexts | Чтение доступно; currency/unit не передаются |
| `v2/images/load` | imageId UUID; base64 image | 200/SUCCESS; оба существующих image ID декодированы | Реальный ответ обёрнут в result/errors/response |
| `v2/assemblyCharts/getAll` | полуоткрытый период, includeDeletedProducts, includePreparedCharts | 200, 5 684 карты | Чтение доступно; выборка текущего дня, не вся история |
| `getTree` | productId/date; optional departmentId | 200, три samples | Без departmentId — union scope; применимость строк анализировать отдельно |
| `getPrepared` | тот же product/date/scope | 200, три samples | Учитывает writeoff/size strategy; не денежный cost |
| `getHistory` | productId; department scope | 200, список на каждом sample | Документация противоречива: departmentId указан «обязательный», но описывает отсутствие; omission работает live |

401/403/404/429 не наблюдались в завершённых API-чтениях. Это не доказательство
полных account permissions или доступности write-методов. Новые права не выдавались.
Sources: [номенклатура](https://ru.iiko.help/article/api-documentations/elementy-nomenklatury?cm=1&ds=1&gc=1),
[цены](https://ru.iiko.help/article/api-documentations/tseny-zadannye-prikazami?cm=1&ds=1&gc=1),
[ТТК](https://ru.iiko.help/article/api-documentations/tekhnologicheskie-karty?cm=1&ds=1&gc=1),
[изображения](https://ru.iiko.help/article/api-documentations/rabota-s-izobrazheniyami?cm=1&ds=1&gc=1).

## P02 — полный каталог, идентичность и единицы

Evidence E068–E070, E075; type/group coverage сохранён с denominators.
Полный ответ: **18 999 414 bytes**, **1.0774 s**, includeDeleted=true,
SHA-256 `fe6fcbf9c3f285c32dbe19468076280a1e5da77685df5b4db46c2ae299e947b8`.
Completeness: получен и разобран весь array официального unpaginated list.
Отдельного server total или атомарного manifest между разными endpoints нет.

| Source type | Всего | deleted=false | Вес=0 среди deleted=false | С текущей ТТК среди deleted=false |
|---|---:|---:|---:|---:|
| DISH | 3 802 | 227 | 18 | 227 |
| GOODS | 3 657 | 2 412 | 1 857 | 1 |
| PREPARED | 1 170 | 839 | 0 | 838 |
| MODIFIER | 558 | 184 | 55 | 183 |
| OUTER | 468 | 468 | 0 | 0 |
| SERVICE | 160 | 117 | 30 | 114 |
| **Итого** | **9 815** | **4 247** | **1 960** | **1 363** |

Deleted: 5 568. Invalid/duplicate/conflicting UUID: **0/0/0**.
Одинаковые точные названия: 575 групп. После существующей EOS-нормализации
(casefold, ё→е, whitespace, trailing punctuation): **666 групп / 1 599 записей**;
среди deleted=false: **103 группы / 270 записей**. Даже внутри неудалённых DISH
есть **3 пары / 6 записей**. Name-only identity непригодна.

10 единиц, 823 группы, 27 категорий, 301 фасовка. Все mainUnit заполнены;
unknown unit/group/category references — **0/0/0**, duplicate package IDs — 0.
`unitWeight` есть у всех; zero=3 228/9 815, negative=0. По контракту это **kg
на одну основную единицу**, а не масса порции по названию. В каталоге есть
шт/кг/л/порц/уп/рул/пак/пач/м; «мес» существует без product references.
Нулевой вес не даёт права на автоматический перевод штуки/порции в kg.

Заполненность всего каталога: description nonempty **217/9 815**;
allergenGroups nonempty **70/9 815**, отдельно null=8 255 и empty=1 490;
frontImageId nonnull **10/9 815**; category null=5 286; parent null=525;
estimatedPurchasePrice nonzero **70/9 815**. Поля shelfLife, nutrition,
storageConditions в полном фактическом наборе отсутствуют. Текст description
не превращался в структурированный состав/срок. Все 36 фактических product
полей представлены у каждой записи; missing/null/empty/zero раздельны в evidence.

EOS: **957 SupplyProduct**, все с iiko_id и default_unit_id; все 957 UUID есть в
текущем каталоге. Product mapping: 956 CONFIRMED, 37 CONFLICT, 1 UNMAPPED.
Confirmed missing target / iiko_id disagreement — 0/0. Unit mapping: 5 CONFIRMED,
5 IGNORED; расхождений default_unit с confirmed unit mapping в существующем
active staging join не найдено (это не гарантия для всех новых source records).
11 source name-collision groups пересекаются с существующими normalized names EOS.
Последний existing full-reference sync от 29.09: PARTIALLY_SUCCEEDED,
records_received=11 427, records_failed=1, IIKO_CONTRACT_ERROR. Он не запускался.

Классификация бизнесом **не утверждена**. DISH — candidate готовых изделий;
GOODS требует отделить сырьё, упаковку и перепродажу по подтверждённым ID/group
правилам; PREPARED — отдельно проверить продаваемые исключения. OUTER/SERVICE/
MODIFIER не публиковать автоматически. `deleted=false` и defaultIncludedInMenu
не являются EOS-статусом. У 227 DISH menu-default true=54, false=173.
Initial decision recommendation: staging/UNASSIGNED до Q01/Q03; это предложение,
не утверждённое назначение статуса и не запись в EOS.

## P03 — цены по точкам

E022/E026/E094: период **[01.10, 15.10.2026)**, все доступные departments,
includeOutOfSale=true, оба вида приказов. 4 067 916 bytes, 1.4008 s,
7 483 product×department×size contexts, 7 533 intervals, 1 724 product UUID,
9 внешних departments. 44 истёкших интервала, 6 scheduled, 550 с категориями;
будущих интервалов в этом окне нет. Cancellation flag в ответе отсутствует;
проверка отменённых приказов и будущих естественных примеров **не выполнена**.

На 08.10 current BASE: 7 483 contexts; included=2 481, excluded=5 002.
Разных базовых цен внутри одного department/product/size context не найдено.
Для 34 product/size pairs цены различаются между departments. Schedule/category
priority отдельно не принят за доказанную effective price.

Только 3/9 внешних departments имеют существующие подтверждённые EOS links;
остальные по названию не сопоставлялись. Они же — 3 активных RETAIL_POINT EOS.
Это техническая выборка, а не назначение бизнес-пилота.

| Point key | Included BASE contexts всех типов | Из 227 неудалённых DISH с included BASE |
|---|---:|---:|
| a8e0fe727d8767fd | 453 | 130/227 |
| 3a07d3cba88939eb | 471 | 160/227 |
| ed50118e82269ba9 | 415 | 130/227 |

67/227 DISH без такой цены на всех трёх точках. Один неудалённый DISH имеет разные
цены: key `41cf55b4ea7aca0b`, основная единица «порц», BASE **120 / 150 / 120**
в порядке таблицы, на 08.10.2026. Currency в API отсутствует: RUB не назначена.
Tax category/context присутствуют, но независимая iikoOffice сверка и правила
scheduled/category/cancelled **missing**. Q04 не закрыт; defaultSalePrice не fallback.

## P04 — фото

E075/E087–E093: reference coverage **10/9 815 (0.102%)**, active **0/4 247**.
10 references относятся к удалённым продуктам (9 DISH, 1 PREPARED), всего
**2 уникальных image UUID**; у groups фото-UUID тоже нет (0/823).
Download/decode coverage: **2/2 уникальных IDs**, оба SUCCESS, id matches,
валидный JPEG **450×600**, decoded sizes **49 617 и 54 116 bytes**.
Один image UUID используется девятью product UUID: наличие связи не подтверждает
визуальную правильность фото для каждого изделия.

Реальный JSON — result/errors/response{id,data}; плоский пример документации
не совпадает с envelope. Первоначальные IMAGE_ERROR и IMAGE_REPEAT bytes=0 в
evidence — ошибка диагностического разбора этой обёртки, **не отсутствие медиа**.
Она исправлена; E090/E093 — итоговые decode результаты. Четыре повторных чтения
одного image ID дали одинаковый body SHA-256, но ETag/Last-Modified отсутствуют.
Stale reference не наблюдалась; разные форматы/размеры и изменение image ID
не доказаны. Рекомендация K4: ID-based allowlist loader, content-hash cache,
явный missing; локальные фото/разметку согласовать отдельно. Не обещать
incremental media и не переносить deleted-фото на изделия по названию.

## P05 — ТТК, единицы и ручное разложение

E024/E027/E075/E084–E086/E098: getAll для **[08.10, 09.10)**,
includeDeletedProducts=true, includePreparedCharts=false.
**5 684 карты / 5 684 product UUID**, 10 482 738 bytes, 0.5035 s.
Missing root/ingredient UUID refs — 0/0; **19 710 ingredient references**,
из них 2 684 к deleted products, 1 901 к product с нулевым unitWeight.
В графе всех текущих recipe edges циклов не обнаружено.

**513/5 684** карт пустые; выход assembledAmount везде положительный.
Nested roots=3 439; ASSEMBLE=5 067, DIRECT=617; COMMON=5 661, SPECIFIC=23.
227/227 active DISH имеют карту, но **5/227 карты пустые**; nested=177,
ASSEMBLE=203, DIRECT=24. Наличие карты не означает её годность к производству.

| Root key | Tree charts | Prepared source rows | Ручной итог после объединения одинаковых ингредиентов | Сравнение |
|---|---:|---:|---:|---|
| 0fe9c49207fc22e1 | 1 | 0 | 0 | Пустая карта; пригодность отсутствует |
| 17bb02b0dcf99eb0 | 5 | 11 | 11 | 0 differences выше 0.000001 |
| 9c846c0569dd5b06 | 12 | 21 | 22 ключа в техническом сравнении | 0 differences выше 0.000001 |

Ручное Decimal-разложение: 1 root unit / assembledAmount, затем amountIn ×
factor; recursively expand заготовки с учётом DIRECT, COMMON и storeSpecification
для подтверждённой точки `3a07d3cba88939eb`. Полученные количества совпали с
prepared data. В третьем примере 21 — число исходных prepared rows, а 22 — число
ключей после сравнения объединённых словарей с дополнением отсутствующих ключей
нулём. Это особенность диагностического сравнения, не доказательство наличия
22 ненулевых ингредиентов. API samples запрошены без departmentId (union scope);
ручная фильтрация по точке не заменяет live single-point и Office acceptance.
Расчёт и trace сохранены. History вернул по одной версии на каждом из трёх
samples; пример реально изменявшегося рецепта/удалённой версии не найден.

Контракт **amountIn/amountMiddle/amountOut — основные единицы ингредиента**;
amountIn1/Out1…3 — kg проработок. Prepared amount относится к одной основной
единице блюда. UnitWeight нужен только для подтверждённых переводов массы;
amountIn нельзя молча считать kg. GetPrepared отражает списание: DIRECT может
остаться конечной заготовкой. Денежной себестоимости эти методы не возвращают.
Независимые 3–5 сверок шефом в iikoOffice отсутствуют; Q06 остаётся открытым.

## P06 — денежная себестоимость

[Официальные определения iikoOffice 9.1](https://ru.iiko.help/article/iikooffice-9-1/topic-3?cm=1&ds=1&gc=1)
дают следующие различия; их применимость к точной установленной server build
и конкретному продукту ещё требует независимой проверки.

| Кандидат | Значение и контекст | Фактичность / ограничение | Live API equality |
|---|---|---|---|
| ССС | Стоимость запасов / количество, отдельно по складу, на системную дату; учитывает приходы и расходы | При отсутствии приходов возможна оценочная стоимость | Не подтверждена |
| СПП | Стоимость последнего прихода, включая влияющие на запасы документы | Без приходов значение не определено; не только закупочная накладная | Не подтверждена |
| ССН | Сумма норм ТТК × ССС ингредиентов | Оценочный ингредиент делает итог оценочным | Не подтверждена |
| ССНПП | Нормы ТТК × СПП ингредиентов | Возможен оценочный fallback; по документации метод по умолчанию выключен | Не подтверждена |

Наличие/значение настройки ССНПП не проверялось, настройки не менялись.
`estimatedPurchasePrice` — оценочный source атрибут, **не фактический cost**.
Balance/stores предоставляет amount/sum запасов на дату; их отношение не доказывает
стоимость актуального рецепта и не выбирается как автоматический fallback.

E052–E057: SALES OLAP columns доступны (279 полей), включая
`ProductCostBase.ProductCost` и `ProductCostBase.OneItem`, оба MONEY.
Read-only POST `/api/v2/reports/olap`, buildSummary=false, 6 полей, одна
подтверждённая точка, **[07.10, 08.10.2026)**: 200, 16 605 bytes, 0.872 s,
76 product/unit rows; null=0, nonzero=75, zero=1. Единицы: 66 «шт», 10 «порц».
Это денежный показатель **проданных позиций за период**, не доказанная стоимость
каждой текущей карточки/ТТК/склада. Currency/tax basis и соответствие одному из
четырёх методов не доказаны. Повторная API-сверка не независима.

**Рекомендованный источник для текущей карточки: не подтверждён.** Q05 остаётся
открытым; Q15 — отдельное решение владельца о gate K при отсутствии cost.
Кандидат SALES OLAP можно отдельно исследовать для historical sold-cost context,
с бухгалтерской сверкой и явным разделением с current-recipe cost.

## P07 — обновления и полнота

E058–E061: price revisionFrom и chart getAllUpdate живые. Первые snapshots
revision=**16 365 164**; delta reads вернули **16 365 166** и пустые changes.
Это подтверждает корректный формат пустого delta при продвижении общей ревизии;
реальные изменения, deletion и A→B→A **не доказаны**. Официальный контракт ТТК
указывает ограничения deletion replication для старых iikoRMS; точную применимость
к установленному серверу необходимо подтвердить.

Каталог: официальный GET list не описывает since/revision/cursor/pages;
подтверждён безопасный full snapshot path. Новый product UUID по сравнению со
старым staging не определяется только разностью счётчиков; incremental catalog
не заявляется. Фото: ID/hash observation, валидаторов не наблюдалось.
Предложение: отдельный successful observation manifest и current pointer;
hash-dedup хранения не заменяет «текущее наблюдение». Partial/error не публикует
новую current projection, отсутствие в partial не считается удалением;
source deleted сохраняется как признак с историей. Cursor обновлять только после
полной успешной транзакции того же scope. В этом R0 никакие cursors не записаны.

## P08 — нагрузка, ограничения и безопасность

E099: **25 измеренных GET**, все 200, суммарно **34 494 319 bytes / 8.3652 s**.
Latency в выборке: min=0.0800, median=0.1248, max=1.4008 s.
Дополнительно один измеренный OLAP POST (16 605 bytes / 0.872 s), homepage GET,
auth/logout и **два прерванных full-catalog GET** с body >16 MiB каждый.
Итого API/auth/home/report operations: **31**; верхние bytes/time прерванных
ответов не сохранены, поэтому 34.49 MB нельзя выдавать за общий трафик исследования.
Сначала защитный лимит каталога был слишком мал; второй диагностический read
также упёрся в него. После явного ответа владельца выполнен один full GET с
cap 128 MiB. Автоматических retries, burst или стресс-теста не было.

[Официальные ограничения iikoServer](https://ru.iiko.help/article/api-documentations/ogranicheniya-i-rekomendatsii?cm=1&ds=1&gc=1):
последовательные запросы, периоды не более месяца (предпочтительно день/неделя),
OLAP buildSummary=false и не более 7 полей. Cloud API limits не переносились
на этот Server API. [Auth lifecycle](https://ru.iiko.help/article/api-documentations/avtorizatsiya?cm=1&ds=1&gc=1)
занимает license slot до logout; slot count не установлен. Не держать сессию
во время ожидания человеческих решений в будущем scheduled flow.

Sales schedule — каждые 15 минут; reports — 08:00; существующие Supply schedules
00:01/00:10 по дням. Worker/scheduler heartbeat свежий, poll=1 s; scheduler failed=0.
Из существующего кода shift loop default=300 s; фактический env override worker
не снят. Aggregate iiko concurrency между worker/shift/manual clients и внешними
интеграциями не измерен; lock клиента не доказывает глобальный lease.

Одно Docker stats наблюдение: API 740.3 MiB/0.14% CPU, worker 116.4 MiB/0.54%,
EOS PostgreSQL 854.8 MiB/0.22%; общий Docker memory ceiling 3.786 GiB.
Это instant sample после исследования, не нагрузочный baseline/peak proof.
EOS DB ~614 MB. Container filesystem free ~1.014 TB — thin virtual filesystem;
это **не подтверждённая ёмкость Windows physical disk, media volume или backup**.
Media currently 2 distinct decoded assets / 103 733 bytes; growth новой базы по
этому deleted-only sample прогнозировать нельзя. Retention/quota и recovery
path существующих backups не проверены; во время read-only R0 backup не создавался.
Один каталог+price+current-chart raw JSON snapshot составляет 33 550 068 bytes;
30 ежедневных полных копий — около 1.01 GB до индексов, JSON/DB overhead и новых
фото. Это арифметическая оценка хранения, не согласованная retention policy.

Начальные **предложения, требующие согласования**: concurrency=1 с общим lease
для iiko читателей, timeout=30 s, retries=0 на пилоте; catalog cap=128 MiB,
recipe/price cap=16 MiB, photo JSON cap=4 MiB. Full catalog — вручную/один раз
в согласованное off-peak окно; daily cadence обсуждать после pilot monitoring.
Price/chart delta — обсуждать интервал 30 min вне Sales slot, без автоматического
включения расписания. Stop: 429/license errors, body cap, timeout, влияние на sync;
soft review threshold >5 s на аналогичный catalog/price/chart read — предложение
из наблюдаемого max, не SLA. По 200 ответам безопасная длительная cadence не доказана.
На K6 нужны measured global concurrency, реальные изменения/deletions, quotas,
lease/recovery, backup/restore и выключение нового reader без удаления истории.

## Q/gates и рекомендация K1

| Вопрос | Результат R0 |
|---|---|
| Q01 publication/status | Не закрыт: начальные статусы/сетевой scope решает владелец; рекомендуемый initial staging |
| Q02 access | API reads доступны; бизнес capability/scope/field grants не утверждены |
| Q03 classification | Полный source inventory и conflicts есть; owner/chef ID-rule и exceptions отсутствуют |
| Q04 prices | Контракт/3 links/различия подтверждены; Office equality, future/cancelled/priority/unit/currency open |
| Q05/Q15 cost | Денежный OLAP-кандидат найден; current factual cost и business exception не подтверждены |
| Q06 recipes | 4 метода, coverage, три ручных сравнения есть; chef Office acceptance missing |
| Q07 identity | Name uniqueness несовместима с source collisions; target schema decision не утверждён |
| Q08 source/sync | Один наблюдаемый configured source и безопасный full read подтверждены; delta/deletion/load частично |
| Q09/Q10 media/attributes | Источник фото доступен, active coverage=0; storage/quotas/local fields требуют решения |

**K1 рекомендован как следующий слайс после решений Q01–Q03/Q07/Q08. Разработку
и массовый импорт сейчас не начинать.** Рабочий минимум: approved UUID subset,
каталог/карточка, unit и проверенный unitWeight, явные missing price/photo/cost,
read-only EOS status и backend field guards. Candidate universe — 227 active DISH,
но он не утверждённый ассортимент; GOODS-перепродажу/продаваемые PREPARED решает
бизнес. Пилот должен включать пары одинаковых названий и zero-weight cases.

Q07 нельзя закрыть простым добавлением profile 1:1: `SupplyProduct` имеет unique
tenant+normalized_name и обязательную default_unit; create/update service также
отвергает duplicate name. Mapping использует name/alias candidate sets, Sales
сохраняет source UUID и nullable SupplyProduct FK. Нужен согласованный вариант:
целевая UUID identity с ограниченным изменением name uniqueness/ambiguous
name resolution и регрессией Supply, **либо** обоснованная альтернативная canonical
identity с явными ID links и сохранением existing Sales/Supply FK. Предпочтение
existing SupplyProduct/profile сохраняется только после этой проверки, не ценой
склейки UUID, добавления суффиксов к display name или fake unit.

Потенциальные K1 migrations: profile/observation/projection/current manifest;
изменение name uniqueness — только отдельным согласованным scope. GET list/detail
из EOS DB, background source import через existing adapter; без сети в UI request
path. Никаких API/DB changes в R0. K3/K4/K5/K6 gaps не включать скрыто в K1.
До реализации владельцу нужен конкретный approved ID-rule/pilot, publication
policy, access matrix и identity/migration decision; independent Office comparisons
передаются владельцам цены/рецепта/cost. Открытые вопросы не помечены закрытыми.

## Проверка артефактов и состояние репозитория

Проверены: 9 815 CSV rows / unique product keys, 40 contiguous export blocks,
type/deleted totals, 666 collision groups / 103 active groups, group coverage
denominators, JSON/CSV parsing, SHA-256 manifest, отсутствие UUID/raw credentials
в сохраняемых evidence, `git diff --check`. Code tests/build не запускались:
изменений исполняемого кода/API/schema нет.

Local git status после работы: только новый R0 report и
`output/stage3_2_r0/`; прежний checkout был clean. Полный отчёт/артефакты не staged.
Commit/push/merge/deploy не выполнялись. Следующий шаг — review R0 и отдельное
утверждение K1; после reconnaissance работа остановлена.
