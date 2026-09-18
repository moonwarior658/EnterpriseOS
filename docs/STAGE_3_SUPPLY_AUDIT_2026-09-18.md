# Stage 3 Supply — evidence audit 18.09.2026

Canonical roadmap: [ROADMAP_STAGE_3_SUPPLY_v0.1.0.md](ROADMAP_STAGE_3_SUPPLY_v0.1.0.md). Это аудит и коррекция документации, не новый параллельный roadmap.

## Current production snapshot — 18.09.2026

- Production baseline, сообщённый владельцем: `f8ab3a355f5ec49f7468e2ff868e1b0e17364a2a`, Alembic `20260917_0056`.
- В этом аудите локально проверено: `HEAD = main = origin/main = baseline`; до правок дерево чистое. Это локальный remote-tracking ref, не новый fetch и не live SSH-проверка production.
- Read-only SSH-проверка 18.09.2026 предпринята дважды, но соединение завершилось `Connection timed out during banner exchange` до авторизации. На Mac ветка `main`; ветка/HEAD/рабочее дерево сервера и live Alembic пока **не проверены**, равенство веток не утверждается. Сервер не изменялся.
- В repo подтверждена непрерывная цепочка migrations до `0056`; миграции в этом аудите не применялись. Production SHA/Alembic и deployment facts ниже опираются на предоставленный baseline, не на новый запрос к серверу.
- В production по baseline: Supplier foundation, Product↔Supplier, price history, PurchaseRequest, ProcurementNeed, allocation/minimum order, SupplierOrder/outbound email, confirmation/deviations/decisions, documents, acceptance/destination/resolutions, payments/settlements, traceability/coverage, supplier↔iiko mapping, incoming invoice readback, base-unit/price/sum contract, receipt lifecycle/accounting facts и cash flow. «В production» относится к реализованному объёму, а не ко всем первоначальным требованиям пункта.
- 3.1C.18: **IMPLEMENTED + DEPLOYED + PRODUCTION_READY; REAL_BUSINESS_SMOKE_PENDING**. Technical iiko contract smoke: **YES**, `EOS-CONTRACT-20260917-001`, UUID `5bf2b1c7-8c91-b774-01a0-ae4cafa53ba1`: `NEW → authoritative UUID → processDocuments → PROCESSED → stock +1`.
- Этот технический документ **не является EOS business receipt**. При deployment production Acceptances = **0**; реальный EOS business receipt **NOT YET PERFORMED**. По остальным 3.1C capabilities deployment не приравнивается к индивидуальному business smoke: отдельные подтверждения сценариев в baseline не приложены.

## Статусы и архитектурные инварианты

`DONE` — реализован описанный operational scope; `DONE_DIFFERENTLY` — результат достигнут другим способом, исходный замысел и остаток сохранены; `PARTIAL` — исходный пункт покрыт частично; `DEFERRED` — явно отложен; `NOT_STARTED` — реализации не найдено; `BLOCKED_EXTERNAL` — подтверждённая внешняя зависимость препятствует работе. `DEPLOYED` и `PRODUCTION_READY` — отдельные оси, не синонимы `BUSINESS_SMOKED`.

P0 — препятствие безопасной эксплуатации; P1 — необходимая проверка/ограничение для доказанного operational completion; P2 — optional/later enhancement; NONE — нет текущего блокера. Приоритет ниже относится к остатку, а не к уже выполненной функции.

EOS хранит бизнес-состояние, расчёты, решения и аудит. Email/печать используют существующий `outbox → AutomationProvider → local n8n → callback`; n8n не имеет прямого доступа к EOS PostgreSQL. iiko receipt фактически вызывает `IikoProvider` из EOS service после сохранения persistent intent; отдельного n8n receipt workflow нет. Это фиксирует существующую реализацию, не меняет ADR-001 и не переносит бизнес-логику из EOS.

Order ≠ confirmation ≠ document ≠ acceptance ≠ payment ≠ accounting fact. HTTP success не равен business success; неизвестный результат требует authoritative reconciliation, без blind retry. Snapshot/tenant/transaction guards сохраняются. Неоднозначные quantity sources не распределяются FIFO/pro-rata, historical iiko invoices автоматически не backfill.

```text
SupplyRequest → ProcurementNeed → PurchaseRequest → SupplierAllocation
→ SupplierOrder → SupplierConfirmation → SupplierDocument → SupplierAcceptance
→ SupplyIikoIncomingReceipt → POSTED iiko accounting fact
→ Payment / Settlement → Cash Flow / Coverage
```

Это схема прослеживаемости, не обязательная временная последовательность: предоплата возможна раньше приёмки; acceptance может начинаться от order/confirmation, но receipt требует документного ценового основания. Payment/Settlement независимы от POSTED. Coverage считает attributable acceptance, accounting facts — только POSTED. Закрытие Acceptance→iiko accounting не меняет границу `INTERNAL_TRANSFER`: он по-прежнему остаётся `NEW`.

Доказательная матрица, аудит полей/вложений и ссылки на исходники приведены ниже.

## Audit matrix — 3.1C.1–3.1C.20

