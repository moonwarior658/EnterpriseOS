# Единый финальный MVP «Сырьё» — release manifest, 20.10.2026

**REVIEW. Без push/deployment и бизнес-приёмки.**

Production baseline: `391d8404b64d85a65098f4d919b773975c49612c`, Alembic `20261020_0081` (зафиксированы в контрольной точке C; в финальной корректировке на сервере не перепроверялись). Ветка: `feature/raw-materials-rm2`, без переключения на локальный main. На production tracked diff отсутствовал; старые untracked файлы не тронуты. R-M3 на production не был найден. Пустой/посторонний коммит на сервере не создавался.

## Контрольные точки

- A — `838a3655b1567c05eaa3036a64b3af75aad4cc2c`: календарная средняя, классифицированный расход и DB-only API/UI.
- B — `f7e05c4a4ffeb5905beb232728e532a10302e00f`: версии стандартов, товары/резервы, доказанные коэффициенты, миграция 0082.
- C — `3695102a22d91dbced4cedba11a148db56a95460`: приёмочные исправления по живому контракту iiko, выключенный ежедневный Core-контур, регрессии/RBAC, пилот и итоговые документы.

- D — отдельный локальный коммит финальной корректировки: документные допуски, отзыв и верификация базового количества с containerId. Точный SHA сообщается по завершении; A/B/C не переписываются.

## Финальная корректировка после 3695102 — 20.10.2026

Локальная работа продолжена от `3695102a22d91dbced4cedba11a148db56a95460`; production не подключался и не изменялся. Дополнительная миграция `20261020_0083` следует за `0082`, без seed/backfill. Прежние контрольные точки A/B/C сохранены.

- `is_employee=true` по умолчанию BLOCKED. SUPPLY_MANAGER (и штатный ADMIN) может в финансовой расшифровке подтвердить конкретную версию накладной **только для текущего сырья** либо её конкретную строку. Нет допуска ко всему контрагенту или ко всем товарам документа.
- Обязательны проверка первички, основание и комментарий; автор/время фиксируются сервером. Append-only GRANT/REVOKE с revision, request UUID, исходными document hash и line hash; повтор того же запроса идемпотентен, другое содержание/конкурирующая версия отклоняются. Отзыв требует нового основания и комментария.
- Это только управленческая закупочная аналитика EOS: iiko, Supply, остатки и бухгалтерская себестоимость не меняются. Допуск сотрудника не снимает проверки проведения, внешнего поставщика, склада, валюты, НДС, суммы и единицы.
- Для `amountUnit=учётная единица` + ненулевой `containerId` предусмотрена отдельная построчная верификация BASE_UNIT_CONTAINER. Снабжение по первичке подтверждает точную единицу и исходное положительное количество (`amount=actualAmount`). Контейнер сохраняется в доказательствах, число и единица не меняются; **KG→KG коэффициент не создаётся**. При несовпадении количества/единицы решение отклоняется. Одного допуска сотрудника недостаточно.
- PCS→KG остаётся только по подтверждённой версии коэффициента для конкретных поставщика, упаковки и исторического периода. Нетто/отношение sum÷price не создаёт коэффициент.
- Подтверждение не переписывает снимок: новый ручной Core refresh создаёт новый snapshot с использованными решениями. Изменение допуска между enqueue/collect/publish запрещает публикацию старого scope. При отзыве текущая цена/средняя, использовавшая допуск, сразу BLOCKED без суммы; исходный исторический snapshot остаётся доступен финансовым ролям с отметкой отзыва.
- Денежные источники/история решений доступны только прежним MATERIAL_PURCHASE_READ ролям (ADMIN, SUPPLY_MANAGER, DIRECTOR, DEPUTY_DIRECTOR, ACCOUNTANT). Редактирование закрыто отдельным MATERIAL_DOCUMENT_ADMIT; производственные роли не получают ни документы, ни основания допусков.

