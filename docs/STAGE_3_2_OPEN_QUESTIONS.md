# EnterpriseOS — Stage 3.2: решения, вопросы, допущения и риски

**Версия:** 0.1.0 · **Дата:** 08.10.2026 · **Статус:** реестр на review.
Бизнес-решения D01–D08 находятся только в
[спецификации](STAGE_3_2_PRODUCT_KNOWLEDGE_AND_PRODUCTION_SPEC.md#3-подтверждённые-бизнес-решения).
Проверенные компоненты/ограничения — в [архитектуре](STAGE_3_2_ARCHITECTURE.md).
Проверки Pxx — в [плане разведки](STAGE_3_2_PRODUCTION_RECONNAISSANCE_PLAN.md).
Предлагаемые владельцы ниже — роли для согласования, не назначенные люди.
Все Q открыты на дату документа; сроки/ответственные лица назначаются на review.

## 1. Вопросы, блокирующие отдельные слайсы

| ID | Вопрос и безопасное поведение пока не решён | Требуемое доказательство/решение | Предлагаемый владелец | Блокирует |
|---|---|---|---|---|
| Q01 | Статус сетевой или по точке? Как впервые назначить один из двух статусов существующим/новым изделиям? До решения только staging, no production eligibility | Решение о scope, первоначальной публикации и новых UUID; iiko menu/deleted не источники статуса | Владелец, NETWORK_MANAGER | K1/K2 |
| Q02 | Кто читает/меняет ассортимент, цены, локальные знания, cost/full recipe? Где раздел «Продукция» в навигации? Новые grants deny-by-default | Подписанная матрица capability × scope × field; canonical roles; review proposed routes | Владелец, DIRECTOR/DEPUTY_DIRECTOR | K1 и все write/sensitive slices |
| Q03 | Что считается готовой продукцией «Эклер»: закупная перепродажа, полуфабрикаты, услуги, модификаторы? Не выбирать по имени | Полная P02 классификация и утверждённое versioned правило по IDs/types/groups + исключения | NETWORK_MANAGER, CHEF_CONFECTIONER | K1 |
| Q04 | Как выбирать цену по точке/дате/приказам и единице? При конфликте/unknown показывать отсутствие | P03 contracts + independent iikoOffice comparison: dates/timezone/priority/cancelled/future/unit/currency; point mapping | NETWORK_MANAGER, ACCOUNTANT | K3 |
| Q05 | Доступен ли фактический денежный cost? Каковы определения ССС/СПП/ССН/ССНПП и область применения? Никакой подмены закупочной оценкой | P06: официальное описание установленной версии, API/report rights, method/period/store/unit/tax, independent iikoOffice equality | ACCOUNTANT, CHEF_CONFECTIONER | Денежная часть K5 и cost analytics; gate K по Q15 |
| Q06 | Какая ТТК действует для даты/точки, выход, потери, единицы/полуфабрикаты, tree vs prepared? Неполный рецепт не пригоден для расчёта | P05: sample/history/versioned recipe, unit conversions, cycles, ручная сверка выхода/ингредиентов; решение источника при unavailable API | CHEF_CONFECTIONER, HEAD_OF_PRODUCTION | K5, gate K, P2 |
| Q07 | Можно ли расширить SupplyProduct как canonical identity при одинаковых именах и required unit? Как устранить iiko_id vs confirmed mapping conflict? Конфликт остаётся unresolved | P02 distribution + local consumer review parser/alias/mapping/Sales/Supply; конкретная schema decision и безопасный migration/backfill plan | Разработка, владелец | K1 |
| Q08 | Один ли iiko source на tenant? Есть ли delta/cursor/deletion contract? Как подтвердить current observation A→B→A? Unknown не продвигает cursor | P01/P07: source scope, completion manifest/pointer design, lease/recovery и измеренный sync budget | Разработка, ADMIN | Identity K1; incremental/schedule K6 |
| Q09 | Photo format/ID/coverage, cache quota/retention, persistent storage/backup, local override? Не выдавать remote credential URL | P04/P08; storage topology read-only inspection, согласованный cache lifecycle и безопасная file выдача | Разработка, ADMIN, владелец | K4/K6 |
| Q10 | Какие сведения обязательны и кто проверяет состав/аллергены/хранение/обучение? Пустые данные ≠ отсутствие аллергенов | P02/P05 coverage + content ownership/publication decision и примеры локального дополнения | CHEF_CONFECTIONER, NETWORK_MANAGER | K4; content acceptance K |
| Q11 | Горизонт прогноза, статистический метод, stockouts/seasonality, сроки годности, минимальные партии/мощность? Продажи не равны спросу/выпуску | После K: реальные examples, source units/coverage/freshness, формулы и измеримая baseline accuracy; сначала объяснимая рекомендация | HEAD_OF_PRODUCTION, NETWORK_MANAGER | P0/P1/P2 |
| Q12 | Как определяется собственная точка/shift/window производственной заявки и подмена? TEMPORARY Supply fallback не наследовать | Отдельное решение scope/context policy + подтверждённые ID mappings; review existing authorization/Regulatory Tasks | Владелец, NETWORK_MANAGER | P0/P1 |
| Q13 | Подтверждение продавцом, замещение шефа, corrections/cancel после approval, выведенное изделие в старом плане? Не отменять молча | После K: lifecycle/ответственность/delegation и конкурентные сценарии; reasons/revisions; отказ override по умолчанию | Владелец, CHEF_CONFECTIONER | Production P0/P1/P2; K2 задаёт только независимый status |
| Q14 | Источники пригодного stock, confirmed expected deliveries, выпуска/списания; production→Supply source и дельты reserved needs? Никакого фиктивного REQUEST_LINE | После K: source evidence, unit/date/lot scopes, idempotency/FK/version contract и genuine integration path; no double reservation | SUPPLY_MANAGER, HEAD_OF_PRODUCTION, разработка | P0/P2/P3/P4 |
| Q15 | Допустима ли приёмка базы без денежной себестоимости при unavailable P06? Нет молчаливого исключения | Отдельное решение владельца: явный missing, запрет cost analytics, дальнейший owner/срок; ТТК годность всё равно обязательна | Владелец проекта | Gate K, если Q05 не закрыт |

## 2. Допущения (не подтверждённые факты)

| ID | Предложение/допущение | Как проверить / последствие отрицательного результата |
|---|---|---|
| A01 | Профиль 1:1 поверх SupplyProduct минимизирует дубли и сохраняет Sales/Supply FK | Q07; при несовместимости оформить альтернативу с явными ID links и migration impact до K1 |
| A02 | Для первой версии статус сетевой, цены по точкам | Q01/Q04; per-point assortment увеличит cardinality/API/UX, потребуется update proposal до K2 |
| A03 | Часть атрибутов карточки доступна iiko read-only | P02/P04/P05; нет атрибута → nullable/local verified field, а не выдуманный source факт |
| A04 | Допустим bounded full snapshot, если delta отсутствует | P07/P08; при недопустимой нагрузке согласовать другой read/report source и объём пилота |
| A05 | Sales reconciled quantities пригодны для product forecast | Q11: проверка units/returns/coverage и stockouts после K; без этого не строить прогноз |
| A06 | Шеф отвечает за опубликованную технологическую/пищевую информацию | Q02/Q10; назначить реальное ответственное лицо, не считать документ назначением |

## 3. Риски и меры

| ID | Риск / эффект | Мера и критерий контроля |
|---|---|---|
| R01 | API существует в документации, но права/версия/лицензия не дают нужные данные | R0 per-method evidence, unsupported ≠ empty, no fictional contract; блокировать зависимый слайс |
| R02 | Name uniqueness и name matching склеят разные UUID / сломают Supply | Q07, no auto merge; targeted identity/parser regressions и isolated constraints |
| R03 | Raw hash-dedup ошибочно выбран как актуальная версия, partial snapshot уничтожает good data | Manifest/pointer, A→B→A/partial tests, authoritative completion и dated freshness |
| R04 | Sync перезапишет локальный status/контент либо source deleted уничтожит историю | Разделить owners/fields, no delete, transactional race tests и append-only audit |
| R05 | Ошибочная цена/себестоимость из другого point/unit/date вводит бизнес в заблуждение | Контекст каждой суммы, independent iikoOffice checks; null/conflict, запрет estimate substitution |
| R06 | Утечка cost/полной ТТК через detail/history/media/API-cache | Field guards на backend, deny-by-default, sensitive access tests; safe recipe projection |
| R07 | Media download создаёт SSRF/файловые риски/переполняет диск | ID-based loader, allowlist MIME/size/path, tenant auth, quota/backup Q09 |
| R08 | Неполные рецепты/единицы, неверный выход и полуфабрикаты исказят сырьё | P05/Q06, immutable recipe basis, manual calculation и fail closed production handoff |
| R09 | Продажи с поздними возвратами/unknown stockouts исказят прогноз | Reuse reconciliation/completeness, versioned recommendation basis, согласованный Q11 |
| R10 | Повтор передачи новой версии плана удвоит закупку/покрытие | Q14 idempotency/source constraints, locked reservations/delta и reconciliation tests |
| R11 | Исследовательский full-sync или неизвестный RPC случайно пишет бизнес-данные | Только read allowlist/не выполнять sync endpoints, no guessed RPC, separate reconnaissance authorization |
| R12 | Нагрузка от фото/ТТК повредит текущим Sales/shift/Supply sync | Serial bounded pilot, measured budgets P08, independent action disable и worker capacity review |
| R13 | Документация ошибочно принята за готовность или разрешение production | Gates R0/K, отдельные задания, evidence types/local vs business verified и dated status |

## 4. Журнал согласования

08.10.2026: D01–D08 получены из текущего задания. Архитектура/слайсы/новые
grants предложены на review. Разведка не выполнена; все Q открыты. В действующих
документах согласован порядок двух частей; исторические статусы/production
контрольные точки не повышены. Дальнейшее решение записывать с датой, автором,
evidence и ссылкой на Q, затем синхронизировать только профильный документ.