`DEPLOYED*` — реализованный объём по production baseline владельца; новый live audit сервера не выполнялся. Для всех строк, кроме явно указанного технического smoke .18, отдельный business-smoke evidence не предоставлен. Исходный объём сверялся с версией canonical roadmap в `f8ab3a3`, а не восстановлен по новым status labels.

| ITEM | ORIGINAL SCOPE | ACTUAL | PROD | STATUS | GAP | WHY | PRIORITY | Evidence |
|---|---|---|---|---|---|---|---|---|
| 3.1C.1 Справочник поставщиков | Реквизиты, контакты, календарь, минимум и начальные поставщики. | CRUD/archive, display/legal name, ИНН/КПП/ОГРН, адреса, банковские реквизиты, order_email, phone, comment, minimum_order_amount; supplier↔iiko mapping. | DEPLOYED* | PARTIAL | Нет accounting_email, отдельного manager/contact, order/delivery weekdays, lead_time и supplier aliases. Наличие конкретных четырёх стартовых поставщиков в production не проверено. | Foundation введён раньше расширенного supplier master; поля не обязательны для текущего ручного контура. | P2 | E1 |
| 3.1C.2 Товар–поставщик | Основной/резервные, приоритет, название, артикул, фасовка, минимум количества, цена, доступность, архив. | PRIMARY/BACKUP, priority, supplier_product_name, SKU, package quantity/unit, price, availability/unavailable_until и archive; API/UI. | DEPLOYED* | PARTIAL | Нет отдельного minimum quantity; supplier_product_name не является обучаемым supplier-alias workflow. | Фасовка и число упаковок не равны отдельному минимальному количеству заказа. | P2 | E1 |
| 3.1C.3 История цен | Цена упаковки/базовой единицы, размер упаковки, источник, период, поставщик и история. | Append-only snapshots, effective_from, source=MANUAL, автор, нормализация цены к базовой единице; timeline API/UI. | DEPLOYED* | DONE | Автоимпорт прайсов и истории iiko отсутствует; это будущие интеграции. | Источник текущей истории — ручное изменение условий; история фактических приходов хранится отдельно. | NONE | E1 |
| 3.1C.4 Средневзвешенная цена | 6 месяцев, все поставщики, взвешивание по фактически принятому количеству проведённых накладных, коридор ±10%, эскалация. | NOT REQUIRED FOR CURRENT MVP; вычисления нет. | Нет; business deferred | DEFERRED | Отложена целиком; historical iiko invoices автоматически не backfill. | Business decision 18.09.2026: аналитика цены, а не transactional invariant; canonical source появился через POSTED receipt, нужна фактическая история. | NONE | D1 |
| 3.1C.5 Закупочный запрос | Общая потребность на дату из заявок, долгов и будущего спроса, стоимость и покрытие; позднее производство. | SupplyProcurementNeed и collector → PurchaseRequest; явные источники, MANUAL_FUTURE, DRAFT/READY/CANCELLED; стоимость из allocation, coverage отдельным read model. | DEPLOYED* | DONE_DIFFERENTLY | Производственный план/ТТК — Stage 3.2; долг не копируется напрямую в заказ. | Введена canonical ProcurementNeed вместо неявного агрегирования заявок и долгов. | NONE | E2 |
| 3.1C.6 Распределение по поставщикам | Разделять запрос/товар между поставщиками, резервный выбор с учётом цены, фасовки, наличия, сроков, минимума и надёжности. | Ручной выбор eligible primary/backup, split allocation, immutable package/price snapshots, CONFIRMED и явное распределение источников. | DEPLOYED* | PARTIAL | Нет reliability scoring, календарного прогноза и автоматического предложения альтернативного поставщика после отказа. | Окончательный выбор остаётся человеку; текущие цена/фасовка/доступность и минимум видны. | P2 | E2 |
| 3.1C.7 Минимальная сумма заказа | Проверка минимума/недобора, предложение будущей потребности, решение руководства; позднее календарь. | minimum_order_amount, subtotal, MET/BELOW_MINIMUM/NOT_CONFIGURED, shortfall в allocation и SupplierOrder. | DEPLOYED* | PARTIAL | Warning only: недобор не блокирует confirm/READY/send; нет автопредложения будущего спроса и календаря. | Контроль реализован как видимый факт для ручного решения, без случайного добивания заказа и без hard enforcement. | P2 | E2 |
| 3.1C.8 Заказ поставщику | UUID, номер, поставщик, строки, количества/цены/суммы, дата, статусы, история, связь с запросом. | SupplierOrder из confirmed allocations, snapshots, source links, DRAFT/READY/SENT/CANCELLED, API/UI и delivery history. | DEPLOYED* | DONE | Отдельного обязательного хвоста foundation не найдено. | Один заказ имеет одного поставщика; отправка и последующие документы — отдельные факты. | NONE | E3 |
| 3.1C.9 Email | Шаблон, таблица, ответственный/телефон, автоматическое формирование, Automation Core, время/ID и переписка. | Immutable communication preview, outbound text template, delivery attempts, outbox → AutomationProvider → n8n → callback; SENT после success, явный retry FAILED. | DEPLOYED* | PARTIAL | Нет inbound thread/history и inbox ingestion; нет доказательства получения/прочтения адресатом. Детальный outbound production smoke artifact не предоставлен. | История отправок не равна переписке; provider success не означает supplier confirmation. | P2 | E3 |
| 3.1C.10 Подтверждение поставщика | Входящее письмо, связь с заказом, PDF руководителю, ручное совпадает/расхождения; сравнение PDF позднее. | Ручной versioned confirmation, immutable RECORDED, line response, quantity/price/date deviations, решения ACCEPT/REJECT в UI. | DEPLOYED* | PARTIAL | Нет inbound ingestion и PDF attachment. | DONE_DIFFERENTLY для domain confirmation: структурированный ручной ввод вместо обработки входящего PDF. | P2 | E4 |
| 3.1C.11 Замены | Пара товаров и supplier-specific решения, auto-pass после 3 подтверждений, всегда уведомлять; приоритет бесперебойность → история → наличие/срок → цена в пределах 5% → поставщик несущественен. | BUSINESS RULE NOT YET REQUIRED; canonical allowed-replacement model отсутствует. | Нет; business deferred | DEFERRED | Вернуться при требованиях к бренду/марке/спецификации, списку допустимых замен и approval policy. | EOS/iiko product — конкретная номенклатура, supplier — источник. Product↔Supplier не означает замену товара; сущность заранее не строим. | NONE | D1 |
| 3.1C.12 Сокращение количества | Недопоставка, прогноз до следующей поставки, обязательный дозаказ/эскалация, поиск другого поставщика. | QUANTITY_CHANGED/LINE_REJECTED в общей deviation model требуют решения; acceptance shortage/rejected resolution → RETURN_TO_PROCUREMENT создаёт canonical need. | DEPLOYED* | DONE_DIFFERENTLY | Нет прогноза «хватит ли», авто-дозаказа и автоматического поиска альтернативы; возврат из acceptance — явное решение, не автоматизм из confirmation. | Обязательный контроль отклонения реализован общей моделью; прогнозный хвост остаётся PARTIAL/P2. | P2 | E4 |
| 3.1C.13 Перенос даты | Всегда руководителю, старая/новая дата, прогноз остатка/остановки, подразделения и альтернативный supplier. | DELIVERY_DATE_CHANGED, baseline/confirmed date и delta, manager decision в unified deviations. | DEPLOYED* | DONE_DIFFERENTLY | Если baseline date отсутствует, requires_decision=false; нет прогноза дефицита, остановки и автоматических альтернатив. | Сравнение с существующей датой требует решения; первое заполнение даты отличается от исходного «всегда». Аналитический хвост PARTIAL/P2. | P2 | E4 |
| 3.1C.14 Накладные | Номер/дата/поставщик/сумма/НДС/строки/файл, сверка, несколько документов на закупку. | Domain document DONE: INVOICE/DELIVERY_NOTE/UPD, metadata, lines/pricing basis, financial_role, immutable RECORDED; order/confirmation/acceptance links, несколько документов. | DEPLOYED* | PARTIAL | Нет binary attachment, отдельных VAT fields и полного статуса трёхсторонней сверки; один документ относится к одному order. | Структурированный операционный документ не является PDF или налоговым регистром. | P2 | E5 |
| 3.1C.15 Оплаты | Отдельная оплата, частичные/несколько оплат, пред-/постоплата, просрочка, поручение, комментарий и история. | Domain payment DONE: RECORDED facts, payment amount/date, pre/postpayment, payment-order number/date, comment; explicit allocations, overdue при известном due date. | DEPLOYED* | PARTIAL | Нет файла поручения/proof; даты платежа не назначаются догадкой; банковской интеграции нет. | Метаданные поручения реализованы, binary proof — отдельное optional enhancement. | P2 | E6 |
| 3.1C.16 Взаиморасчёты | Документы/оплаты/возвраты/корректировки, долг/просрочка, движение и внутренний акт, финансовые исключения. | ACTIVE obligation + один RECORDED PAYABLE, payment allocations/reversal, refunds/corrections, statement, debt/overpayment/unallocated prepayment и exceptions. | DEPLOYED* | DONE | Не бухгалтерский акт/ledger; duplicate safeguards и exceptions не доказывают отсутствие любого возможного повторного банковского платежа. | Явные связи предотвращают повторный учёт одного обязательства; никаких guessed allocations. | NONE | E6 |
| 3.1C.17 Приёмка | Ordered/confirmed/documented/received/rejected/accepted/accounted, план/факт и исключения. | Acceptance + destination mapping, shortage/rejected/excess issues и resolutions; accounted_quantity/accounted_sum из POSTED receipt. | DEPLOYED* | DONE | Полный business smoke с реальной EOS acceptance ещё не выполнен; данные при deployment: Acceptances=0. | Прежний BLOCKED_BY_3_1C_18 закрыт кодом lifecycle 18F; recorded acceptance сама не является accounting fact. | P1 | E7 |
| 3.1C.18 Приход iiko | Создать приход через provider, подтвердить iiko, обновить остатки, показать ошибку; HTTP ack недостаточен. | IMPLEMENTED + DEPLOYED + PRODUCTION_READY: DRAFT→READY→CREATING→CREATED→PROCESSING→POSTED, reconciliation, authoritative UUID/PROCESSED, accounting facts, UI. | DEPLOYED*; PRODUCTION_READY; real smoke pending | DONE | REAL_BUSINESS_SMOKE_PENDING; общий Dashboard ошибок — Stage 3.3. Только safe base-unit contract; package conversion/сервисы/неоднозначные суммы не допускаются. | Технический contract smoke доказан отдельно; stock refresh выполняет GET, но не сохраняет новый EOS staging snapshot. | P1 | E8 |
| 3.1C.19 Товарное покрытие | Full/partial/not covered, with substitutions/delay, незакрытые позиции; недозакупка не экономия. | Явные allocation/order/acceptance sources; FULLY_COVERED/PARTIALLY_COVERED/NOT_COVERED, UNKNOWN_LEGACY, MANUAL_FUTURE отдельно, has_delay и uncovered count. | DEPLOYED* | DONE_DIFFERENTLY | Нет COVERED_WITH_SUBSTITUTIONS; delay — отдельный флаг, только при полном покрытии и recorded_at позже need_date. | Coverage основан на attributable RECORDED acceptance, не POSTED и не оплате; substitutions deferred, FIFO/pro-rata и legacy guessing запрещены. | NONE | E9 |
| 3.1C.20 Денежный поток | План/заказ/подтверждение/документ/принято/оплачено/долг/исключения, видимая потребность. | Read model supplier/request: planned, ordered, confirmed, payable documented, accepted, gross/net paid, refunded, debt/overdue, variances и exceptions; API/UI. | DEPLOYED* | DONE | Не accounting ledger и не прогноз банковской ликвидности; UNAVAILABLE/null при недостаточных фактах. | Использует snapshots и canonical settlement; не скрывает need/coverage и не называет недозакупку экономией. | NONE | E10 |

