# Stage 3.2 / K1 — реальное наполнение «Продукции»

08.10.2026. **Локальная реализация на review; production deployment и загрузка не выполнены.**
Gate K и бизнес-приёмка не закрыты. Текущий запрос разрешил реализацию K1 и
read-only исследование; производственная часть, K2–K6 и автоматическое расширение
ассортимента не реализуются.

## Сентябрьская выборка и доказательства

Повторно прочитаны EOS Sales и iiko через существующий клиент. PostgreSQL:
`BEGIN READ ONLY`, statement timeout, завершение rollback. iiko: только catalogue,
MeasureUnit и price GET, auth/logout; код исследовательского reader выполнялся
в памяти, файлы production не записывались. Production HEAD до/после:
`a9c75d02e2e18db68f83e77a29f25b0863272eed`, Alembic `20261006_0073`.
Существующие untracked `'2026-09-01'`, `M`, `backup/` не изменялись.
Снимок отбора: **08.10.2026 14:06:16 Asia/Yekaterinburg**; данные iiko текущие,
не исторические характеристики сентября. Названия/единицы/вес датированы snapshot.

Период — **[01.09.2026, 01.10.2026)** по `business_date` Sales.
Кандидат: присутствующее, не удалённое событие с положительным количеством и без
флага возврата, на точке с подтверждённым OLAP mapping; уникальность — UUID,
не название. Бесплатные положительные продажи включаются. Последующий возврат
сам по себе не вычёркивает изделие с другой подтверждённой положительной продажей.
KPI и reconciliation Sales не менялись.

| Проверка | Результат |
|---|---:|
| События Sales за сентябрь, включая прочие флаги | 14 844 |
| UUID в исходных событиях, включая отменённые/возвратные | 157 |
| Найдено фактически проданных уникальных позиций | **141** |
| Подтверждённые точки | **3** |
| Успешные дневные загрузки / ожидаемые дни | **30 / 30** |
| Дни с продажами по каждой из трёх точек | **30 / 30** |
| Готово технически к первоначальной загрузке | **141** |
| Требуют разрешения конфликтов UUID/mapping/единиц | **0** |
| Несогласованные исторические ссылки Sales.product_id | **0** |
| Проданные позиции только неподтверждённых точек | **0** |
| Подтверждённые связи с существующим SupplyProduct | **5** |
| Записи с одинаковыми именами, разными UUID | **6**, остаются раздельными |

Точки: Матросова 35, Игарская 25В, Матросова 15. Остальные точки не объявляются
подтверждёнными. SalesDaySync — отметка по source, не отдельный журнал каждой
точки: 30/30 плюс наличие событий всех точек во все дни подтверждают доступный
контур EOS, но не являются независимой сверкой контрольных сумм iikoOffice.
Есть 15 положительных событий с возвратным флагом; включение этих флагов не
расширяет набор UUID: обе проверки дают 141.

Ассортимент следует заданному правилу «все проданные позиции», без автоматической
классификации по iiko type: **122 DISH, 13 GOODS, 4 MODIFIER, 2 SERVICE**.
Одна запись сейчас deleted в iiko. MODIFIER/SERVICE и deleted явно перечислены
в review CSV и требуют содержательной бизнес-проверки, но не являются UUID
конфликтами и не потеряны. Продажи не назначают EOS-статус: команда публикации
обязательно требует отдельный `initial_status`, список подтверждённых точек,
review hash и действующего ADMIN. Техническая готовность не равна утверждению
начального статуса или бизнес-приёмке.

## Реально заполненные поля

| Поле | Из 141 | Семантика |
|---|---:|---|
| Название, UUID iiko, единица | 141 | Из актуального источника, ID-only |
| Артикул | 141 | Source num/code |
| Положительный вес | 131 | `unitWeight`: kg на основную единицу; исходная точность сохраняется |
| Тип продажи | 141 | `useBalanceForSell`: 139 non-weight → «Порционный», 2 weight → «Весовой» |
| Описание | 5 | Текст iiko, не выдуманный состав/срок |
| Категория EOS | 0 | Категории iiko не подменяют EOS классификацию |
| Подтверждённая действующая цена | **0** | В рабочий API неподтверждённые BASE-кандидаты не попадают |
| Фото, ТТК, себестоимость, состав, аллергены, хранение, обучение | **0** | Отсутствуют; не заполняются из названия/догадок |

