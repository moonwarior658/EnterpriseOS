# R-M1 — изолированный release manifest, 20.10.2026

**Статус: локальный release на review. Выпуск не выполнен.**

- Base production: `ef92ebfac3f24509382d540044d9c96338aa264e`, Alembic `20261009_0079`.
- Источник только R-M1: `b0126cb86b92426901fcc1f18ffc86dded70473f`.
- Ветка: `release/rm1-isolated-20261020`; worktree `/tmp/eos-release-rm1-20261020`. Main сохранён на b0126cb. Итоговый commit — tip этой ветки, предоставлен в финальном отчёте; один commit непосредственно поверх ef92ebf.
- Перенос: 19 runtime/test файлов R-M1 точно совпадают с b0126cb. Два R-M1 документа перенесены с актуализацией release evidence и ссылок. Этот manifest — дополнительный файл. Исторические исследования остаются в immutable исходном commit; их код/CSV/JSON в release не добавлялись.
- `1c4276b` и прочие промежуточные commits не входят в ancestry release. K5C fixed warehouse, cost_config и refresh из карточки не перенесены. Существующий K5C остаётся ровно на ef92ebf, без изменения метода/данных.

## Точный состав и diff относительно production

В release ровно 22 файла: 7 modified, 15 added. Никаких удалений, dependencies/lockfile, Dockerfile/Compose или env изменений.

```sh
git diff --stat ef92ebfac3f24509382d540044d9c96338aa264e release/rm1-isolated-20261020
git diff --binary ef92ebfac3f24509382d540044d9c96338aa264e release/rm1-isolated-20261020
```

Полный patch после commit сохранён отдельно в `/tmp/eos-rm1-isolated-release.patch`. Его можно воспроизвести командой выше. В таблице SHA-256 содержимого всех payload-файлов; manifest не включает собственный hash.

| Статус | Файл | SHA-256 |
|---|---|---|
| A | `backend/api/alembic/versions/20261020_0080_raw_material_knowledge.py` | `ef7b9b69ccda2af67601c3ee569ec3984acd173ec092b8a46310d031a7bf37b5` |
| A | `backend/api/app/api/routes/raw_materials.py` | `256b271b8b1af85a9133ebe0fb8575fd72be83cf3a3d979202f1bbf4788f7e28` |
| M | `backend/api/app/core/authorization.py` | `43395e37e0485add7acc0190889a0851f1e14f9270e46e28cfb4adec9fab858e` |
| M | `backend/api/app/core/config.py` | `69e03099f09a6764f3019c0c70e0f5eebea998375c47e5fbfc44a89ac0ad3084` |
| M | `backend/api/app/main.py` | `b291ec5e4975d39092f869cde45d7651e1f90491b7ecfded5806d5739805d544` |
| M | `backend/api/app/models/__init__.py` | `3c01f7799d0e3cce1d2336d8cbf58083cfd736ef05ca4a682b9602a72c833a75` |
| A | `backend/api/app/models/raw_material.py` | `b19663c4c5c9f27269fbef186c116e557a4f1f0a86c7a6a42f403e843e8ae021` |
| A | `backend/api/app/raw_materials/__init__.py` | `477f489faacc523d45e002c6bb0020c8771a757332be7241a3a4c5a65fd59c3f` |
| A | `backend/api/app/raw_materials/service.py` | `7f0604cae26b132b591c50f806fda8b2649c08f852f966ca9f99e0cf607c801d` |
| A | `backend/api/app/schemas/raw_materials.py` | `8aed4a55c48102511728702e7a60f1d8766cabe8310bf44a4fe6410cc7cb14f3` |
| A | `backend/api/tests/test_raw_materials.py` | `21e1cb3ae10d1b301c7f57c45a9a20e98d8403fb029750229d2da0aeef85f15f` |
| A | `backend/api/tests/test_raw_materials_postgres.py` | `e1369b4a08747fafb34ccc49b33be9879ba15581039d197443b83632137085ef` |
| M | `backend/api/tests/test_requests_api.py` | `95a7e17f148d77af4e00fac899290d14ea607f59bb80f1ae36f190c1ea548723` |
| A | `docs/ROADMAP_STAGE_3_2_RAW_MATERIALS_MVP_2026-10-12.md` | `dec0571417e740c41e385c84587c776ad3d761d6bcaed2ae97016ed832ebde92` |
| A | `docs/STAGE_3_2_RAW_MATERIALS_MVP_SPEC_2026-10-12.md` | `81aca68e8d250c2cf7b948af7722d98a52611d032d6da19fadb31a9e4c8af16a` |
| M | `frontend/src/App.tsx` | `4871549f9439b55244855b274e7d602232f2f7e4ccfb9fe2169cce165b866d7e` |
| M | `frontend/src/layouts/AppLayout.tsx` | `958577b7605479c597d634a7f3f20c0e44ea060404c0e93c4bbf03128fa717f9` |
| A | `frontend/src/pages/RawMaterialsPage.css` | `497c7e03a06061777883a2df15fcd94fb904548495cffd209e677e53354a0bc5` |
| A | `frontend/src/pages/RawMaterialsPage.tsx` | `ac4b08f451d540dcf4b33036c243f8b8be7e2bd1ec1cecfdb336fbb8e6b23b8c` |
| A | `frontend/src/services/rawMaterials.ts` | `427383c8979289b6ccf7d0da7e5a42318168d04750e84a1d7743f23d7f024c9f` |
| A | `frontend/tests/rawMaterials.test.ts` | `7ada93dab220421e692204b773e70cf0a2f69d80ace1fa4a7cbe0aac4a26bfc9` |
| A | `docs/STAGE_3_2_RAW_MATERIALS_RM1_RELEASE_MANIFEST_2026-10-20.md` | `self: excluded` |