## Evidence index: code, UI, tests, migrations, git

Тесты ниже изучены как evidence наличия проверок; они не объявляются заново выполненными и не заменяют live PostgreSQL/production smoke. Общая модель: [supply.py](../backend/api/app/models/supply.py); API contracts: [schemas](../backend/api/app/schemas/supply.py), [Supply routes](../backend/api/app/api/routes/supply.py). Revision identifiers ниже — хвосты полных Alembic revision IDs, а не номер произвольного шага.

- **E1** — `4eb2db7`, `f14b227`; migrations 0035–0037, 0042, 0055. [Backend](../backend/api/app/models/supply.py), [tests](../backend/api/tests/test_supply_product_suppliers_api.py), [UI](../frontend/src/pages/SupplySuppliersPage.tsx). Supplier/product-supplier/price history; supplier mapping: app/integrations/iiko/supplier_mapping_service.py; test_iiko_supplier_mapping.py; SupplierIikoMappingPanel.
- **E2** — `aa375e9`, `56bd44e`, `670b650`, `f282566`, `a10ed0a`; 0038–0042. [Backend](../backend/api/app/supply/purchase_allocations.py), [tests](../backend/api/tests/test_supply_purchase_requests_api.py), [UI](../frontend/src/pages/SupplyPurchaseAllocationWorkspace.tsx). Также procurement_needs.py, purchase_requests.py; test_supply_purchase_requests_postgres.py и test_supply_supplier_minimum_order_postgres.py.
- **E3** — `9d47244`, `2ac8058`, `360e7dd`, `48d56fb`; 0043–0045. [Backend](../backend/api/app/supply/supplier_order_delivery.py), [tests](../backend/api/tests/test_supply_supplier_order_email_postgres.py), [UI](../frontend/src/pages/SupplySupplierOrderDetailPage.tsx). supplier_orders.py хранит message snapshot; email attempt retries только после FAILED, общий Automation Core обрабатывает доставку; callback фиксирует SENT, не read receipt.
- **E4** — `b81f556`, `2bf36d8`, `3c31f6b`; 0046–0048. [Backend](../backend/api/app/supply/supplier_confirmations.py), [tests](../backend/api/tests/test_supply_supplier_confirmations_postgres.py), [UI](../frontend/src/components/SupplierConfirmationPanel.tsx). QUANTITY_CHANGED, PRICE_CHANGED, DELIVERY_DATE_CHANGED, LINE_REJECTED; price increase >10% относительно order требует решения; .12/.13 используют общую модель.
- **E5** — `3c31f6b`, `85d72f3`; 0048/0053. [Backend](../backend/api/app/supply/supplier_documents.py), [tests](../backend/api/tests/test_supply_supplier_documents_postgres.py), [UI](../frontend/src/components/SupplierDocumentsPanel.tsx). PAYABLE/SUPPORTING/NON_FINANCIAL, obligation links и pricing basis; файла/НДС полей в domain document нет.
- **E6** — `85d72f3`; 0052–0053. [Backend](../backend/api/app/supply/supplier_settlements.py), [tests](../backend/api/tests/test_supply_supplier_settlements.py), [UI](../frontend/src/components/SupplierSettlementPanel.tsx). supplier_payments.py; test_supply_supplier_payments.py, postgres suites; SupplierPaymentsPanel и SupplySupplierPaymentsPage.
- **E7** — `faf129c`, `09f9c46`, `f8ab3a3`; 0049–0051/0056. [Backend](../backend/api/app/supply/supplier_acceptances.py), [tests](../backend/api/tests/test_supply_supplier_acceptances_postgres.py), [UI](../frontend/src/components/SupplierAcceptancesPanel.tsx). RETURN_TO_PROCUREMENT, documented-first excess, destination mapping; _line_read суммирует accounted только POSTED; UI отображает accounted quantity/sum.
- **E8** — `6c53450`, `49a9314`, `f8ab3a3`; 0055–0056. [Backend](../backend/api/app/supply/iiko_incoming_receipts.py), [tests](../backend/api/tests/test_iiko_incoming_receipt_lifecycle.py), [UI](../frontend/src/components/SupplierAcceptancesPanel.tsx). incoming_receipt_readiness.py, IikoProvider/client, app/api/routes/iiko_incoming_receipts.py; test_incoming_receipt_readiness.py, test_iiko_incoming_receipts_postgres.py: cycle/constraints/immutability/concurrency. Последний проверенный repo head 0056.
- **E9** — `6c53450`; 0054. [Backend](../backend/api/app/supply/purchase_requests.py), [tests](../backend/api/tests/test_supply_quantity_traceability_postgres.py), [UI](../frontend/src/pages/SupplyPurchaseRequestDetailPage.tsx). get_purchase_request_coverage; allocation/order/acceptance source models, ручное multi-source distribution, UNKNOWN_LEGACY без догадок.
- **E10** — `6c53450`. [Backend](../backend/api/app/supply/procurement_cash_flow.py), [tests](../backend/api/tests/test_supply_procurement_cash_flow.py), [UI](../frontend/src/components/ProcurementCashFlowSummary.tsx). Supplier и purchase-request scope, canonical settlements, acceptance value; нет отдельной ledger migration.
- **D1** — явные business decisions владельца в задании на аудит от 18.09.2026, закреплены в canonical roadmap и дополнении к спецификации.