[Исследование контрагента и №2929](STAGE_3_2_RAW_MATERIALS_DOCUMENT_ADMISSIONS_2026-10-20.md). Реальных подтверждений первички не предоставлено: локальный replay без допусков сохраняет последнюю цену 7 READY/3 BLOCKED, среднюю 1/9, расход 10 READY. №2929 остаётся BLOCKED. Независимой Office-сверки и браузерной приёмки нет; расписание выключено. Итоговые проверки и текущий состав релиза — в [manifest](STAGE_3_2_RAW_MATERIALS_FINAL_RELEASE_MANIFEST_2026-10-20.md).

## Поведение и совместимость

- Средняя: Σ документных сумм с НДС / Σ подтверждённого сопоставимого количества за 6 полных месяцев; Decimal без раннего округления. Неподтверждённые исторические контрагенты/единицы блокируют весь соответствующий показатель.
- Расход: только производное учётное списание по исходным расходным документам с корневыми DISH/PREPARED; прямой отпуск, перемещения, возвраты, инвентаризации, сессии/списания и корректировки отдельно. Это не норматив, физический замер партии или себестоимость.
- Источник потребления реально использует пары INVOICE/INCOMING_INVOICE и INVENTORY_CORRECTION/INCOMING_INVENTORY; они проверены отдельно, неизвестные пары не угадываются.
- Месячный отчёт движений превышает прежний защитный лимит XML 10 МБ. Новый сырьевой метод читает непересекающиеся окна ≤7 дней через прежний безопасный клиент; общий лимит/методы других контуров не менялись.
- Snapshots R-M2 совместимы: новые аналитические поля находятся в append-only payload тех же snapshots. Старый payload не изменяется, старые средняя/расход отображаются NO_DATA. Ошибка получения не удаляет сохранённые snapshots.
- API читает только EOS. Добавлены GET /raw-materials/{id}/usage, GET /raw-materials/{id}/standards/options, POST /raw-materials/{id}/reserve-selection. Остальные действующие маршруты сохранены; projections расширены аддитивно.
- Деньги: ADMIN, SUPPLY_MANAGER, DIRECTOR, DEPUTY_DIRECTOR, ACCOUNTANT; технология/количество отдельно. Денежные endpoints/history/source/sort и вложенные будущие поля закрыты backend.
- Основной товар, резерв, производитель и поставщик различаются. Доказанные directed conversions привязаны к конкретному товару, версии спецификации, датам, поставщику и упаковке. Нетто само по себе коэффициент не создаёт. Старый blocked snapshot не переписывается.
- Ежедневный action `materials.refresh_enrolled` подготовлен: один Core parent, явно заданные ≤10 уже включённых UUID, дочерние команды через прежний outbox/worker и защиту активного refresh. Нет своего scheduler/retry/callback.
- `raw_material_daily_accepted=False` по умолчанию: action скрыт из доступного каталога, schedule contract и исполнитель закрыты. Никакой schedule/seed не создаётся. После отдельной бизнес-приёмки потребуется явно включить gate и создать ОДНО daily Core schedule по утверждённому списку. В этой работе это не выполнялось.

## Миграция и зависимости

- Миграции `20261020_0082` после `0081` и `20261020_0083` после `0082`; исходная цепочка production 0079→0080→0081 сохраняется.
- Добавляются `material_product_allowances` и `material_unit_conversions`, tenant-aware FK RESTRICT, единственный PRIMARY, ограничения factor/дат/направления, сериализованный overlap guard и защита от поздних INSERT после подтверждения и UPDATE/DELETE истории.
- Снимается только ограничение R-M1 primary=self: другой PRIMARY требует явного допуска той же версии/tenant. Legacy self-approval остаётся допустимым.
- Downgrade отказывается удалять накопленные стандарты. Для production с историей — только совместимый кодовый rollback и сохранение БД, без разрушительного downgrade.
- `0083`: append-only material_document_admissions, tenant/product/snapshot FK, author tenant guard, сериализация по карточке, unique request/revision, GRANT/REVOKE guard и запрет UPDATE/DELETE. На заполненной таблице downgrade останавливается.
- Новых Python/npm/DB extensions не требуется. Docker Compose/Dockerfiles, requirements, HTTP/Vite конфигурация не менялись.
- K3/K5B/K5C/X3, SupplierOrders/приёмки/документы и существующие бизнес-данные не изменены. Невыпущенный K5C `1c4276b` отсутствует в ancestry; isolated diff проверен.

