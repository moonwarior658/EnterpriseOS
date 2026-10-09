# EnterpriseOS — K2: управление продукцией, результат 09.10.2026

**Статус:** реализовано локально, остановка на review. Deployment, commit, push,
смена ветки и production mutations не выполнялись. Работа в существующей `main`
по запрету менять ветку без отдельной инструкции; исходное дерево было чистым.
K1 production / 141 загруженная позиция — подтверждение владельца в задании,
не результат нового live audit. Gate K и производственная часть остаются открытыми.

## Реализовано и принятые решения

- Полная локальная карточка EOS: отображаемое название, выбор существующей
  активной категории EOS, описание, характеристики, состав, аллергены, хранение,
  текстовые материалы для продавцов. Source name/description сохраняются отдельно;
  локально очищенное описание не возвращается из iiko. Происхождение описания видно в UI.
- ON_SALE / OFF_SALE принадлежат EOS. Soft deletion — отдельный deleted_at,
  не изменение статуса/публикации. Каталог скрывает удалённые, отдельный фильтр
  открывает их; восстановление сохраняет identity, связи, статус и локальный контент.
- Добавление через read-only выбор UUID iiko, отображение UUID и явное подтверждение
  статуса/причины. Перед записью EOS повторно читает источник и проверяет checksum,
  исходный source K1 и единицу. Системные поля не принимаются в edit DTO.
  Разные UUID с одинаковым именем не склеиваются; уже добавленный UUID не дублируется.
  Для новых UUID используются только подтверждённые Supply ID links; конфликты
  mappings/Sales links блокируют добавление. SupplyProduct/mappings по имени не создаются.
- Повторное добавление удалённого UUID восстанавливает ту же запись. Новое изделие
  получает отдельную manual batch, исходный manifest K1 не изменяется. Bootstrap
  retry продолжает видеть исходную партию, игнорируя manual batches.
- «Проверено» задаётся сервером по ActionContext: employee ID, имя и дата.
  Редактирование, смена статуса, удаление/восстановление снимают отметку.
  Фильтр непроверенных и прогресс работают по всем опубликованным неудалённым
  изделиям, включая OFF_SALE, независимо от поиска/пагинации.
- Все изменения имеют reason, версию и AuditEvent в одной транзакции. История
  показывает сотрудника, дату, причину, прежние/новые локальные и отображаемые
  значения. Product row lock и expected_version защищают от перезаписи; identical
  retry того же сотрудника не даёт второй transition/audit. Добавления дополнительно
  сериализуются source lock и unique tenant/source/UUID.
- Матрица backend/меню: управление ADMIN, NETWORK_MANAGER, CHEF_CONFECTIONER,
  HEAD_OF_PRODUCTION; просмотр DIRECTOR, DEPUTY_DIRECTOR; остальные семь ролей
  закрыты. Нет отдельной роли OPERATIONAL_DIRECTOR. Существующие production
  department/active employee guards ActionContext сохранены. Sales/Supply права не менялись.
- Eligibility guard требует published, отсутствие deleted_at и ON_SALE и блокирует
  строку при проверке. Производственных consumers пока нет; подключение guard к
  create/confirm будущих планов обязательно после gate K. Старые Sales/Supply
  данные и контракты не менялись; iiko write-методы не используются.

## API и миграция

Additive `20261009_0075` после `20261008_0074`: local content, version с default=1,
nullable deletion/verification, tenant-safe employee FK, version check и индекс
рабочего каталога. Нет data reload, смены UUID или перепубликации партии K1.
Downgrade с K2 данными/product audit останавливается; безопасный operational
rollback сохраняет схему/историю. Предыдущие migrations не изменены.