## Stage 3.0 / 3.1A / 3.1B: по каждому официальному пункту

Production 3.1A от 02.08 и 3.1B от 23–24.08 подтверждён существующими статусными документами, не повторным smoke этого аудита. Sources: [ADR-002](ADR-002_SUPPLY_DOMAIN_MODEL.md), [Supply model](../backend/api/app/models/supply.py), [service](../backend/api/app/supply/service.py), [public service](../backend/api/app/supply/public_service.py), [parser](../backend/api/app/supply/parser.py), [Automation actions](../backend/api/app/automation/supply_actions.py), [stock calculation](../backend/api/app/supply/stock_calculation.py), [iiko documents](../backend/api/app/supply/iiko_documents.py), [routing](../backend/api/app/integrations/iiko/document_routing.py), [printing](../backend/api/app/supply/printing.py), [Dashboard](../frontend/src/pages/DashboardPage.tsx). Тесты: test_supply_parser, test_public_supply_api, test_supply_cycles_duplicates_api, test_supply_fulfillment_api, test_supply_iiko_document_workflow, test_supply_printing.

| ITEM | Фактический статус / production scope | Остаток / причина / priority |
|---|---|---|
| 3.0 | DONE: ADR-002 принят; термины, domain/invariants, предварительные permissions, migration strategy и docs | Финальные роли/алгоритмы ADR намеренно не закрывает; NONE |
| 3.1A.1 | PARTIAL: departments model/seed deployed | Admin codes UI отсутствует; P2 |
| 3.1A.2 | DONE_DIFFERENTLY: directions/cycles deployed | Жёсткий календарь заменён configurable schedules; NONE |
| 3.1A.3 | PARTIAL: product catalog, base unit/category/storage, archive, iiko mapping и aliases deployed | Supplier name/SKU есть позднее .C.2, полноценный supplier-alias workflow нет; P2 |
| 3.1A.4 | DONE: editable EOS categories deployed | Не передаются в iiko; NONE |
| 3.1A.5 | DONE: storage zones deployed | NONE |
| 3.1A.6 | DONE: public form, raw lines/quantity/unit deployed | Неизвестные значения сохраняются для ручного разбора; NONE |
| 3.1A.7 | DONE: parser/normalization supported formats deployed | Не универсальное понимание произвольного ввода; NONE |
| 3.1A.8 | PARTIAL: alias enums deployed | Нет contextual unknown-unit clarification/candidate workflow; P2 |
| 3.1A.9 | PARTIAL: manual matching/approved aliases/conflict checks deployed | Нет candidate queue и полного approval scope UI; P2 |
| 3.1A.10 | NOT_STARTED: таймеры проверки 5/10 минут | Automation cycle timing не заменяет таймер редактирования; P2 |
| 3.1A.11 | DONE: uniqueness department/direction/cycle deployed | NONE |
| 3.1A.12 | PARTIAL: optimistic version protection deployed | Нет полноценного временного edit lock; P2 |
| 3.1A.13 | DONE: duplicate protection deployed | NONE |
| 3.1A.14 | DONE: business numbering deployed | Поиск в чатах — later; P2 |
| 3.1A.15 | DONE: request list deployed | NONE |
| 3.1A.16 | DONE: manual supply workbench deployed | NONE |
| 3.1A.17 | PARTIAL: dept/product/unit debts persisted, overfulfillment supported | Отдельное погашение старого долга через signed transfer не реализовано; P2 |
| 3.1A.18 | PARTIAL: recurring yellow/red signals deployed | Tooltip UX отсутствует; P2 |
| 3.1A.19 | DONE: requested/actual/debt plan-fact deployed | NONE |
| 3.1A.20 | DONE: initial requests/mapping/debt Dashboard deployed | Не весь Stage 3.3; NONE |
| 3.1B.1 | DONE: provider/read access deployed | NONE |
| 3.1B.2 | PARTIAL: references/products/units/packages/warehouses/mapping deployed | Нет общего enterprise и fallback Excel import; P2 |
| 3.1B.3 | PARTIAL: immutable stock snapshot/manual sync deployed | Нет Supply stock schedule/stale UX; P2 |
| 3.1B.4 | DONE_DIFFERENTLY: stock calculation deployed, долг после actual finalization | Stock deficit → ProcurementNeed отдельно от debt; NONE |
| 3.1B.5 | DONE_DIFFERENTLY: explicit production routes deployed | Generic enterprise resolver и расширение маршрутов отсутствуют; P2 |
| 3.1B.6 | PARTIAL: SOURCE/flow grouping deployed | Нет отдельной persistent document-line relation; P2 |
| 3.1B.7 | PARTIAL: document intents/UUID/number/status/request/version deployed | Отдельная line-level relation и signed physical transfer отсутствуют; P2 |
| 3.1B.8 | DONE: persistent intent/provider/authoritative readback deployed | INTERNAL_TRANSFER NEW остаётся принятой границей; NONE |
| 3.1B.9 | DONE: canonical verified PDF deployed | NONE |
| 3.1B.10 | DONE: persistent Print Agent/copies=2/idempotency deployed | NONE |
| 3.1B.11 | PARTIAL: outbox/n8n/callback/reprint/history deployed, физическая печать подтверждена | Нет общего Dashboard print exception; P2 |
| 3.1B.12 | DONE: operational completion actual→debt→terminal deployed | Signed-return и old-debt coverage вне scope; P2 |