## Итоговые проверки финальной корректировки

- Полный backend: **1304 tests OK, skipped=50**, с RAW_MATERIAL_TEST_DATABASE_URL на отдельной PostgreSQL 17. Пропуски — прочие optional runtime suites; профильные PostgreSQL проверки выполнены.
- Целевые tests: **25 OK** — 9 новых policy/API сценариев, 7 новых PostgreSQL сценариев (включая наследуемый полный API/Core путь) и 9 прежних PostgreSQL регрессий. Проверены все роли EmployeeRole, tenant/product/snapshot isolation, обязательная первичка, document/line/hash scope, независимость двух допусков, сохранение строгих PCS коэффициентов, отзыв/regrant, повторные запросы, конкурирующие решения, audit rollback и смена scope в полёте.
- Миграция: реальный пустой цикл **0082 → 0083 → 0082 → 0083 OK**; проверены FK/check/unique и immutable triggers. После появления синтетической истории downgrade закономерно отказывается её удалять. Offline SQL диапазона 0082→0083 просмотрен; DML/seed/backfill нет.
- Frontend: **219/219 OK** при последовательном выполнении полного suite; production build и ESLint всех изменённых TS/TSX/tests прошли. Первый параллельный npm test завис на завершении неизменённого salesPolish.test.ts без assertion failures; наш зависший запуск остановлен, весь suite повторён последовательно и завершился за 41.5 с. Никаких исправлений Sales/Vite не внесено.
- Новая JSDOM проверка: обязательная незаполненная первичка, безопасный повтор с тем же request_id, финансовая история, отзыв и отсутствие write controls у роли чтения. Реальный браузер недоступен (apps=[], browsers=[]); визуальная бизнес-приёмка не заявляется.
- Локальный replay десяти карточек: последняя цена **7 READY / 3 BLOCKED → 7/3**, средняя **1/9 → 1/9**, расход **10/0 → 10/0**. Статусы, суммы, количества и причины до/после равны; реальных допусков не создавалось. Архив/результаты вне Git, исходный pilot evidence не перезаписан.
- Изолированный кластер после проверок остановлен; сохранён вне Git без удаления накопленной тестовой истории. Production не подключался, данные/конфигурация/сервисы не менялись. Расписание выключено.
- Dependencies/HTTP/Vite/K3/K5B/K5C/Supply документы не изменялись этой корректировкой. Старый K5C 1c4276b не входит в ancestry. `git diff --check` чистый. Прежний untracked R-M2 preflight сохранён вне коммита.

## Проверки контрольной точки C (до корректировки)

- Полный backend suite: **1288 tests, OK (skipped=50)**. Пропущены прочие optional suites без специальных runtime URL; профильные PostgreSQL тесты не пропущены.
- Изолированная PostgreSQL 17: **9 tests OK**, плюс пустой upgrade/downgrade/re-upgrade 0081↔0082, tenant FK, единственный PRIMARY, конкурентный overlap, immutable history и поздние INSERT, Core publication/idempotency/audit rollback.
- Профильные Core/schedule/RBAC tests после добавления daily gate: **63 tests OK**; затем весь окончательный backend suite выше.
- Frontend: **218/218 OK**, TypeScript/Vite production build OK; ESLint изменённых файлов OK. Предупреждение размера bundle сохранено, зависимости не менялись.
- Полный ESLint: только две прежние ошибки `AuthContext.tsx` (set-state-in-effect, only-export-components); файл не менялся. Lint изменённых файлов чистый.
- Offline SQL диапазона 0081→0082 просмотрен (84 строки); новых extensions и DML/seed нет.
- Временный собственный PostgreSQL после проверок остановлен, файлы тестового кластера сохранены вне Git.
- Полный старый suite на первом проходе выявил только окружение /app/uploads; повтор теста с временным WORK_REQUEST_UPLOAD_DIR и окончательный full suite прошли. Тест single-head обновлён под законную новую 0082.
- JSDOM проверки включают ручное обновление/ошибку с сохранением истории, безопасный source drill-down, quantity-only history без денежных запросов и явный выбор разрешённого резерва без Supply writes.
- Fresh read-only pilot evidence подтвердил реальные теги/пары типов, точный состав 10 UUID, календарные периоды, 7/3 последних цен и количественные балансы. Без изменения прав iiko или production данных.
- Браузер недоступен, независимая iikoOffice сверка не выполнена. Это открытые бизнес-гейты, не зелёные тесты.
- `git diff --check` чистый; посторонний preflight untracked сохранён.

