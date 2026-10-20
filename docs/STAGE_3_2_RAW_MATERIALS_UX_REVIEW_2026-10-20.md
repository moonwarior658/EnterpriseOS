# «Сырьё»: пакет UX-правок, 20.10.2026

Рабочая ветка `feature/raw-materials-rm2`, база `a6c6a294be148a7767075eed80d97fe6df4463a0`, схема `20261020_0083`. Точный SHA кандидата выдаётся после коммита этого пакета. Новых миграций нет.

**Статус: локальная реализация и автоматические проверки выполнены; browser / визуальная приёмка НЕ выполнены. Deployment остановлен до совместного просмотра владельцем.** Последнее уточнение владельца: «делай правки. Потом отдельно посмотрим результат».

## Checklist 01–20

PASS в этой таблице означает только указанную проверку кода, DOM или API, а не визуальную приёмку в браузере. Desktop/mobile appearance, удобство и нативный file picker требуют отдельного browser smoke. Скриншотов нет: CUA возвращает apps=[], browsers=[]; попытка открыть iab завершается `Browser is not available: iab`.

| № | Изменённый компонент | Что сделано | Проверка / evidence | Результат |
|---|---|---|---|---|
| 01 | `RawMaterialsPage`, `RawMaterialsPage.css` | Компактный реестр: название, тип, единица, фактические показатели; формы и документы не мешают чтению. Восстановлена доступность таблицы на мобильном breakpoint. | `materialUx.test.ts`: registry/card; просмотр scoped CSS. | PASS DOM/код; визуально не проверено |
| 02 | `PurchaseValue`, `UsageValue`, `MaterialCard` | Единые русские состояния «Нет данных» / «Требуется проверка», цветовые статусы карточки; единицы — из API iiko. | `materialUx`, `materialFinal`, `rawMaterials`. | PASS DOM |
| 03 | `materialPresentation` | Два десятичных знака, запятая, пробелы тысяч; точное строковое округление без изменения источника. Поддержаны дроби и экспоненциальная запись. | Decimal display + precision-preserving editor tests, включая значения за пределом Number.MAX_SAFE_INTEGER. | PASS |
| 04 | `PurchasePanel`, `materialPeriod` | Раздельные подписи расчётного периода средней и окна поиска последних приходов в модальном окне. Даты показываются включительно, на API остаётся полуоткрытый период. | Проверка period formatter, DOM карточки и истории; код отдельной подписи каждого периода. | PASS DOM/код |
| 05 | `PurchasePanel`, `MaterialCard` | Расчёты, snapshots и первичные документы убраны с основной страницы. | Card test: до открытия нет details, форм, запросов истории/расхода. | PASS DOM |
| 06 | `MaterialCard`, `MaterialEditor` | Действующая версия и сохранённый черновик показаны отдельно; объяснены отсутствие черновика, причины изменения, несохранённые правки, консультации, право подтверждения, архив и отсутствие основной позиции. | Draft → save → confirm test + backend workflow/RBAC/PG. | PASS |
| 07 | `EnrollMaterial`, `MaterialDialog` | Включение SupplyProduct в модальном окне, без разворачивания формы под таблицей. | Registry test: форма в dialog portal, вне `.material-page`; POST только выбранного existing-id. | PASS DOM |
| 08 | `RawMaterialsPage`, CSS | «Без поставщика» и «Архив карточек» — переключатели с aria-pressed и активным оформлением; сброс в том же стиле EOS. | Registry filter test + CSS specificity inspection. | PASS DOM/код; визуально не проверено |
| 09 | `RawMaterialsPage`, `catalog_sort`, API/service catalog | Сортировка по семи содержательным колонкам, asc/desc, до пагинации; Decimal для чисел. BLOCKED/NO_DATA отдельно после значений, неопределённый резервный поставщик не выбирается произвольно. Денежная сортировка запрещена без MONEY. | Pure sort tests; actual SQLite/PG API filtering/pagination/RBAC; revoked admission test. | PASS |
| 10 | `PurchaseValue`, `UsageValue` | Из строк реестра удалены дата последнего прихода и период расхода. Подробности сохранены в карточке и модальном окне. | Registry test проверяет отсутствие дат/периодов в table. | PASS DOM |
| 11 | `materialPresentation`, реестр | Форматы `1 078,80 кг`, `275,35 ₽/кг` и аналогично для л. | Formatter + registry DOM tests. | PASS |
| 12 | `MaterialCard` | Строка `SupplyProduct: UUID` удалена; UUID используется для API и внутренних связей. | Card DOM test; contract POST tests. | PASS |
| 13 | `MaterialCard`, `.material-info-grid` | Блок около фотографии: тип, статус, единица iiko, вес, действующий стандарт, черновик. | Card DOM + scoped CSS inspection. | PASS DOM/код; визуально не проверено |
| 14 | `MaterialCard` | Удалена техническая подпись «Назначения поставщиков из Supply…». | Negative DOM assertion. | PASS |
| 15 | `MaterialCard`, `ReserveSelection` | Отдельные группы основного/резервных товаров и поставщиков, единые пустые состояния; выбор разрешённого резерва — через кнопку и modal. | Registry/card/reserve tests; backend standards PG. | PASS DOM/API; визуально не проверено |
| 16 | `PurchasePanel`, `.material-metrics` | Компактные три показателя, заголовок и обновление в одной строке; статусы, даты и НДС показываются на карточке без сырых причин/документов. | Card/polling tests, success/error/disabled states. | PASS DOM; визуально не проверено |
| 17 | `PurchasePanel`, `UsagePanel`, `MaterialDocumentAdmissions` | История цен, snapshots, источники, расчёт средней, расход и допуски находятся в modal; история и пагинация сохранены. | Purchase polling → history modal → invoice/supplier; usage/admission tests; PG history integrity. | PASS DOM/API |
| 18 | `MaterialEditor`, `StandardsEditor` | Вся спецификация в modal: сведения, товары, производители, упаковка, коэффициенты, затем подтверждение. Причины и обязательные поля обозначены; сохранённая версия и содержимое привязаны к confirm. Ввод производителей через запятую исправлен. | Draft/save/confirm + exact coefficient/weight/manufacturer tests; backend/PG workflow. | PASS DOM/API |
| 19 | `History`, `MaterialCard` | История изменений открывается кнопкой в шапке карточки; авторы, время, причины, версии, детали безопасного аудита и пагинация сохранены. | Card history test; existing backend history tests. | PASS DOM/API |
| 20 | `MaterialDialog`, редакторы, scoped CSS | EOS buttons/EosSelect/EosCheckbox, оформленный file picker; busy/error/disabled, защита повторной отправки; Esc/крестик/backdrop с dirty guard, beforeunload, focus trap, внутренний scroll и responsive CSS. | Dialog focus/dirty/busy tests; photo PUT once → saved image; style/build/lint. | PASS DOM/код; desktop/mobile и picker визуально не проверены |