Семантика `useBalanceForSell` проверена по [официальному контракту iiko](https://ru.iiko.help/article/api-documentations/elementy-nomenklatury?cm=1&ds=1&gc=1).
«Порционный» здесь означает невесовую продажу; это не классификация готового блюда
и не подтверждение выхода ТТК. Нулевые веса 10 записей отображаются как неизвестные.

Дополнительно подготовлены **413** текущих ценовых контекстов для 141 UUID,
из них **363 included BASE**: Игарская 25В — 119, Матросова 35 — 111,
Матросова 15 — 133. Scheduled/category-price контекстов в этой выборке нет.
Цена-API не возвращает валюту и единицу цены; Office-сверка effective price
не проведена. Поэтому RUB, unit, defaultSalePrice и цена из чека не назначены.
Это **кандидаты для сверки**, а не 363 подтверждённых цены. API/хранилище уже
поддерживают подтверждённые суммы по точке и полуоткрытому интервалу, валюте,
единице, evidence и автору подтверждения. Готовое подтверждение можно включить
в snapshot перед первоначальной публикацией.

## Что реализовано

- Source-first EOS identity unique `(tenant, Sales source, iiko UUID)`, стабильный
  EOS UUID и nullable tenant FK к SupplyProduct только при подтверждённом mapping.
  Supply normalized-name uniqueness, единицы, mappings и Sales facts не изменяются.
- Три additive таблицы: партии/отчёт, изделия, подтверждённые цены; миграция
  `20261008_0074`. Нет seed/backfill данных при upgrade. Downgrade блокируется,
  если есть партии: operational rollback — снятие публикации, не удаление истории.
- `GET /products` и `GET /products/{id}`: backend search по названию/артикулу,
  status/mode/category, offset/limit, точка/дата цены; стабильная сортировка name/id.
  Нет iiko запросов при открытии портала, raw payload, цены чека, costs или ТТК.
- Новый read capability через текущий ActionContext. Безопасная карточка для
  бизнес-ролей каталога; DRIVER/HANDYMAN и SERVICE не получают новый доступ.
  SELLER видит цены только своей подтверждённой активной точки; прочие читатели —
  подтверждённые retail points. Управление статусом/контентом закрыто до K2.
- Рабочие routes `/products` читают API; демо — только dev `/dev/products`,
  отдельный компонент без fallback. Ошибка загрузки не возвращает вымышленные данные.
  Неизвестные поля показаны отсутствующими. Стоимость не входит в K1 grants/JSON,
  поэтому колонка исключена у всех ролей K1; обычная таблица имеет шесть колонок.
- Явные CLI `collect`, `preview`, `publish`, `rollback`. Collection повторно
  использует существующий iiko client и проверяет fingerprint Sales source;
  source snapshot не меняет EOS. Preview PostgreSQL read-only.
- Publication — одна транзакция, блокировка source, unique constraints, review hash,
  actor и AuditEvent. Идентичный повтор возвращает ту же партию без новых карточек/
  событий. Другой набор после bootstrap отклоняется: автоматического расширения нет.
  Rollback идемпотентно скрывает карточки и сохраняет цены/идентичность/отчёт/аудит.
  Повторная публикация откатанной партии требует отдельного решения, автоматического
  восстановления нет. CLI последующего ручного добавления в K1 отсутствует;
  новые позиции проходят отдельный ручной процесс с подтверждением mapping.

## Артефакты и бизнес-проверка

Локально сохранены только необходимые нормализованные поля, без credentials,
raw catalogue/OLAP/recipe payload:

- [selection report](../output/stage3_2_k1/selection_report.json) — все 141 UUID,
  warnings/problems, связи и review hash;
- [catalog review CSV](../output/stage3_2_k1/catalog_review.csv) — названия/единицы/
  вес/тип/mapping/флаги для сверки;
- [price candidates](../output/stage3_2_k1/price_candidates_review.csv) — суммы
  источника, включённость и интервалы, все помечены UNCONFIRMED;
- [summary](../output/stage3_2_k1/summary.json), [points](../output/stage3_2_k1/points_review.json)
  и [SHA-256 manifest](../output/stage3_2_k1/manifest.json).

После review и отдельного согласования production: verified backup/recovery →
миграция/API → `collect` read-only → `preview` → сверка отчёта/hash/status/точек →
явная публикация → frontend и бизнес-проверка. Ни один из этих production write
шагов текущим результатом не выполнен. Команды из `backend/api`:

```text
uv run python -m app.product_knowledge.cli collect --tenant eclair --source SOURCE_ID --snapshot /private/tmp/k1-source.json
uv run python -m app.product_knowledge.cli preview --tenant eclair --source SOURCE_ID --snapshot /private/tmp/k1-source.json --report /private/tmp/k1-plan.json
uv run python -m app.product_knowledge.cli publish --tenant eclair --source SOURCE_ID --snapshot /private/tmp/k1-source.json --actor-id ADMIN_ID --expected-hash REVIEWED_HASH --initial-status APPROVED_STATUS --confirmed-point POINT_UUID_1 --confirmed-point POINT_UUID_2 --confirmed-point POINT_UUID_3
uv run python -m app.product_knowledge.cli rollback --tenant eclair --source SOURCE_ID --actor-id ADMIN_ID --batch-id BATCH_UUID
```

Эти команды используют конфигурацию выбранного runtime; сейчас они приведены для
review, не как разрешение выполнить их в production. Source/actor/status/hash
не угадываются. Между preview и publish используется тот же snapshot; если Sales
изменился, новый hash требует повторной сверки.

Чеклист владельца/шефа/продавца:

1. Проверить 141 UUID, совпадающие имена, 4 MODIFIER, 2 SERVICE и deleted запись;
   подтвердить начальный сетевой статус, не делать его производственным допуском.
2. Сверить названия, `useBalanceForSell`, базовые единицы и вес для двух весовых,
   нескольких порционных и 10 неизвестных весов в iikoOffice.
3. Сверить price candidates по трём точкам, подтвердить валюту, единицу, интервалы/
   effective context и evidence; до этого «Нет подтверждённой цены» корректно.
4. В контрольном runtime после отдельного наполнения проверить поиск, фильтры,
   вторую страницу, карточку/возврат с сохранением фильтров, seller scope,
   пустой каталог, отказ API и снятие публикации партии.
5. Фото/ТТК/cost и незаполненные знания не считать принятыми. Production demand
   и автоматическая синхронизация не запускаются до gate K.

## Проверки и оставшиеся ограничения

Проверено:

- Полный backend после исправления read context: **1145 тестов, OK, 36 optional PostgreSQL tests skipped**.
- Профильные K1 API/publication тесты: **13 OK**, включая роли, Seller price scope
  и дополнительную проверку согласованности исторической ссылки Sales.
- Live отдельный PostgreSQL: **2 теста OK**, concurrent retry/tenant/UUID/status
  constraints, точность веса, unpublication и запрет downgrade с партиями.
  Отдельно полный upgrade и цикл 0073 → 0074 → 0073 → 0074 на пустой DB прошли.
  Временный PostgreSQL после проверок остановлен и удалён; production не использовался для QA-записи.
- Frontend: **3 профильных теста OK**, production build OK, ESLint всех изменённых
  frontend-файлов OK. Предупреждение build о размере существующего bundle сохранено.
- `git diff --check` OK. Production HEAD/status/Alembic после чтений неизменны.

Git: ветка `main` сохранена, stage/commit/push не выполнялись. Dirty tree включает
K1 и входящие изменения K0/R0. Новые K1 файлы пока untracked; tracked modifications
— authorization.py, main.py, models/__init__.py, test_requests_api.py (head),
App.tsx, AppLayout.tsx, architecture и существующий dirty roadmap. Новые files:
models/schemas/routes/product_knowledge.py, app/product_knowledge/{bootstrap,service,
snapshot,cli,__init__}.py, Alembic 0074, два backend test files, рабочая page и
отдельная demo page, frontend API service/live test, этот report и output K1.
CSS/demoCatalog/demo layout/R0 artifacts пришли из K0/R0, не переписывались K1.
Автоматические API/DOM-тесты не заменяют browser/iikoOffice/бизнес-приёмку.
Подтверждённые цены пока отсутствуют, EOS категории не назначены, знания не
наполнены. Status/edit/photo mutations K2–K5 и background refresh K6 остаются
вне текущей реализации. Необходимая бизнес-проверка не объявляется выполненной.

Commit, push, смена ветки и production deployment не выполнялись. Существующие
изменения K0 и R0 сохранены; их наличие в dirty tree не относится к новым K1
изменениям автоматически.