## Пилот и границы приёмки

См. [результаты пилота](STAGE_3_2_RAW_MATERIALS_FINAL_PILOT_2026-10-20.md). Это локальный расчёт свежего read-only evidence, не публикация новых метрик на production. Последняя цена 7 READY / 3 BLOCKED, средняя 1 READY / 9 BLOCKED, расход 10 READY; все количественные балансы сошлись. Реальные коэффициенты/стандарты не выдуманы и не подтверждены за владельца.

- Независимая РОСВ iikoOffice: NOT_AVAILABLE. OFFICE_VERIFIED не выставляется.
- Браузер: доступных приложений/браузеров нет (CUA apps=[], browsers=[]). Визуальная и бизнес-приёмка остаются владельцу; JSDOM/API её не заменяют.
- Источник iiko не предоставляет атомарную транзакцию чтения всего периода; hashes, периоды и время наблюдения сохранены.
- Расход — количественная внутренняя сверка; партионная/поставщицкая раскладка расхода и норматив отсутствуют.
- Внутри refresh окна читаются один раз; дочерние карточки ежедневного Core parent пока не делят общий сетевой кэш. Контур ограничен 10 явно согласованными UUID; gate выключен.
- Учётные/технологические подтверждения выполняет снабжение после консультаций, а изменения БМК/Ларица требуют отдельного решения владельца через ADMIN. Массовое заполнение не выполнялось.
- Известные HTTP redirect/Vite dev server проблемы вынесены за этот diff; их конфигурация не исправлялась.

## Будущий deployment — только после отдельного разрешения

1. Проверить точные Git SHA/Alembic 0081, dirty/untracked, services и отсутствие других изменений production.
2. Свежий PostgreSQL backup, hash/TOC и фактическое восстановление на отдельной БД; применить 0082 и 0083 там и проверить сохранность данных. Сохранить старые image IDs.
3. После разрешения отправить только согласованный release ref, fetch/checkout точного итогового SHA после корректировки на production; не main и не K5C.
4. Собрать api, automation-worker, frontend; проверить миграцию в новом backend image. Выполнить однократно `docker compose --env-file .env -f docker/compose/docker-compose.yml run --rm --no-deps --pull never api alembic upgrade 20261020_0083`. У `compose run` нет --no-build.
5. После успешной миграции заменить только API/worker/frontend через `up -d --no-deps --no-build`. PostgreSQL/n8n/proxy не перезапускать.
6. Проверить health/schema/API/13-role RBAC/Supply/Продукция, limited manual run только по прежним карточкам; качество не исправлять автоматически. При ошибке миграции/данных/работоспособности остановиться, без destructive DB rollback.
7. Оставить ежедневный gate false и schedules не создавать до отдельной бизнес-приёмки. HTTP/Vite вне этого релиза.

## Точный состав diff относительно production