## Функциональность и зависимости

- SupplyProduct UUID — единственная товарная идентичность; additive profile, явное включение после утверждения пилота. Нет seed, name matching, автоматического создания/утверждения карточек.
- Реестр, поиск/фильтры/пагинация, карточка, приватные фото, технические сведения, immutable revisions и отдельные подтверждения, audit/optimistic locking, текущие PRIMARY/BACKUP поставщики из Supply. Денежные поля R-M1 пусты; для неразрешённых ролей отсутствуют в API. Денежная сортировка недоступна.
- Переиспользованы уже имеющиеся в ef92ebf `product_knowledge.media.normalize/store/blob_path`, `bootstrap.digest`, SupplyProduct/SupplyProductSupplier/IikoUnitMapping, общий authorize/ActionContext и record_audit_event. Эти зависимости не требуют 1c4276b.
- Новые capabilities: MATERIAL_KNOWLEDGE_READ/EDIT/CONFIRM и MATERIAL_PURCHASE_READ; старые grants не менялись. Технологии читают разрешённые управленческие/производственные роли; edit/confirm — SUPPLY_MANAGER/ADMIN. Закупочные цены — SUPPLY_MANAGER/DIRECTOR/DEPUTY_DIRECTOR/ACCOUNTANT и ADMIN.
- requirements.txt, package.json/package-lock.json, Dockerfiles и Compose идентичны base. Pillow/SQLAlchemy/Pydantic, React/TypeScript уже присутствуют. Проверено на Python 3.12.13, Node 22.23.1/npm 10.9.8, PostgreSQL 17.10; совместимо с текущими Python 3.12/Node 22 Dockerfiles.
- Фото: новый namespace `/app/uploads/product-photos/raw-materials` внутри существующего photo volume. Существующие фото/ссылки не меняются, секреты и настройки доступа не тронуты.

## Миграция

Единственная новая revision: `20261020_0080`, `down_revision = 20261009_0079`. Между production head и новой revision нет отсутствующих миграций.

Создаются только raw_material_profiles, material_specification_versions, material_specification_approvals и функция/триггеры immutable history. Tenant FK/unique/check constraints и optimistic conflict проверены на PostgreSQL. Нет INSERT/UPDATE/backfill существующих бизнес-таблиц, executions или schedules.

Пустой schema downgrade `0080 → 0079` проверен. При наличии профилей downgrade намеренно блокируется MATERIAL_KNOWLEDGE_EXISTS. После начала бизнес-пилота безопасный штатный откат — прежние API/frontend images с сохранением schema 0080 и всех знаний/фото. Удаление новой истории для отката запрещено.

## Проверки на изолированном release

| Проверка | Результат |
|---|---|
| Полный backend `uv run python -m unittest discover -s tests -v` | 1257 tests, OK, skipped=53; дополнительные окружения не настроены |
| PostgreSQL `tests.test_raw_materials_postgres` | 3 PASS: реальные migrations, constraints, immutable history, конкурентный enroll/save |
| Полный frontend `npm test` | 215 PASS, 0 skip/fail |
| `npm run build` | PASS, существующее предупреждение о размере chunk |
| ESLint всех изменённых frontend файлов + нового test | PASS |
| Общий `npm run lint` | 2 прежние ошибки AuthContext.tsx: set-state-in-effect, only-export-components; файл побайтно совпадает с ef92ebf, по repository rules не изменялся |
| Protected source paths | Supply, Automation/iiko, K3/K5B/K5C, production ProductCosts, старые migration files — без diff от ef92ebf |
| `git diff --check`, file allowlist, local document links | PASS |
| Настоящий браузер / business acceptance | Не выполнялись и не заявляются; API и DOM-tests их не заменяют |