## Scope decision / Deferred by business decision — 18.09.2026

**3.1C.4 Weighted Average — DEFERRED / NOT REQUIRED FOR CURRENT MVP.** Закупочный контур работает без средневзвешенной: это аналитика/контроль цены, а не обязательный transactional invariant. Canonical source появился через POSTED iiko receipt; к реализации возвращаемся после накопления достаточной фактической истории. Historical iiko invoices автоматически не backfill. Отсутствие расчёта не блокирует Purchase Request → Supplier Order → Acceptance → iiko Receipt → Payment/Settlement. Текущий price deviation сравнивает confirmation с order, а не с шестимесячной средней.

**3.1C.11 Substitutions — DEFERRED / BUSINESS RULE NOT YET REQUIRED.** Сейчас EOS/iiko product — конкретная номенклатура, supplier — источник товара, Product↔Supplier уже существует. Отдельная canonical модель original product → allowed replacement product пока бизнесу не нужна. Триггер возврата: жёсткая привязка к бренду/марке/спецификации, список допустимых замен и approval policy. Domain entity заранее ради roadmap не строим. Отсутствие substitutions не блокирует текущую закупочную цепочку.

Оба пункта сохранены как planned enhancements, а не потеряны или объявлены DONE; прежняя классификация их как обязательных P1 отменена этим решением. Остальные P2 ниже — оценка аудита optional/later scope, а не новое утверждение об отмене требований владельцем.