## Пользовательские сценарии

1. Реестр, фильтры, заголовки сортировки, включение товара — DOM-интеграция с контролем запросов; серверная сортировка отдельно проверена на PostgreSQL до пагинации.
2. Информационная карточка — DOM: основная страница без форм, inline-истории и технического UUID.
3. Закупочная история → документ-основание — DOM с тестовым HTTP, видны накладная/поставщик/суммы; фактические API sources/RBAC проверены backend-тестами.
4–5. Черновик → сохранение → подтверждение — DOM проверяет expected_version, specification_id, content_hash и обязательную консультацию; PostgreSQL проверяет реальные изменения, аудит, stale version, concurrency и ограничения.
6. История изменений — отдельное окно, автор/дата/причина/версия, существующая пагинация.
7. Фото — DOM проверяет FormData/file/version/reason, защиту двойного submit и загрузку blob изображения после сохранения; backend проверяет нормализацию фото; PostgreSQL — неизменяемость истории.
8. Несохранённые изменения — Esc/крестик показывают предупреждение; продолжение сохраняет введённое; busy запрещает закрытие, Tab остаётся внутри окна, фокус возвращается.
9. Права — frontend без денежных запросов для технологической роли; backend matrix, tenant isolation, запрет сортировок без MONEY, недоступность stale цены после отзыва допуска. **Desktop/mobile browser сценарий не выполнен.**