Backend suite включает все роли R-M1, tenant isolation, audit, private photo и запрет утечки цен через list/detail/history/сортировки, а также существующие Supply/«Продукция»/K5C regression tests. Для старого upload-теста ремонтов использована временная WORK_REQUEST_UPLOAD_DIR; production данные не использованы в fixtures.

## Проверка существующего backup и восстановления

Production опрошен только read-only. Текущий Git ef92ebf и schema 0079 подтверждены, tracked worktree чистый. Прежние untracked `'2026-09-01'`, `M`, `backup/`, `output/` и необычное compose-имя сохранены без изменений. Контейнеры/их image IDs не менялись.

- Backup: `D:\EnterpriseOS\backups\postgresql\eos_postgres_2026-10-18_03-00-02.dump`, **57 987 827 байт**.
- SHA-256 на сервере и скачанной приватной копии совпали: `7a9f79dbd440ca3aae3db8249d9d208df567622fd39e3e963f11185a4283d1e2`.
- `pg_restore --list` PASS; реальный `pg_restore --no-owner --no-acl --exit-on-error` в новую локальную БД `eos_rm1_backup_restore` на отдельном временном PG17 PASS. Restored Alembic = 0079.
- На восстановленной копии прошёл цикл `0079 → 0080 → 0079 → 0080`. Сравнены count + детерминированный digest каждой из **96** существующих таблиц: содержимое неизменно. Новые три таблицы пусты; raw registry total=0.
- Read-only ASGI smoke на копии: anonymous `/raw-materials` = 401; авторизованные `/raw-materials`, candidates, `/products`, `/supply/products`, `/health`, `/health/database` = 200. Никаких POST/создания/подтверждения карточек на копии backup.
- Отдельно исходный код **ef92ebf** проверен на restored schema **0080**: health/database/products/Supply = 200; raw-materials отсутствует (404). Совместимость возврата старого кода с новой схемой подтверждена.
- Совокупный SHA-256 manifest fingerprints: `a05e73913068766bfa5c950d8cb1958723b5e1d32708b3552e28d7809672426b`.
- Временный PG cluster, fixture DB, копия dump и производные приватные данные удалены после проверок. Оригинал backup на сервере не изменяется.

**Граница:** backup от 18.10 подтверждает восстановимость, но не текущий recovery point 20.10. Перед разрешённым будущим cutover обязательны свежий согласованный backup и новый preflight. Нельзя восстанавливать backup 18.10 поверх live DB с более новыми данными. Штатный code rollback оставляет schema 0080, бизнес-данные и volume; полное DB restore — отдельное решение владельца.

Последние проверенные image IDs (перед выпуском перепроверить):

- API `sha256:841984e3141819440cd1c9f82d0db8b8b5e06d23627762845409bd3ffa2112155`.
- Frontend `sha256:c4741594bdc42606b58676ce4037de5ab74bd5270269184d71113dd5acb992512`.

В будущем затронуты только API/frontend и единственная миграция 0080. Worker, PostgreSQL, n8n и proxy не требуют перезапуска для R-M1. Эти строки — manifest, не выполненный deployment.

## GitHub и граница выпуска

SSH-agent пуст; существующий id_ed25519 требует passphrase. Попытка загрузки из Keychain отменена без ввода/замены ключа. Credentials, SSH config и origin не менялись.

Существующая авторизация gh активна. Успешно выполнена read-only проверка без изменения remote:

```sh
git -c credential.helper= -c 'credential.helper=!gh auth git-credential' ls-remote https://github.com/moonwarior658/EnterpriseOS.git refs/heads/main
```

GitHub main подтверждён как b0126cb86b92426901fcc1f18ffc86dded70473f. Для будущих разрешённых Git-операций доступен этот одноразовый HTTPS helper; SSH потребует разблокировки существующего ключа владельцем. Passphrase не запрашивалась/не сохранялась; push не выполнялся. Выпускать следует именно согласованный изолированный commit/branch, а не origin/main с K5C.

R-M2, iiko collection, ежедневное расписание, mass import, калькулятор и товарные автозамены не включены. 10 UUID остаются предложением, бизнес-карточки владелец создаст/утвердит сам после отдельного разрешения deployment. Остановка на review.