## Supplier master: проверка полей

| Поле/возможность | Факт |
|---|---|
| legal name, ИНН, КПП, ОГРН | Есть nullable fields и UI |
| legal/actual address, банковские реквизиты | Есть |
| order email, phone | Есть |
| accounting email | Нет отдельного поля |
| manager/contact | Нет отдельной сущности/поля; free-text comment не эквивалент |
| order/delivery weekdays, lead time | Нет |
| minimum amount | Есть, >=0, nullable |
| minimum quantity | Нет; package_quantity ProductSupplier — размер фасовки |
| supplier aliases | Нет canonical aliases; supplier_product_name/SKU привязаны к ProductSupplier |
| iiko mapping | Есть отдельный confirmed mapping, API/UI и migration 0055 |
| Новопак / Рестоэксперт / Девон / ИП Махнев | Реальное заполнение production не проверено; не отмечать DONE по наличию модели |

## Attachments / inbound / analytics

| Объект | Domain/metadata | Binary attachment / ingestion | Оценка |
|---|---|---|---|
| Supplier confirmation PDF | Ручной structured confirmation и связь с заказом есть | Нет upload/PDF storage и inbound ingestion | OPTIONAL/P2 для manual MVP |
| Supplier document | Номер/дата/строки/сумма/role/links есть | Нет binary attachment | OPTIONAL/P2; domain document не MISSING |
| Payment order / proof | payment_order_number/date, amount/comment есть | Нет файла платёжки/proof | OPTIONAL/P2 |
| Прочие procurement files | Generic procurement attachment entity/API/UI не найден | Нет | OPTIONAL/P2 |
| Repair photos / generated transfer PDF | WorkRequestAttachment и printable PDF существуют в своих контурах | Не переиспользованы как generic Supply attachments | Не закрывает procurement gap |
| Outbound email | Template/preview/attempts/callback/time/provider ID есть | Inbound reply/thread/automatic parsing отсутствует | PARTIAL/P2 |
| Reliability/forecast | Факты deviations/decisions сохраняются | Нет delivery/price reliability metrics, агрегированных quantity/date stats, shortage forecast или auto-alternate proposal | Future/P2 |

