# Automation Core: создание регламента цен K3 — 09.10.2026

## Причина

K3 добавил `products.sync_iiko_prices` в backend catalog и strict schema, но
frontend `buildActionPayload` не поддерживал этот action. Выбор типа был
доступен; форма отправляла `payload: {}`. Backend закономерно возвращал 422:
обязательны `source_id`, `confirmed_point_ids`, `currency=RUB`, `office_evidence`.
Локальная валидация эти параметры не проверяла, API adapter отбрасывал `loc`,
а перевод `Field required` выдавал «Заполните обязательные поля формы».
Это ошибка интеграции формы с контрактом, не ошибка заполнения видимых полей.

## Исправление

- ADMIN-only GET `/api/automation/product-price-configuration` читает policy
  последнего опубликованного снимка K3 своего tenant, проверяет активные
  explicit mappings и совпадение с подтверждёнными snapshot point links.
  При отсутствии/изменении конфигурации возвращает безопасный 409. iiko не вызывается.
- Форма загружает policy с сервера, показывает точки, RUB, обычный прейскурант
  без категории, интервал 60 минут. Source/evidence не вводятся вручную и не
  угадываются; defaults области company и interval=60. Без конфигурации
  сохранение блокируется с понятной причиной.
- POST/PATCH отправляет полный typed payload; backend strict validation не
  ослаблена. Ответы 422 сопоставляются полям формы, включая ошибки вложенного
  payload и root PriceRefreshPayload validator; сырые validation internals не
  показываются. Сообщение о дубле остаётся конкретным и безопасным.
- Создание и изменение ценового расписания блокируют существующий регламент
  tenant/source, включая выключенный. Проверка сериализована существующим
  `SalesSyncState FOR UPDATE`; UPDATE исключает собственный id. Новая миграция
  не нужна, другие automation types не меняются.
- iiko read-only, ассортимент/статусы/локальные правки/manager verification и
  безопасное поведение неизвестных SCHEDULED приоритетов не меняются.

## Проверки

Backend: 1174 tests OK, 40 optional skips; targeted price/automation API 51 OK.
Frontend: 15 tests OK, включая JSDOM формы: выбор → получение policy → field
error → успешный POST с точным payload/company/hourly. Changed-file ESLint и
production build OK; существующее предупреждение chunk >500kB остаётся.
На изолированном PostgreSQL 17 конкурентные два create сохраняют ровно один
регламент; второй получает понятную ошибку дубля. Temporary cluster удалён.

API integration test проверяет пустой payload (422), конфигурацию из snapshot,
создание (201), сохранённый payload, повторное создание (422), PATCH и GET без
потери параметров. Backend и frontend tests содержат только fixture данные.

## Production

Владелец в последней фразе задания явно поручил исправить production.
Preflight: Git `cb4176aa18790e9fae975bda8349e21a48076c8a`, Alembic 0076;
опубликованный K3 snapshot: три точки/RUB; ценовых расписаний нет. Существующие
untracked files не удаляются. Commit/push этим заданием не запрошены.

Перед обновлением созданы `C:\eos\backup\eos-price-form-fix-20261009.dump`
(48 551 509 bytes, custom format, pg_restore --list OK) и
`C:\eos\backup\eos-price-form-code-before-20261009.tar` (пять заменяемых файлов).
Исправление передаётся отдельным patch archive; обновляются API/worker/frontend,
production checkout остаётся с явным diff относительно базового SHA.
Миграция/общий iiko reference sync/создание действующего регламента автоматически
не выполняются. Итог обновления и runtime smoke фиксируется ниже.

### Итог production исправления

09.10.2026 11:54 Екатеринбург: пересобраны и обновлены только API,
automation-worker и frontend. Git HEAD остаётся `cb4176a`; пять изменённых
implementation files оставлены как явно видимый production hotfix diff,
без commit/push. Новые тесты и этот отчёт сохранены в локальном checkout.

Live HTTP GET configuration с действующим ADMIN токеном: OK, три точки/RUB
(токен не сохранялся и не выводился). На production PostgreSQL выполнен
transactional route smoke через TestClient и внешнюю rollback-транзакцию:
POST 201, missing payload 422, duplicate 422, PATCH 200, GET payload equality.
После rollback schedules count=0; statuses/local_name/local_description/version/
verified_at/verified_by_employee_id продукции совпадают до/после.
Новый действующий регламент не создавался и расписание не включалось.

Пользовательская визуальная проверка браузера остаётся владельцу: обновить
страницу, выбрать «Обновить цены продукции», проверить блок подтверждённых
трёх точек/RUB, название и company/60/Asia_Yekaterinburg; сохранить. Проверить
payload в карточке регламента и конкретную ошибку при повторном создании.
JSDOM формы и production API runtime проверены; визуальная приёмка не заявляется.

Откат кода (только при необходимости): из `C:\eos` восстановить
`tar -xf backup/eos-price-form-code-before-20261009.tar`, затем
`docker compose -f docker/compose/docker-compose.yml build api automation-worker frontend`
и `docker compose -f docker/compose/docker-compose.yml up -d --no-deps api automation-worker frontend`.
Backup БД/посторонние untracked файлы не удалять; миграции не откатывать.

Финальный read-only smoke: работающий frontend по HTTP отдаёт исправленную
форму с `getProductPriceConfiguration` и блоком параметров K3; все три сервиса
Running=true, Alembic остаётся 0076. AppleDouble `._*`, созданные нашим tar,
удалены точечно; прежние untracked files сохранены. `git diff --check` OK.

### Последующее Git consolidation

Владелец позже явно поручил Git update вместе с исправлением manual run K3.
Предыдущие записи «без commit/push» описывают первоначальный hotfix, а не
текущее разрешение. Этот код/тесты/отчёт включены в общий release diff;
[manual-run report](AUTOMATION_K3_MANUAL_RUN_FIX_2026-10-09.md) фиксирует продолжение.