DOM-интеграция использует синтетические fixtures и подменённый fetch; она не выдаётся за сквозной тест реального браузера и API. Реальные транзакции, фото и workflow выполнялись только на отдельных тестовых БД, не на production.

## Проверки

- Full backend: `WORK_REQUEST_UPLOAD_DIR=/private/tmp/materials-ux-test-uploads ...python -m unittest discover -s tests -v`: **1308 run, OK, 67 optional skipped**. Файловое хранилище тестов направлено во временный каталог, без изменения конфигурации проекта.
- Изолированная PostgreSQL 17, localhost:55439, только `eos_supply_migration_test`: **4** raw-material API/constraints/concurrency tests + **13** admissions/standards/purchases tests — **17 PASS**, включая отказ downgrade при существующей истории. Эти PG тесты входят в optional skips полного прогона и выполнены отдельно. Все тестовые tenants уникальны; прежние данные не удалялись.
- Frontend: **226 PASS**; финальные результаты полного suite записаны в `/private/tmp/materials-ux-frontend-full-final.log`; отдельные новые UX scenarios — **7 PASS**.
- `npm run build`: PASS; существующее предупреждение о размере bundle >500 kB.
- ESLint только изменённых компонентов/services/tests: PASS. `AuthContext.tsx` не изменялся, известные baseline ошибки не исправлялись.
- `git diff --check`: PASS; перед коммитом проверяется также staged diff.
- Evidence: `frontend/tests/materialUx.test.ts`, `rawMaterials.test.ts`, `materialPurchase.test.ts`, `materialFinal.test.ts`; `backend/api/tests/test_material_catalog_sort.py`, `test_raw_materials.py`, `test_raw_materials_postgres.py`, `test_material_admissions.py`, `test_material_purchases.py`. Сырые логи находятся в `/private/tmp/materials-ux-*.log`, в Git не включаются.

## Состав и совместимость

Backend: только аддитивные catalog sort/direction и запрет денежной сортировки без существующего разрешения. Сортировка использует уже разрешённые projections EOS, включая текущую валидность отозванных допусков, без обращения к iiko и без переоценки/перезаписи snapshots. Дополнительные сорта вычисляются по отфильтрованному локальному набору перед пагинацией; это подходит текущему ограниченному реестру, при существенном росте потребуется отдельно оценить производительность.

Frontend: RawMaterialsPage/CSS; MaterialPurchase, MaterialUsage, MaterialStandards, MaterialDocumentAdmissions; новые MaterialDialog (обёртка существующего EosDialog), MaterialEditor и materialPresentation; safe MaterialApiError text; regression/UX tests.

Модель, миграции, формулы, коэффициенты, snapshot policy, документные допуски, бухгалтерия, Supply-документы, ProductKnowledge и Employee pages, Automation Core и расписание не менялись. Значения округляются только для чтения; исходные поля веса/коэффициента при редактировании сохраняют точность. Новых зависимостей нет.

## Git, production и следующий gate

- Production в этом пакете не изменялся: ни push, ни deployment, ни миграций/перезапусков, ни бизнес-записей, ни сборов.
- Последнее подтверждённое состояние предыдущего выпуска: `a6c6a29`, `0083`; повторный live preflight в UX-пакете не проводился. Свежий backup для нового выпуска не создавался: deployment отложен до browser review.
- Предыдущий dirty manifest `STAGE_3_2_RAW_MATERIALS_FINAL_RELEASE_MANIFEST_2026-10-20.md` и untracked `STAGE_3_2_RM2_RELEASE_PREFLIGHT_2026-10-20.md` сохранены отдельно и не включаются в новый коммит.
- Перед будущим выпуском нужны browser smoke desktop/mobile, осмотр всех 20 пунктов владельцем, актуальный Git/Alembic/services preflight и свежий backup с подтверждённым восстановлением. При browser/functional FAIL выпуск запрещён.
- HTTP/Vite backlog, расписание и независимая iikoOffice-сверка не входят в пакет; расписание не включалось, OFFICE_VERIFIED не объявляется.