Manual confirmation доступен независимо от отсутствия inbox/attachments, через карточку заказа. Accounting-email/recipient metadata не равны communication history. Date/quantity deviations не означают расчёт прогноза; price deviation от order не означает weighted average. Оценка OPTIONAL не отменяет целевое требование хранения файлов в ADR-002: это явный оставшийся объём, не заявление о полном соответствии исходной спецификации.

## Ограничения receipt и денежной модели

- Историческая цена/сумма берётся из документа; safe main/base unit mapping и подтверждённый supplier/store обязательны. Container/package conversion, service FIXED_AMOUNT, unresolved excess и неоднозначное распределение не «угадываются».
- POSTED подтверждается authoritative UUID, PROCESSED и exact match строк; accounted facts не возникают из HTTP ack. Readiness/accounting migration 0056 присутствует. Отсутствие пригодных business data не означает отсутствие lifecycle.
- После POSTED есть stock GET; `_stock_refresh` не сохраняет полученный snapshot в EOS и не проверяет ожидаемый stock delta. Ошибка GET сохраняется как STOCK_REFRESH_FAILED, не отменяя POSTED. Техническое доказательство stock +1 из baseline не расширяется на любую будущую EOS приёмку.
- VAT omission поддержан текущим узким contract; полноценных document VAT fields/налоговой сверки нет. Расширение требует явного контракта, но текущий аудит не объявляет неподтверждённый внешний blocker.
- Settlement считает explicit ACTIVE allocations; due date nullable, overdue вычисляется только при известной дате. Refund/correction — записанные операционные факты, не банковская интеграция. Cash flow — read model, не ledger.
- Current receipt admin UI показывает raw enums/error codes и UUID; это P2 UX gap относительно repository conventions, а не отсутствующий UI. Ничего в frontend в этой задаче не исправлялось.

## Согласованность документов

PROJECT_CHARTER и BLUEPRINT задают миссию/целевую модель, а не актуальный completion checklist: без изменений. ADR-001/ADR-002 сохраняют историю решений и целевой scope; документный файл и широкие процессы не выдаются за реализованные. Прямой IikoProvider отражён как фактический integration path, без нового архитектурного решения. AGENTS уже указывает canonical Supply roadmap и не требует правок. CODEX_CONTEXT и общий roadmap имели устаревшие статусы, поэтому обновлены минимально. В eOS_STAGE_3_SUPPLY добавлено датированное дополнение: старые требования weighted average/substitution остаются историческим замыслом, их обязательность для текущего MVP явно изменена владельцем.

## Stage 3 — Not in Production / Partial / Deferred

