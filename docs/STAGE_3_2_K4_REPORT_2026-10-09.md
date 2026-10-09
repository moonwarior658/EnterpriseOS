# Stage 3.2 / K4 — фотографии продукции: review

09.10.2026. Локальная реализация, без commit/push/deployment. K0–K3 на production
работают по сообщению владельца; повторный live audit не выполнялся.

## Реализовано и решения

- Одно основное фото EOS: загрузка, просмотр, замена, удаление из карточки;
  отображение в таблице/mobile/card, отдельные заглушки отсутствия и ошибки.
- Права D10/K2: ADMIN, NETWORK_MANAGER, CHEF_CONFECTIONER, HEAD_OF_PRODUCTION —
  manage; DIRECTOR/DEPUTY_DIRECTOR — read; прочим нет доступа. Сохранены tenant,
  active employee/production context и publication guards. Anonymous — 401.
- ID-only связь по стабильному UUID ProductKnowledgeProduct. Только локальный
  pointer; iiko sync/price refresh не пишут его. Source photo downloader не добавлен:
  R0 active coverage=0; source cache в будущем хранить отдельно, с EOS priority.
- JPEG/PNG/WebP, 10 MiB, 16 млн пикселей, один кадр, проверка actual format и
  полного декодирования. Нормализация в WebP ≤1600×1600 без исходных метаданных.
  Filename/remote URL не используются. Защищённая выдача без публичного mount,
  Authorization, private/no-store/nosniff; browser blob URLs освобождаются.
- Причина, expected_version, PostgreSQL row lock, digest idempotency исходного
  запроса. Изменение снимает отметку «Проверено». Duplicate retry не пишет второй
  audit; stale иной запрос — 409. DB pointer/version/audit транзакционны.
- Immutable hash blobs записываются атомарно до DB commit; старые файлы сохраняются
  после замены/удаления. Audit before/after сохраняет hash и существующий actor/role/time.
  DB failure может оставить orphan blob; автоматическое удаление не добавлено.
- Named Docker volume, backup/recovery procedure и offline checksum verifier,
  который проверяет current **и исторические** ссылки. [Runbook](STAGE_3_2_K4_STORAGE_RUNBOOK.md).

## API / DB

Migration `20261009_0077` после `0076`: nullable `local_photo_hash`, PostgreSQL hash
constraint. Downgrade запрещён при current photo или PHOTO_UPLOAD/PHOTO_DELETE
history, включая случаи удаления всех current pointers.

`GET /products/{id}/photo` — защищённый WebP; `PUT` — multipart `file`,
`expected_version`, `reason`; `DELETE` — существующий ProductCommand.
PUT/DELETE возвращают ProductRead. `ProductRead.photo` — nullable hash версии.
Настройка `PRODUCT_PHOTO_UPLOAD_DIR=/app/uploads/product-photos`, compose volume
`product_photo_uploads`. API цен и бизнес-формулы K0–K3 не изменены.

## Файлы

Backend:

- `backend/api/app/product_knowledge/media.py` — validation/storage/actions/recovery verifier.
- `backend/api/app/api/routes/product_knowledge.py` — photo API.
- `backend/api/app/core/config.py` — media directory.
- `backend/api/app/models/product_knowledge.py` — pointer/constraint.
- `backend/api/app/product_knowledge/management.py` — hash в существующем аудите.
- `backend/api/app/product_knowledge/service.py`, `app/schemas/product_knowledge.py` — read projection.
- `backend/api/alembic/versions/20261009_0077_product_photos.py`.
- `backend/api/tests/test_product_photos.py`, `test_product_photos_postgres.py`.
- `backend/api/tests/test_requests_api.py`, `test_product_knowledge_postgres.py`,
  `test_product_price_refresh_postgres.py` — актуальный ожидаемый Alembic head.

Frontend / Docker:

- `frontend/src/pages/productKnowledge/ProductPhoto.tsx` — protected image/editor.
- `frontend/src/pages/ProductKnowledgePage.tsx`, `ProductKnowledgePage.css` — integration/mobile.
- `frontend/src/pages/productKnowledge/ProductManagement.tsx` — photo action labels in history.
- `frontend/src/services/productKnowledge.ts` — nullable photo, safe photo errors.
- `frontend/tests/productPhotos.test.ts` — component interaction checks.
- `docker/compose/docker-compose.yml` — persistent API volume.

Docs: этот отчёт, storage runbook, `STAGE_3_2_PRODUCT_KNOWLEDGE_AND_PRODUCTION_SPEC.md`,
`STAGE_3_2_ARCHITECTURE.md`, `ROADMAP_STAGE_3_2_v0.1.0.md`.

## Проверки

- Фото/K2 API suite: 11 тестов, OK. Дополнительная security проверка anonymous
  GET/PUT/DELETE, JPEG/WebP acceptance: 2 теста, OK; отдельный head check — OK.
- PostgreSQL 17.10: пустой цикл `0076 → 0077 → 0076 → 0077`, OK.
  8 реальных PG тестов K1/K2/K3/K4, OK в отдельных чистых schema созданной временной
  БД (исключает влияние фото-history на прежние downgrade guards). Конкурентные
  retry/conflict, invalid hash constraint, immutable audit/guard, отдельный процесс
  backend читает committed photo с диска. Cluster остановлен и удалён.
- Frontend: 6 профильных тестов K1/K2/K3/K4, OK. Photo component проверяет private
  fetch, placeholder/error, revoke URL, manage visibility, multipart version/reason,
  duplicate guard, disabled state и 409. Это JSDOM проверки, не browser visual QA.
- Production frontend build — OK, стандартное предупреждение о chunk >500 kB.
  ESLint для всех изменённых frontend TS/TSX и нового теста — OK.
- Восстановление копии media в отдельную временную директорию: checksum current/audit
  references — OK; намеренные повреждение/отсутствие исторического файла обнаружены.
- Полный backend прогон: **1197 тестов, OK, 42 optional skips**. PostgreSQL K1–K4
  отдельно исполнены выше. Первый проход выявил старый ожидаемый Alembic head;
  assertion актуализирован, заключительный полный прогон прошёл.
- `git diff --check` — OK. Проверены полный diff tracked файлов и новые task files.

## Открытые проверки и границы

Docker здесь отсутствует: реальный restart/recreate API container, DB+volume
recovery rehearsal и production backup не проверены. Volume wiring реализован,
независимое чтение backend process подтверждено, но это не Docker evidence.
Browser на desktop/mobile и бизнес-проверка соответствия фото конкретным изделиям
также остаются открытыми. K4/Gate K не закрыты; производство K5/P не начато.

Исторические blobs сохраняются без автоматической retention; нужно наблюдать
свободное место. Source-iiko фото не импортируются. Без текущего локального фото
показывается заглушка. Runbook фиксирует будущий source-media priority contract.

Git: task files изменены/новые и не staged; существующий `?? output/` сохранён.
Ветка не менялась. Commit, push, deployment не выполнялись. Остановка на review.