- `backend/api/alembic/versions/20261020_0082_material_standards.py`
- `backend/api/alembic/versions/20261020_0083_material_document_admissions.py`
- `backend/api/app/api/routes/automation.py`
- `backend/api/app/api/routes/raw_materials.py`
- `backend/api/app/automation/catalog.py`
- `backend/api/app/automation/local_actions.py`
- `backend/api/app/core/authorization.py`
- `backend/api/app/core/config.py`
- `backend/api/app/integrations/iiko/client.py`
- `backend/api/app/models/__init__.py`
- `backend/api/app/models/raw_material.py`
- `backend/api/app/raw_materials/admission_policy.py`
- `backend/api/app/raw_materials/admissions.py`
- `backend/api/app/raw_materials/analytics.py`
- `backend/api/app/raw_materials/conversions.py`
- `backend/api/app/raw_materials/daily.py`
- `backend/api/app/raw_materials/purchase_refresh.py`
- `backend/api/app/raw_materials/purchases.py`
- `backend/api/app/raw_materials/service.py`
- `backend/api/app/raw_materials/standards.py`
- `backend/api/app/schemas/automation.py`
- `backend/api/app/schemas/raw_materials.py`
- `backend/api/tests/test_material_admissions.py`
- `backend/api/tests/test_material_admissions_postgres.py`
- `backend/api/tests/test_material_analytics.py`
- `backend/api/tests/test_material_daily.py`
- `backend/api/tests/test_material_purchases.py`
- `backend/api/tests/test_material_purchases_postgres.py`
- `backend/api/tests/test_material_standards.py`
- `backend/api/tests/test_material_standards_postgres.py`
- `backend/api/tests/test_raw_materials.py`
- `backend/api/tests/test_raw_materials_postgres.py`
- `backend/api/tests/test_requests_api.py`
- `docs/ROADMAP_STAGE_3_2_RAW_MATERIALS_MVP_2026-10-12.md`
- `docs/STAGE_3_2_RAW_MATERIALS_DOCUMENT_ADMISSIONS_2026-10-20.md`
- `docs/STAGE_3_2_RAW_MATERIALS_FINAL_PILOT_2026-10-20.md`
- `docs/STAGE_3_2_RAW_MATERIALS_FINAL_RELEASE_MANIFEST_2026-10-20.md`
- `docs/STAGE_3_2_RAW_MATERIALS_MVP_SPEC_2026-10-12.md`
- `frontend/src/components/MaterialDocumentAdmissions.tsx`
- `frontend/src/components/MaterialPurchase.tsx`
- `frontend/src/components/MaterialStandards.tsx`
- `frontend/src/components/MaterialUsage.tsx`
- `frontend/src/pages/RawMaterialsPage.tsx`
- `frontend/src/services/rawMaterials.ts`
- `frontend/tests/materialAdmissions.test.ts`
- `frontend/tests/materialFinal.test.ts`
- `frontend/tests/materialPurchase.test.ts`
- `frontend/tests/rawMaterials.test.ts`

Исключено из коммитов: прежний `docs/STAGE_3_2_RM2_RELEASE_PREFLIGHT_2026-10-20.md`, приватные captures/логи/backup, тестовые БД и артефакты сборки.

## Новые API и порядок проверки допуска

- `GET /raw-materials/{product_id}/document-admissions?offset=&limit=` — финансовая история и текущие решения; no-store.
- `POST /raw-materials/{product_id}/metrics/{snapshot_id}/admissions` — отдельное write-разрешение, expected_version/expected_revision, request_id, GRANT/REVOKE, kind, точные document_id/hash, необязательный line_num для сотрудника (пусто = строки только этого сырья), обязательные evidence/comment. GRANT требует primary_checked. Для BASE_UNIT_CONTAINER обязательны строка, verified_unit_id и verified_quantity, точно совпадающие с исходником.
- Прежние metrics/sources контракты расширены аддитивно: current и admission_validity, все сохранённые documents. Исторические суммы не переписываются. Реестр и верх карточки используют current с учётом отзыва.
- Для бизнес-проверки: открыть финансовую расшифровку сохранённого blocked snapshot → выбрать документ или строку → проверить первичку → внести основание/комментарий → сохранить → вручную обновить показатели. Для №2929 отдельно подтвердить внешнюю закупку и KG/container, только если первичка это доказывает. PCS коэффициенты утверждать прежним интерфейсом стандартов. Отзыв немедленно закрывает текущую сумму и требует нового расчёта.
- Бизнес-подтверждения в этой работе не выполнялись. Синтетические тестовые решения существуют только в отдельной локальной тестовой БД.