Новые API: PATCH knowledge/sale-status/verification, DELETE soft deletion,
POST restore, GET scoped history, GET iiko-candidates и POST UUID-confirmed add.
GET list/detail расширены локальными полями, allowed_actions, проверкой и версией;
list поддерживает deleted/unverified и общий progress. Полные контракты — в
[архитектуре](STAGE_3_2_ARCHITECTURE.md#k2-implementation--09102026-локально-на-review).
Каталог/карточка/история читают EOS DB. Только явный поиск/подтверждение нового
UUID обращаются к iiko read-only. В UI нет source_id/checksum/credentials/raw payload;
UUID показывается только в требуемом шаге выбора/подтверждения.

## Изменённые файлы

- Backend: `app/core/authorization.py`, `app/models/product_knowledge.py`,
  `app/schemas/product_knowledge.py`, `app/api/routes/product_knowledge.py`,
  `app/product_knowledge/{service,management,bootstrap}.py` (в `backend/api`).
- Миграция: `backend/api/alembic/versions/20261009_0075_product_knowledge_management.py`.
- Backend tests: `test_product_knowledge.py`, `test_product_knowledge_postgres.py`,
  `test_product_knowledge_management.py`, `test_product_knowledge_management_postgres.py`,
  `test_requests_api.py` (только ожидаемый single Alembic head).
- Frontend: `src/services/productKnowledge.ts`, `src/pages/ProductKnowledgePage.tsx`,
  `src/pages/ProductKnowledgePage.css`, `src/pages/productKnowledge/ProductManagement.tsx`;
  tests `productKnowledgeLive.test.ts`, `productKnowledgeManagement.test.ts`.
- Документы: текущий отчёт, Stage 3.2 spec/architecture/roadmap/open questions.
  Charter/Blueprint/ADR/общая roadmap и production configuration не изменены.

## Проверки

- Python 3.12 / uv, профильные K1/K2 tests: **21/21 PASS**. Все 13 ролей;
  read-only/denied mutations, tenant/not-found, strict DTO, category validation,
  stale version/source checksum, idempotent retries, soft delete/restore/re-add,
  progress, verification reset, audit rollback, safe source error, local/source separation.
- Полный backend suite: **1157 tests, OK, 39 skipped** (1118 успешных).
  Пропуски — отдельные внешние/интеграционные стенды; K1/K2 PostgreSQL
  выполнены отдельным обязательным прогоном, а не зачтены по skips.
  Для Repairs использован временный WORK_REQUEST_UPLOAD_DIR. Первый прогон выявил
  только старый ожидаемый head 0074 и локальный недоступный `/app/uploads`; исправлено
  ожидание head и окружение теста, бизнес-код Repairs не менялся.
- PostgreSQL 17.10: пустой upgrade всей цепочки, цикл 0074→0075→0074→0075;
  такой же цикл с опубликованной тестовой партией K1, полное сравнение её полей;
  **5/5 K1/K2 PG tests PASS**, финальные K2 **3/3 PASS**. Проверены concurrent
  retry/conflict, один UUID/один audit при concurrent add, eligibility/delete/restore,
  version constraint, запрет UPDATE/DELETE audit, отказ downgrade с бизнес-данными.
  Только disposable localhost cluster, не production; кластер остановлен и удалён.
- Frontend: production build PASS; ESLint изменённых source/test файлов PASS;
  профильные tests **4/4 PASS**, включая UUID confirmation/409/double submit.
  Полный frontend suite: **203/203 PASS**. Build сообщает о chunk >500 KB;
  переразбиение bundle вне scope K2. AuthContext baseline lint не исправлялся.
- `git diff --check`: PASS. Полный diff и новые файлы просмотрены.
- Browser/visual/business acceptance и реальные iiko credentials/read calls этого
  задания не проверялись; mock UI tests и disposable PG не заменяют эти проверки.

## Production handoff — выполнять только по отдельному заданию

1. Review текущего diff и матрицы, затем согласованный release. Проверить current
   HEAD/status/Alembic: ожидаемый baseline K1 — 0074; при отличии остановить rollout.
2. Сделать и проверить backup, подтвердить recovery path. Зафиксировать K1 batch ID,
   количество 141 и UUID/публикацию/связи/цены для сравнения после upgrade.
3. Собрать затронутые backend/frontend images; worker использует backend image и
   должен иметь совместимую модель при любых product-каталоговых обращениях.
   Выполнить upgrade 0075, затем backend, затем frontend по существующему runbook.
   Не запускать повторную публикацию/загрузку K1, не добавлять schedule K6.
4. Сверить неизменность 141 исходных UUID/batch/publication и Sales/Supply smoke.
   Проверить личные учётные записи всех разрешённых ролей и явные 403 остальных.
   У шефа/заведующего должно быть действующее назначение производства.
5. На согласованном контрольном изделии: edit→verify→edit (проверка снимается),
   OFF_SALE→delete→deleted filter→restore; UUID/history/links сохраняются.
   Два окна редактирования дают безопасный 409. Повтор HTTP-команды не даёт дубль audit.
6. С существующими read-only credentials iiko проверить поиск конкретного UUID,
   подтверждение и повторное добавление удалённого изделия. Дополнительное новое
   изделие выбирать только по согласованию владельца; никаких изменений в iiko.
   Проверить keyboard/loading/disabled/error/history и progress в браузере.
7. При rollback сохранить schema/local data/audit. Старый backend не знает soft
   deletion и новой матрицы: `/products` должен быть закрыт до возврата совместимого
   backend; простое скрытие frontend-кнопок недостаточно. Не выполнять downgrade
   с данными K2 и не восстанавливать backup поверх новых бизнес-изменений.

Ограничения: knowledge scheduled refresh остаётся K6; здесь нет нового sync/worker/
outbox. Фото, цены, ТТК/cost и production demand не реализовывались. Категории
выбираются из существующего активного EOS справочника; новые категории не создаются.
Текстовые сведения и отметка «Проверено» требуют содержательной приёмки человека.


## Финальный git status

`main`: 17 изменённых tracked файлов и 7 новых task файлов; staging отсутствует.
Commit/push/deployment не выполнялись. `git diff --check` PASS после финального
обновления документации. Посторонних изменений в исходно чистом checkout нет.


## Release review — 09.10.2026

Владелец рассмотрел отчёт и принял техническую реализацию к релизной проверке,
отдельно разрешил commit/push в main. Исторический git status выше — состояние
перед этим разрешением. Подготовлен [production runbook](STAGE_3_2_K2_PRODUCTION_RUNBOOK.md)
с backup, проверкой 141 K1 записей/manifest/UUID/цен до и после 0075 и обновлением
только API/frontend. Final diff повторно проверен; профильные K1/K2/single-head
checks **26/26 PASS**, RBAC соответствует утверждённой матрице. Production данные
на этом проходе не читались/не изменялись; rollout не выполнен. Commit SHA/push
проверяются и сообщаются после фиксации, не подставляются в документ заранее.
