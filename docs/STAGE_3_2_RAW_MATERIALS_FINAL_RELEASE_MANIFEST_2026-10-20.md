# Единый финальный MVP «Сырьё» — release manifest, 20.10.2026

**REVIEW. Без push/deployment и бизнес-приёмки.**

Production baseline: `391d8404b64d85a65098f4d919b773975c49612c`, Alembic `20261020_0081` (повторно прочитаны на production в этой работе). Ветка: `feature/raw-materials-rm2`, без переключения на локальный main. На production tracked diff отсутствовал; старые untracked файлы не тронуты. R-M3 на production не был найден. Пустой/посторонний коммит на сервере не создавался.

## Контрольные точки

- A — `838a3655b1567c05eaa3036a64b3af75aad4cc2c`: календарная средняя, классифицированный расход и DB-only API/UI.
- B — `f7e05c4a4ffeb5905beb232728e532a10302e00f`: версии стандартов, товары/резервы, доказанные коэффициенты, миграция 0082.
- C — коммит, содержащий этот manifest: приёмочные исправления по живому контракту iiko, выключенный ежедневный Core-контур, регрессии/RBAC, пилот и итоговые документы. Точный SHA C — в итоговом сообщении и `git log -3`; self-SHA не встраивается в содержимое собственного коммита.

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

- Только `20261020_0082`, down_revision `20261020_0081`; исходная цепочка production 0079→0080→0081 сохраняется.
- Добавляются `material_product_allowances` и `material_unit_conversions`, tenant-aware FK RESTRICT, единственный PRIMARY, ограничения factor/дат/направления, сериализованный overlap guard и защита от поздних INSERT после подтверждения и UPDATE/DELETE истории.
- Снимается только ограничение R-M1 primary=self: другой PRIMARY требует явного допуска той же версии/tenant. Legacy self-approval остаётся допустимым.
- Downgrade отказывается удалять накопленные стандарты. Для production с историей — только совместимый кодовый rollback и сохранение БД, без разрушительного downgrade.
- Новых Python/npm/DB extensions не требуется. Docker Compose/Dockerfiles, requirements, HTTP/Vite конфигурация не менялись.
- K3/K5B/K5C/X3, SupplierOrders/приёмки/документы и существующие бизнес-данные не изменены. Невыпущенный K5C `1c4276b` отсутствует в ancestry; isolated diff проверен.

## Проверки

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
2. Свежий PostgreSQL backup, hash/TOC и фактическое восстановление на отдельной БД; применить 0082 там и проверить сохранность данных. Сохранить старые image IDs.
3. После разрешения отправить только согласованный release ref, fetch/checkout точного SHA C на production; не main и не K5C.
4. Собрать api, automation-worker, frontend; проверить миграцию в новом backend image. Выполнить однократно `docker compose --env-file .env -f docker/compose/docker-compose.yml run --rm --no-deps --pull never api alembic upgrade 20261020_0082`. У `compose run` нет --no-build.
5. После успешной миграции заменить только API/worker/frontend через `up -d --no-deps --no-build`. PostgreSQL/n8n/proxy не перезапускать.
6. Проверить health/schema/API/13-role RBAC/Supply/Продукция, limited manual run только по прежним карточкам; качество не исправлять автоматически. При ошибке миграции/данных/работоспособности остановиться, без destructive DB rollback.
7. Оставить ежедневный gate false и schedules не создавать до отдельной бизнес-приёмки. HTTP/Vite вне этого релиза.

## Точный состав diff относительно production

- `backend/api/alembic/versions/20261020_0082_material_standards.py`
- `backend/api/app/api/routes/automation.py`
- `backend/api/app/api/routes/raw_materials.py`
- `backend/api/app/automation/catalog.py`
- `backend/api/app/automation/local_actions.py`
- `backend/api/app/core/config.py`
- `backend/api/app/integrations/iiko/client.py`
- `backend/api/app/models/__init__.py`
- `backend/api/app/models/raw_material.py`
- `backend/api/app/raw_materials/analytics.py`
- `backend/api/app/raw_materials/conversions.py`
- `backend/api/app/raw_materials/daily.py`
- `backend/api/app/raw_materials/purchase_refresh.py`
- `backend/api/app/raw_materials/purchases.py`
- `backend/api/app/raw_materials/service.py`
- `backend/api/app/raw_materials/standards.py`
- `backend/api/app/schemas/automation.py`
- `backend/api/app/schemas/raw_materials.py`
- `backend/api/tests/test_material_analytics.py`
- `backend/api/tests/test_material_daily.py`
- `backend/api/tests/test_material_purchases.py`
- `backend/api/tests/test_material_purchases_postgres.py`
- `backend/api/tests/test_material_standards.py`
- `backend/api/tests/test_material_standards_postgres.py`
- `backend/api/tests/test_raw_materials_postgres.py`
- `backend/api/tests/test_requests_api.py`
- `docs/ROADMAP_STAGE_3_2_RAW_MATERIALS_MVP_2026-10-12.md`
- `docs/STAGE_3_2_RAW_MATERIALS_FINAL_PILOT_2026-10-20.md`
- `docs/STAGE_3_2_RAW_MATERIALS_FINAL_RELEASE_MANIFEST_2026-10-20.md`
- `docs/STAGE_3_2_RAW_MATERIALS_MVP_SPEC_2026-10-12.md`
- `frontend/src/components/MaterialPurchase.tsx`
- `frontend/src/components/MaterialStandards.tsx`
- `frontend/src/components/MaterialUsage.tsx`
- `frontend/src/pages/RawMaterialsPage.tsx`
- `frontend/src/services/rawMaterials.ts`
- `frontend/tests/materialFinal.test.ts`
- `frontend/tests/materialPurchase.test.ts`
- `frontend/tests/rawMaterials.test.ts`

Исключено из коммитов: прежний `docs/STAGE_3_2_RM2_RELEASE_PREFLIGHT_2026-10-20.md`, приватные captures/логи/backup, тестовые БД и артефакты сборки.