| Область | Реальный остаток / статус | Operational 3.1C / приоритет |
|---|---|---|
| 3.0 | DONE: принят ADR-002; финальные permissions и алгоритмы в нём намеренно оставлены поздним этапам | NONE |
| 3.1A | Admin departments/codes, unknown-unit clarification, candidate queue/approval levels, таймеры 5/10 минут и предупреждения, временный edit lock, tooltip долгов — NOT_STARTED/PARTIAL; optimistic locking уже есть | Не блокирует, P2 / 3.4 |
| 3.1A расписания | DONE_DIFFERENTLY: жёсткие понедельник/четверг и часы obsolete как hardcode; используются настраиваемые циклы Automation Core | NONE |
| 3.1A supplier aliases | В Product↔Supplier есть supplier name/SKU; полноценного alias ingestion/learning нет | P2 |
| 3.1B references/stock | Нет резервного Excel import, общего импорта предприятий, отдельного stale-data UX и Supply stock-sync schedule; ручной snapshot/read-stock работает | P2 |
| 3.1B routing | DONE_DIFFERENTLY: explicit routes по department/flow вместо общего динамического enterprise resolver; Бар/Кухня/Авто не включены | P2, расширение маршрутов отдельно |
| 3.1B документы | Нет отдельной line-level модели связи документа со строками заявки, физической передачи/получателя, signed-return и отдельного покрытия старого долга | P2, вне закрытого operational scope |
| 3.1B processing | INTERNAL_TRANSFER сохраняется NEW, не PROCESSED; это ограничение scope, не актуальный внешний blocker контракта incoming receipt | P2, отдельное решение |
| 3.1B print | Ошибки и history есть в карточке; общий Dashboard print exceptions отсутствует | P2 / 3.3 |
| 3.1C master/selection | Отсутствующие поля supplier, minimum quantity, supplier aliases, reliability metrics, quantity/date deviation statistics, прогноз дефицита и auto-alternate supplier | P2, optional enhancements |
| 3.1C minimum | Недобор виден; hard block, future-demand suggestion и календарный подбор отсутствуют | P2, manual decision достаточен |
| 3.1C inbound/files | Нет inbound supplier email ingestion/thread, confirmation PDF, document binary, payment proof и generic procurement attachment model | P2, optional для структурированного ручного MVP |
| 3.1C VAT/reconciliation | Нет отдельной VAT-модели/полной трёхсторонней сверки; omission в текущем safe receipt contract не означает налоговую функциональность. Multi-order supplier document отсутствует | P2; расширенный контракт согласовывать до реализации |
| 3.1C.4 / .11 | DEFERRED по решениям выше; в production отсутствуют | NONE, будущие enhancements |
| 3.1C.17–.18 | Реализованы/развёрнуты, реальная EOS acceptance→receipt→POSTED не business-smoked | P1, проверка operational completion |
| 3.1C email и остальные сценарии | Deployment заявлен baseline; индивидуальный business smoke, получение email адресатом и состав master data не подтверждены отдельными артефактами | P1 — собрать evidence сквозного сценария; отсутствие evidence не равно отсутствию feature |
| 3.1C receipt UI/stock | В admin UI видны UUID/raw status/error code; stock GET после POSTED не сохраняет EOS staging snapshot и не проверяет дельту +quantity | P2 UX/observability; бизнес-проверка остатков входит в P1 smoke |
| 3.2 | NOT_STARTED: production plan/ТТК/chef confirmation, выпуск/списание и анализ отклонений | Later stage, P2 относительно 3.1C |
| 3.3 | PARTIAL: базовый Dashboard заявок/mapping/debt есть; unified procurement/print exceptions, owner/deadline/severity не реализованы | Later stage, P2 |
| 3.4 | PARTIAL: отдельные UX/аудит/архивные механизмы уже есть; финальные roles, departments admin, employee/shift links, трёхсторонняя передача, business-regulations UI, retention jobs, межединичное объединение долгов остаются | Later stage, P2 |
| Main roadmap | Min/Max, auto-order по календарю поставщиков и полная политика кратности не реализованы; package allocation уже есть | P2 / будущий согласованный scope |

Локальных незадеплоенных feature commits относительно предоставленного production SHA не обнаружено; migrations в repo не опережают `0056`. Новые правки этого аудита — только локальные документы. У перечисленных отсутствующих функций нет законченного сквозного API/UI; наличие отдельных enum/полей/Repair attachments не закрывает feature. `BLOCKED_EXTERNAL` для текущего safe receipt contour не обнаружен: старый запрет из-за неизвестного incoming write contract obsolete после технического smoke. Неизвестные package/VAT/legacy контракты остаются ограничениями расширения, а не доказанным P0 текущего контура.

### Next recommended work

Первым шагом провести отдельно согласованный реальный бизнес-сценарий в EOS: need → allocation/order → отправка и ручное confirmation → document → acceptance с destination/source distribution → receipt NEW → POSTED → accounting facts/остатки → payment allocation/settlement и cash flow/coverage. Зафиксировать ссылки и результаты, отдельно проверить shortage/rejected/excess, unpaid/overpaid и безопасное отображение ошибки без создания искусственных финансовых фактов. Этот документационный аудит не выполняет production writes, отправку email или новый smoke.

### Operational completion criteria — 3.1C

Реализация текущего operational scope присутствует в production по baseline. **Доказанное operational completion пока не объявляется:** реальный EOS business receipt и сквозной бизнес-сценарий ещё не подтверждены. Известных P0 по проверенным источникам не найдено; отсутствие smoke не является доказательством отсутствия runtime defects.

Для закрытия должны быть подтверждены на реальных фактах:

- каждая потребность прослеживается до allocation/order либо явно видна как uncovered/UNKNOWN_LEGACY;
- заказанные количества прослеживаются до acceptance, shortage/rejected/excess имеют видимое решение;
- receipt-eligible accepted quantities прослеживаются до POSTED accounting facts; непринятое не проводится, заблокированное не теряется;
- supplier documents, obligations, payments и allocations прослеживаются; долг, переплата, overdue/unknown due date и exceptions видны;
- coverage и денежные факты независимы, недозакупка не скрыта как экономия;
- ошибка/неизвестный внешний результат сохраняется и разрешается явно, не порождая blind retry;
- реальный EOS business smoke зафиксирован отдельно от технического iiko contract smoke.

Weighted Average/Substitutions — deferred enhancements, не blockers. Общий Stage 3 остаётся незавершённым из-за Stage 3.2, полного 3.3/3.4 и сохранённых остатков исходного scope; закрытие operational 3.1A/3.1B/3.1C не означает 100% всей исходной спецификации.

## Валидация этого аудита

Проверяются относительные markdown links, существование source paths, ссылки на canonical roadmap, отсутствие противоречивых текущих status statements, `git diff --check`, `git diff --stat`, `git status`. Backend/frontend, migrations и production не изменяются; runtime suites/build и повторный business smoke не выполняются в documentation-only задаче. Исторические результаты тестов/production в roadmap сохранены с датами и не выдаются за свежий прогон.
